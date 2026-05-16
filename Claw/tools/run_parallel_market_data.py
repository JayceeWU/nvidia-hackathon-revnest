#!/usr/bin/env python3
"""
Run pricing-workflow market-data tools as a real parallel fan-out/fan-in batch.

The OpenClaw agent still owns browser verification, MoodTrip MCP calls, pricing
reasoning, and publishing. This helper owns the local Python/API tools that can
be launched from a normal subprocess:

- weather
- holidays
- Ticketmaster events
- SerpApi Google Events
- SerpApi Google Hotels + Vacation Rentals
- Tavily pricing context

It writes normal progress events for each child stage and stores a combined
JSON result for the pricing-decision stage to consume.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import datetime as dt
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from typing import Any
import urllib.parse

import progress_logger


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LOG_PATH = ROOT / "runs" / "airbnb-pricing-progress.log"
DEFAULT_OUTPUT_DIR = ROOT / "runs"
WORKFLOW_NAME = "pricing-workflow"
DEFAULT_DATABASE_URL = "postgres://postgres:postgres@localhost:55434/dev"


def utc_now_iso() -> str:
    return dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat()


def parse_iso_date(value: str, field_name: str) -> dt.date:
    try:
        return dt.date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} must use YYYY-MM-DD format") from exc


def load_dotenv(base_env: dict[str, str]) -> dict[str, str]:
    env = dict(base_env)
    dotenv_path = ROOT / ".env"
    if not dotenv_path.exists():
        return env

    for raw_line in dotenv_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'\"")
        if key and not env.get(key):
            env[key] = value
    return env


def database_url_from(env: dict[str, str]) -> str:
    return env.get("CLAW_DATABASE_URL") or env.get("DATABASE_URL") or DEFAULT_DATABASE_URL


def sql_literal(value: object) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def parse_database_url(database_url: str) -> dict[str, str]:
    parsed = urllib.parse.urlparse(database_url)
    return {
        "database": (parsed.path or "/dev").lstrip("/") or "dev",
        "user": urllib.parse.unquote(parsed.username or "postgres"),
    }


def run_psql_sql(sql: str, env: dict[str, str]) -> str:
    database_url = database_url_from(env)
    if shutil.which("psql", path=env.get("PATH")):
        cmd = ["psql", database_url, "-v", "ON_ERROR_STOP=1", "-tA", "-c", sql]
    else:
        info = parse_database_url(database_url)
        cmd = [
            "docker",
            "compose",
            "-f",
            str(ROOT / "data" / "docker-compose.yml"),
            "exec",
            "-T",
            "postgres",
            "psql",
            "-U",
            info["user"],
            "-d",
            info["database"],
            "-v",
            "ON_ERROR_STOP=1",
            "-tA",
            "-c",
            sql,
        ]
    result = subprocess.run(cmd, cwd=ROOT, env=env, text=True, capture_output=True, check=False)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "psql command failed").strip()
        raise RuntimeError(detail)
    return result.stdout.strip()


def market_data_summary_id(
    *,
    account_id: str,
    property_id: str,
    run_id: str,
    stage: str,
    tool: str,
    start_date: dt.date,
    end_date: dt.date,
) -> str:
    raw = "|".join([account_id, property_id, run_id, stage, tool, start_date.isoformat(), end_date.isoformat()])
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]
    return f"market-data-{digest}"


def summary_payload(
    args: argparse.Namespace,
    result: dict[str, Any],
    start_date: dt.date,
    end_date: dt.date,
    horizon: int,
    target_property_id: str,
) -> dict[str, Any]:
    summary_property_ids = getattr(args, "summary_property_ids", [args.property_id])
    payload = {
        "run_id": args.run_id,
        "account_id": args.account_id,
        "property_id": target_property_id,
        "property_type": args.property_type,
        "address": args.address,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "pricing_horizon": horizon,
        "currency": args.currency,
        "stage": result.get("stage"),
        "tool": result.get("tool"),
        "label": result.get("label"),
        "status": result.get("status"),
        "summary": result.get("summary"),
        "returncode": result.get("returncode"),
        "duration_seconds": result.get("duration_seconds"),
        "collected_at": result.get("collected_at"),
        "source_started_at": result.get("source_started_at"),
        "source_completed_at": result.get("source_completed_at"),
        "command": result.get("command"),
        "error": result.get("error"),
        "json": result.get("json"),
        "stdout_tail": result.get("stdout_tail"),
        "stderr_tail": result.get("stderr_tail"),
    }
    if len(summary_property_ids) > 1:
        payload.update({
            "sharedMarketData": True,
            "marketAnchorPropertyId": args.property_id,
            "hotelBatchRunId": args.run_id,
            "summaryPropertyIds": summary_property_ids,
        })
    return payload


def parse_summary_property_ids(args: argparse.Namespace) -> list[str]:
    property_ids = [str(args.property_id)]
    raw = getattr(args, "summary_property_ids_json", None)
    if raw:
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError("--summary-property-ids-json must be a JSON array of property ids") from exc
        if not isinstance(parsed, list):
            raise ValueError("--summary-property-ids-json must be a JSON array of property ids")
        property_ids.extend(str(item).strip() for item in parsed if str(item).strip())
    deduped: list[str] = []
    seen: set[str] = set()
    for property_id in property_ids:
        if property_id and property_id not in seen:
            deduped.append(property_id)
            seen.add(property_id)
    if not deduped:
        raise ValueError("At least one summary property id is required")
    return deduped


def write_market_data_summary(
    args: argparse.Namespace,
    result: dict[str, Any],
    start_date: dt.date,
    end_date: dt.date,
    horizon: int,
    env: dict[str, str],
    property_id: str | None = None,
) -> None:
    target_property_id = property_id or args.property_id
    status = str(result.get("status") or "failed")
    if status not in {"completed", "skipped", "failed"}:
        status = "failed"
    summary = str(result.get("summary") or result.get("error") or "Market-data tool completed without a text summary.")
    record_id = market_data_summary_id(
        account_id=args.account_id,
        property_id=target_property_id,
        run_id=args.run_id,
        stage=str(result.get("stage") or "unknown"),
        tool=str(result.get("tool") or "unknown"),
        start_date=start_date,
        end_date=end_date,
    )
    data_json = json.dumps(summary_payload(args, result, start_date, end_date, horizon, target_property_id), ensure_ascii=False, sort_keys=True)
    sql = f"""
INSERT INTO market_data_summary (
  id, account_id, property_id, run_id, stage, tool, status, summary, start_date, end_date, data
)
VALUES (
  {sql_literal(record_id)},
  {sql_literal(args.account_id)}::uuid,
  {sql_literal(target_property_id)},
  {sql_literal(args.run_id)},
  {sql_literal(result.get('stage') or 'unknown')},
  {sql_literal(result.get('tool') or 'unknown')},
  {sql_literal(status)},
  {sql_literal(summary)},
  {sql_literal(start_date.isoformat())}::date,
  {sql_literal(end_date.isoformat())}::date,
  {sql_literal(data_json)}::jsonb
)
ON CONFLICT (account_id, property_id, run_id, stage, tool, start_date, end_date)
DO UPDATE SET
  status = EXCLUDED.status,
  summary = EXCLUDED.summary,
  data = EXCLUDED.data,
  updated_at = now();
"""
    run_psql_sql(sql, env)


def read_account_property_rows(env: dict[str, str], account_id: str) -> list[dict[str, Any]]:
    sql = f"""
SELECT COALESCE(json_agg(json_build_object(
  'id', id,
  'room_count', room_count,
  'capacity', capacity,
  'data', data
) ORDER BY id), '[]'::json)::text
FROM property
WHERE account_id = {sql_literal(account_id)}::uuid;
"""
    output = run_psql_sql(sql, env)
    if not output:
        return []
    return json.loads(output.splitlines()[-1])


def number_or_none(value: Any) -> float | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace("$", "").replace(",", "").replace("%", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def int_or_none(value: Any) -> int | None:
    parsed = number_or_none(value)
    return int(round(parsed)) if parsed is not None else None


def percent_rate(value: Any) -> float | None:
    parsed = number_or_none(value)
    if parsed is None:
        return None
    return parsed / 100 if parsed > 1 else parsed


def dashboard_trend(value: str | None) -> str:
    if value in {"up", "high", "positive"}:
        return "up"
    if value in {"down", "slightly_down", "low", "negative"}:
        return "down"
    return "flat"


def result_for_stage(results: list[dict[str, Any]], stage: str) -> dict[str, Any] | None:
    matches = [result for result in results if result.get("stage") == stage]
    return next((result for result in matches if result.get("status") == "completed"), matches[0] if matches else None)


def result_json(result: dict[str, Any] | None) -> dict[str, Any]:
    payload = (result or {}).get("json")
    return payload if isinstance(payload, dict) else {}


def format_day(value: Any) -> str:
    try:
        return dt.date.fromisoformat(str(value)).strftime("%a")
    except ValueError:
        return str(value or "")[:3]


def median(values: list[float]) -> float | None:
    cleaned = sorted(value for value in values if isinstance(value, (int, float)))
    if not cleaned:
        return None
    return cleaned[len(cleaned) // 2]


def result_collected_at(result: dict[str, Any] | None) -> str:
    return str((result or {}).get("collected_at") or (result or {}).get("source_completed_at") or utc_now_iso())


def weather_dashboard_signal(
    args: argparse.Namespace,
    payload: dict[str, Any],
    summary: str | None,
    collected_at: str,
) -> dict[str, Any]:
    daily = payload.get("daily") or payload.get("days") or []
    daily = daily if isinstance(daily, list) else []
    highs = [number_or_none(day.get("temperature_max_f") or day.get("high_f") or day.get("high")) for day in daily if isinstance(day, dict)]
    highs = [value for value in highs if value is not None]
    lows = [number_or_none(day.get("temperature_min_f") or day.get("low_f") or day.get("low")) for day in daily if isinstance(day, dict)]
    lows = [value for value in lows if value is not None]
    precip_values = []
    impacts: list[str] = []
    dashboard_days = []
    for day in daily:
        if not isinstance(day, dict):
            continue
        rain_mm = number_or_none(day.get("precipitation_mm")) or 0
        precip_pct = number_or_none(day.get("precipitation_probability_max_pct"))
        if precip_pct is None:
            precip_pct = min(100, round(rain_mm * 8))
        precip_values.append(precip_pct)
        impact = str(day.get("demand_impact") or "neutral")
        impacts.append(impact)
        high = int_or_none(day.get("temperature_max_f") or day.get("high_f") or day.get("high"))
        conditions = day.get("conditions") or day.get("weather") or day.get("condition") or impact.replace("_", " ")
        dashboard_days.append({"day": format_day(day.get("date")), "high": high, "conditions": conditions})

    if any(impact == "down" for impact in impacts):
        trend = "down"
        label = "Weather risk"
        footnote = "May soften demand"
    elif any(impact == "up" for impact in impacts):
        trend = "up"
        label = "Favorable weather"
        footnote = "Supports leisure demand"
    else:
        trend = "flat"
        label = "Mild forecast" if daily else "No forecast"
        footnote = "No major impact" if daily else "Weather source unavailable"

    high_f = int(round(max(highs))) if highs else None
    low_f = int(round(min(lows))) if lows else (int(round(min(highs) - 10)) if highs else None)
    return {
        "location": payload.get("resolved_location") or payload.get("location") or args.address,
        "summary": label if not summary else label,
        "high_f": high_f,
        "low_f": low_f,
        "precip_pct": int(round(max(precip_values))) if precip_values else None,
        "trend": "neutral" if trend == "flat" else trend,
        "impactTrend": trend,
        "footnote": footnote,
        "collectedAt": collected_at,
        "days": dashboard_days[:7],
        "sourceSummary": summary,
    }


def event_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    events = payload.get("events") or []
    if not isinstance(events, list):
        return []
    output = []
    for event in events:
        if not isinstance(event, dict):
            continue
        signal = event.get("demand_signal") or {}
        output.append({
            "name": event.get("name") or event.get("title") or "Local event",
            "date": event.get("date"),
            "impact": signal.get("impact") if isinstance(signal, dict) else None,
        })
    return output


def events_dashboard_signal(
    args: argparse.Namespace,
    ticketmaster_payload: dict[str, Any],
    serpapi_payload: dict[str, Any],
    summary: str | None,
    collected_at: str,
) -> dict[str, Any]:
    events = event_items(ticketmaster_payload) + event_items(serpapi_payload)
    impact_counts: dict[str, int] = {}
    for item in events:
        impact = item.get("impact") or "unknown"
        impact_counts[impact] = impact_counts.get(impact, 0) + 1
    pressure_count = impact_counts.get("high", 0) + impact_counts.get("medium", 0)
    if pressure_count:
        headline = "Increasing Demand"
        trend = "up"
        footnote = "Pushes price up"
    elif events:
        headline = "Local events found"
        trend = "flat"
        footnote = "Monitor impact"
    else:
        headline = "No major events"
        trend = "flat"
        footnote = "No major impact"
    query = ticketmaster_payload.get("query") or serpapi_payload.get("query") or {}
    location = query.get("city") or query.get("address") or args.address
    return {
        "location": location,
        "upcoming_count": len(events),
        "headline": headline,
        "trend": trend,
        "footnote": footnote,
        "collectedAt": collected_at,
        "next": events[:5],
        "sourceSummary": summary,
    }


def hotel_comp_properties(payload: dict[str, Any]) -> list[dict[str, Any]]:
    properties = payload.get("properties") or []
    if isinstance(properties, list) and properties:
        return [item for item in properties if isinstance(item, dict)]
    output = []
    for day in payload.get("daily") or []:
        if isinstance(day, dict):
            output.extend(item for item in (day.get("properties") or []) if isinstance(item, dict))
    return output


def hotel_comp_daily_medians(payload: dict[str, Any]) -> list[float]:
    medians = []
    for day in payload.get("daily") or []:
        if not isinstance(day, dict):
            continue
        summary = day.get("summary") or {}
        value = number_or_none(summary.get("median_rate_per_night"))
        if value is not None:
            medians.append(value)
    return medians


def competitor_dashboard_signal(
    args: argparse.Namespace,
    payload: dict[str, Any],
    summary_text: str | None,
    collected_at: str,
) -> dict[str, Any]:
    summary = payload.get("summary") or {}
    medians = hotel_comp_daily_medians(payload)
    median_rate = number_or_none(summary.get("median_of_daily_medians")) or number_or_none(summary.get("median_rate_per_night")) or median(medians)
    delta_pct = 0
    if len(medians) >= 2 and medians[0]:
        delta_pct = int(round(((medians[-1] - medians[0]) / medians[0]) * 100))
    trend = "up" if delta_pct > 0 else "down" if delta_pct < 0 else "flat"
    properties = hotel_comp_properties(payload)
    return {
        "location": args.address,
        "median_rate": int(round(median_rate)) if median_rate is not None else None,
        "delta_pct": delta_pct,
        "sample_size": len(properties),
        "trend": trend,
        "collectedAt": collected_at,
        "sourceSummary": summary_text,
    }


def occupancy_dashboard_signal(property_rows: list[dict[str, Any]], horizon: int, collected_at: str) -> dict[str, Any] | None:
    available = 0
    booked = 0
    weighted_rates = []
    for row in property_rows:
        data = row.get("data") or {}
        rooms = int_or_none(row.get("room_count") or data.get("roomCount") or data.get("rooms")) or 0
        rate = percent_rate(data.get("occupancyRate") or data.get("occupancy") or data.get("portfolio_rate"))
        if rooms <= 0 or rate is None:
            continue
        room_nights = rooms * max(1, horizon)
        available += room_nights
        booked += int(round(room_nights * rate))
        weighted_rates.append((rate, room_nights))
    if not available:
        return None
    portfolio_rate = booked / available
    trend = "up" if portfolio_rate >= 0.78 else "down" if portfolio_rate < 0.55 else "flat"
    return {
        "portfolio_rate": round(portfolio_rate, 3),
        "delta_vs_last_month_pct": 0,
        "booked_room_nights": booked,
        "available_room_nights": available,
        "trend": trend,
        "collectedAt": collected_at,
    }


def build_hotel_home_dashboard_data(
    args: argparse.Namespace,
    results: list[dict[str, Any]],
    start_date: dt.date,
    end_date: dt.date,
    horizon: int,
    env: dict[str, str],
) -> dict[str, Any]:
    weather_result = result_for_stage(results, "weather")
    ticketmaster_result = result_for_stage(results, "events_ticketmaster")
    serpapi_events_result = result_for_stage(results, "events_serpapi")
    comps_result = result_for_stage(results, "hotel_comps_serpapi")
    property_rows = read_account_property_rows(env, args.account_id)
    dashboard_collected_at = utc_now_iso()

    demand_signals: dict[str, Any] = {}
    demand_signals["weather"] = weather_dashboard_signal(
        args,
        result_json(weather_result),
        (weather_result or {}).get("summary"),
        result_collected_at(weather_result),
    )
    demand_signals["events"] = events_dashboard_signal(
        args,
        result_json(ticketmaster_result),
        result_json(serpapi_events_result),
        compact_list([str((ticketmaster_result or {}).get("summary") or ""), str((serpapi_events_result or {}).get("summary") or "")], 2),
        max(result_collected_at(ticketmaster_result), result_collected_at(serpapi_events_result)),
    )
    demand_signals["competitor"] = competitor_dashboard_signal(
        args,
        result_json(comps_result),
        (comps_result or {}).get("summary"),
        result_collected_at(comps_result),
    )
    occupancy = occupancy_dashboard_signal(property_rows, horizon, dashboard_collected_at)
    if occupancy:
        demand_signals["occupancy"] = occupancy

    return {
        "demandSignals": demand_signals,
        "marketDataRun": {
            "runId": args.run_id,
            "propertyId": args.property_id,
            "propertyType": args.property_type,
            "summaryPropertyIds": getattr(args, "summary_property_ids", [args.property_id]),
            "sharedMarketData": len(getattr(args, "summary_property_ids", [args.property_id])) > 1,
            "startDate": start_date.isoformat(),
            "endDate": end_date.isoformat(),
            "pricingHorizon": horizon,
            "collectedAt": dashboard_collected_at,
            "updatedAt": dashboard_collected_at,
        },
    }


def write_hotel_home_dashboard(args: argparse.Namespace, dashboard_data: dict[str, Any], env: dict[str, str]) -> None:
    data_json = json.dumps(dashboard_data, ensure_ascii=False, sort_keys=True)
    sql = f"""
INSERT INTO hotel_home_dashboard (id, account_id, data)
VALUES ('home', {sql_literal(args.account_id)}::uuid, {sql_literal(data_json)}::jsonb)
ON CONFLICT (account_id, id)
DO UPDATE SET
  data = jsonb_set(
    hotel_home_dashboard.data || (EXCLUDED.data - 'demandSignals'),
    '{{demandSignals}}',
    COALESCE(hotel_home_dashboard.data->'demandSignals', '{{}}'::jsonb) || COALESCE(EXCLUDED.data->'demandSignals', '{{}}'::jsonb),
    true
  ),
  updated_at = now();
"""
    run_psql_sql(sql, env)

def log_event(
    *,
    run_id: str,
    stage: str,
    status: str,
    message: str,
    tool: str | None = None,
    error: str | None = None,
    log_path: Path = DEFAULT_LOG_PATH,
    metadata: dict[str, Any] | None = None,
) -> None:
    progress_logger.append_event(
        log_path,
        run_id=run_id,
        workflow=WORKFLOW_NAME,
        skill=WORKFLOW_NAME,
        stage=stage,
        status=status,
        message=message,
        tool=tool,
        error=error[:1000] if error else None,
        metadata=metadata,
    )


def positive_int_or_none(value: str | None) -> int | None:
    if value in (None, ""):
        return None
    try:
        parsed = int(float(value))
    except ValueError:
        return None
    return parsed if parsed > 0 else None


def positive_float_or_none(value: str | None) -> float | None:
    if value in (None, ""):
        return None
    try:
        parsed = float(value)
    except ValueError:
        return None
    return parsed if parsed > 0 else None


def compact_list(values: list[str], limit: int = 3) -> str:
    cleaned = []
    seen = set()
    for value in values:
        item = str(value or "").strip()
        key = item.lower()
        if item and key not in seen:
            cleaned.append(item)
            seen.add(key)
    if not cleaned:
        return ""
    shown = cleaned[:limit]
    suffix = f", plus {len(cleaned) - limit} more" if len(cleaned) > limit else ""
    return ", ".join(shown) + suffix


def item_names(items: Any, key: str = "name", limit: int = 3) -> str:
    if not isinstance(items, list):
        return ""
    return compact_list([str(item.get(key) or item.get("title") or "") for item in items if isinstance(item, dict)], limit)


def impact_counts_text(impacts: Any) -> str:
    if not isinstance(impacts, dict) or not impacts:
        return ""
    order = ["high", "medium", "low", "unknown"]
    parts = []
    for key in order:
        value = impacts.get(key)
        if value:
            parts.append(f"{value} {key}")
    for key, value in impacts.items():
        if key not in order and value:
            parts.append(f"{value} {key}")
    return ", ".join(parts)


def money_fragment(value: Any) -> str | None:
    if not isinstance(value, (int, float)):
        return None
    rounded = int(value) if float(value).is_integer() else round(float(value), 2)
    return f"USD {rounded}"


def rate_range_text(summary: dict[str, Any]) -> str:
    low = summary.get("overall_min_rate_per_night", summary.get("min_rate_per_night"))
    high = summary.get("overall_max_rate_per_night", summary.get("max_rate_per_night"))
    median = summary.get("overall_median_rate_per_night", summary.get("median_rate_per_night"))
    parts = []
    if low is not None and high is not None:
        parts.append(f"rate range {money_fragment(low)}-{money_fragment(high)}")
    if median is not None:
        parts.append(f"median {money_fragment(median)}")
    return ", ".join(part for part in parts if "None" not in part)


def summarize_json(stage: str, payload: dict[str, Any]) -> str:
    if payload.get("error"):
        return f"The {stage} source returned an error: {payload['error']}. No trusted market signal was collected from this source for the requested date range."

    if stage == "weather":
        source = payload.get("source", "weather")
        days = payload.get("days") or payload.get("daily") or []
        count = len(days) if isinstance(days, list) else 0
        fallback = " fallback" if payload.get("fallback") else ""
        risk_notes = []
        weather_days = days if isinstance(days, list) else []
        for day in weather_days:
            if not isinstance(day, dict):
                continue
            description = str(day.get("condition") or day.get("weather") or day.get("summary") or "").strip()
            demand_signal = day.get("demand_signal") or {}
            impact = demand_signal.get("impact") if isinstance(demand_signal, dict) else None
            if description or impact:
                note = " ".join(part for part in [str(day.get("date") or ""), description, f"impact={impact}" if impact else ""] if part)
                risk_notes.append(note)
        notable = compact_list(risk_notes, 2)
        if notable:
            return f"Weather{fallback} data from {source} covered {count or 'some'} day(s). Notable signals: {notable}. Use rain, heat, wind, and comfort conditions as demand and operations modifiers."
        return f"Weather{fallback} data from {source} covered {count or 'some'} day(s). No specific severe-weather signal was surfaced in the summary, so treat weather as a normal demand modifier unless the raw daily JSON says otherwise."

    if stage == "holidays":
        summary = payload.get("summary") or {}
        public_count = summary.get("public_holiday_count")
        school_count = summary.get("school_holiday_count")
        holidays = payload.get("holidays") or payload.get("public_holidays") or []
        names = item_names(holidays, limit=3)
        if public_count is not None or school_count is not None:
            return f"Holiday data found {public_count or 0} public and {school_count or 0} school holiday(s) in the requested window." + (f" Notable rows: {names}." if names else " No named holiday rows were returned for immediate ADR uplift.")
        count = len(holidays) if isinstance(holidays, list) else 0
        return f"Holiday data returned {count} holiday row(s) for the requested window." + (f" Notable rows: {names}." if names else " No named holiday rows were available in the payload.")

    if stage == "events_ticketmaster":
        summary = payload.get("summary") or {}
        events = payload.get("events") or []
        count = summary.get("event_count")
        if count is None:
            count = len(events) if isinstance(events, list) else 0
        impact_text = impact_counts_text(summary.get("demand_impact_counts"))
        names = item_names(events, limit=3)
        return f"Ticketmaster returned {count} local event(s)." + (f" Demand mix: {impact_text}." if impact_text else "") + (f" Notable events: {names}." if names else " No named events were available in the payload.")

    if stage == "events_serpapi":
        summary = payload.get("summary") or {}
        events = payload.get("events") or []
        count = summary.get("event_count")
        if count is None:
            count = len(events) if isinstance(events, list) else 0
        impact_text = impact_counts_text(summary.get("demand_impact_counts"))
        names = item_names(events, limit=3)
        return f"SerpApi Google Events returned {count} event(s) after date filtering." + (f" Demand mix: {impact_text}." if impact_text else "") + (f" Notable events: {names}." if names else " No named events were available in the payload.")

    if stage == "hotel_comps_serpapi":
        summary = payload.get("summary") or {}
        properties = payload.get("properties") or []
        count = summary.get("property_count")
        if count is None:
            count = len(properties) if isinstance(properties, list) else 0
        query = payload.get("query") or {}
        modes = []
        if query.get("includes_hotels"):
            modes.append("hotels")
        if query.get("includes_vacation_rentals"):
            modes.append("vacation rentals")
        mode_text = f" across {', '.join(modes)}" if modes else ""
        rate_text = rate_range_text(summary)
        names = item_names(properties, limit=3)
        return f"SerpApi Google Hotels returned {count} comparable properties{mode_text}." + (f" Rate snapshot: {rate_text}." if rate_text else " No usable nightly-rate range was returned.") + (f" Examples: {names}." if names else "")

    if stage == "tourism_tavily":
        searches = payload.get("searches") or []
        errors = [item.get("error") for item in searches if isinstance(item, dict) and item.get("error")]
        query_names = compact_list([str(item.get("query") or "") for item in searches if isinstance(item, dict)], 3)
        summary = payload.get("summary") or {}
        guidance = summary.get("pricing_guidance") or summary.get("guidance")
        return f"Tavily tourism-demand research completed {len(searches)} queries with {len(errors)} error(s)." + (f" Query themes: {query_names}." if query_names else "") + (f" Guidance: {guidance}" if guidance else " Use these results as context and reconcile them with events, holidays, weather, and comp rates.")

    return "Market-data tool completed and returned a payload for the requested property/date window. Review the stored JSON diagnostics for source-specific detail."


def parse_json_output(stdout: str) -> dict[str, Any] | None:
    text = stdout.strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return None
    return None


def missing_key_error(error: str | None) -> bool:
    if not error:
        return False
    lowered = error.lower()
    return "missing" in lowered and ("api_key" in lowered or "api key" in lowered)


def tail(value: str, max_chars: int = 4000) -> str:
    return value[-max_chars:] if len(value) > max_chars else value


def run_task(task: dict[str, Any], env: dict[str, str], log_path: Path, timeout_seconds: int) -> dict[str, Any]:
    stage = task["stage"]
    tool = task["tool"]
    run_id = task["run_id"]
    source_started_at = utc_now_iso()
    started = time.monotonic()

    log_event(
        run_id=run_id,
        stage=stage,
        status="started",
        message=task["start_message"],
        tool=tool,
        log_path=log_path,
    )

    try:
        proc = subprocess.run(
            task["cmd"],
            cwd=ROOT,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout_seconds,
            check=False,
        )
        duration = round(time.monotonic() - started, 3)
        source_completed_at = utc_now_iso()
        payload = parse_json_output(proc.stdout)
        error = None
        if stage == "tourism_tavily" and payload and payload.get("tool") == "pricing-context" and not payload.get("error"):
            summary = payload.get("summary") or {}
            search_count = int(summary.get("search_count") or 0)
            error_count = int(summary.get("error_count") or 0)
            if search_count and error_count >= search_count:
                error = f"all Tavily searches failed ({error_count}/{search_count}); see JSON diagnostics"
            else:
                error = None
        elif payload and payload.get("error"):
            error = str(payload["error"])
        elif proc.returncode != 0:
            error = tail((proc.stderr or proc.stdout or "").strip(), 1000) or f"exit code {proc.returncode}"

        if not error and (proc.returncode == 0 or (stage == "tourism_tavily" and payload and payload.get("tool") == "pricing-context")):
            status = "completed"
            message = summarize_json(stage, payload or {})
        elif missing_key_error(error):
            status = "skipped"
            message = f"{task['label']} was skipped because required API configuration is missing: {error}. No trusted market signal was collected from this source."
        else:
            status = "failed"
            message = f"{task['label']} failed: {error or 'the command returned no usable output'}. No trusted market signal was collected from this source."

        log_event(
            run_id=run_id,
            stage=stage,
            status=status,
            message=message,
            tool=tool,
            error=error,
            log_path=log_path,
            metadata={"duration_seconds": duration},
        )
        return {
            "stage": stage,
            "tool": tool,
            "label": task["label"],
            "status": status,
            "summary": message,
            "returncode": proc.returncode,
            "duration_seconds": duration,
            "collected_at": source_completed_at,
            "source_started_at": source_started_at,
            "source_completed_at": source_completed_at,
            "command": task["display_command"],
            "error": error,
            "json": payload,
            "stdout_tail": tail(proc.stdout),
            "stderr_tail": tail(proc.stderr),
        }
    except subprocess.TimeoutExpired as exc:
        duration = round(time.monotonic() - started, 3)
        source_completed_at = utc_now_iso()
        error = f"timed out after {timeout_seconds} seconds"
        log_event(
            run_id=run_id,
            stage=stage,
            status="failed",
            message=f"{task['label']} timed out",
            tool=tool,
            error=error,
            log_path=log_path,
            metadata={"duration_seconds": duration},
        )
        return {
            "stage": stage,
            "tool": tool,
            "label": task["label"],
            "status": "failed",
            "summary": f"{task['label']} timed out after {timeout_seconds} seconds and returned no usable market signal.",
            "returncode": 124,
            "duration_seconds": duration,
            "collected_at": source_completed_at,
            "source_started_at": source_started_at,
            "source_completed_at": source_completed_at,
            "command": task["display_command"],
            "error": error,
            "json": None,
            "stdout_tail": tail(exc.stdout or ""),
            "stderr_tail": tail(exc.stderr or ""),
        }


def python_cmd(*parts: str) -> list[str]:
    return [sys.executable, *parts]


def display_command(cmd: list[str]) -> str:
    rendered = []
    for part in cmd:
        if part == sys.executable:
            rendered.append("python3")
        elif any(char.isspace() for char in part):
            rendered.append(json.dumps(part))
        else:
            rendered.append(part)
    return " ".join(rendered)


def build_tasks(args: argparse.Namespace, end_date: dt.date, horizon: int) -> list[dict[str, Any]]:
    adults = positive_int_or_none(args.adults) or positive_int_or_none(args.capacity) or 2
    bedrooms = positive_int_or_none(args.bedrooms)
    bathrooms = positive_float_or_none(args.bathrooms)

    specs: list[tuple[str, str, str, list[str]]] = [
        (
            "weather",
            "tools/weather_tool.py",
            "weather",
            python_cmd(
                "tools/weather_tool.py",
                "weather",
                "--location",
                args.address,
                "--start-date",
                args.start_date,
                "--end-date",
                end_date.isoformat(),
            ),
        ),
        (
            "holidays",
            "tools/get_holiday.py",
            "holiday calendar",
            python_cmd(
                "tools/get_holiday.py",
                "calendar",
                "--address",
                args.address,
                "--start-date",
                args.start_date,
                "--end-date",
                end_date.isoformat(),
            ),
        ),
        (
            "events_ticketmaster",
            "tools/ticketmaster.py",
            "Ticketmaster events",
            python_cmd(
                "tools/ticketmaster.py",
                "events",
                "--address",
                args.address,
                "--start-date",
                args.start_date,
                "--end-date",
                end_date.isoformat(),
                "--limit",
                str(args.event_limit),
            ),
        ),
        (
            "events_serpapi",
            "tools/serpapi.py",
            "SerpApi Google Events",
            python_cmd(
                "tools/serpapi.py",
                "events",
                "--address",
                args.address,
                "--start-date",
                args.start_date,
                "--end-date",
                end_date.isoformat(),
                "--filter-date-range",
                "--limit",
                str(args.event_limit),
            ),
        ),
        (
            "hotel_comps_serpapi",
            "tools/serpapi.py",
            "SerpApi Google Hotels",
            python_cmd(
                "tools/serpapi.py",
                "hotels",
                "--address",
                args.address,
                "--check-in-date",
                args.start_date,
                "--pricing-horizon",
                str(horizon),
                "--search-mode",
                "both",
                "--adults",
                str(adults),
                "--currency",
                args.currency,
                "--limit",
                str(args.hotel_limit),
            ),
        ),
        (
            "tourism_tavily",
            "tools/tavily.py",
            "Tavily pricing context",
            python_cmd(
                "tools/tavily.py",
                "pricing-context",
                "--address",
                args.address,
                "--start-date",
                args.start_date,
                "--end-date",
                end_date.isoformat(),
                "--query-count",
                str(args.tavily_query_count),
                "--max-results",
                str(args.tavily_max_results),
            ),
        ),
    ]

    tasks = []
    for stage, tool, label, cmd in specs:
        if stage == "hotel_comps_serpapi":
            if bedrooms is not None:
                cmd.extend(["--bedrooms", str(bedrooms)])
            if bathrooms is not None:
                cmd.extend(["--bathrooms", str(math.ceil(bathrooms))])
        tasks.append(
            {
                "run_id": args.run_id,
                "stage": stage,
                "tool": tool,
                "label": label,
                "cmd": cmd,
                "display_command": display_command(cmd),
                "start_message": f"Fetching {label} for {args.address}",
            }
        )
    return tasks


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run pricing-workflow market-data tools in parallel")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--account-id", required=True, help="RevNest account id for market-data summary persistence")
    parser.add_argument("--property-id", required=True, help="RevNest property id for market-data summary persistence")
    parser.add_argument(
        "--summary-property-ids-json",
        help="Optional JSON array of property ids that should each receive the same shared market_data_summary rows",
    )
    parser.add_argument("--address", required=True, help="Verified property location or hotel market")
    parser.add_argument("--property-type", choices=["airbnb", "hotel"], default="airbnb", help="Pricing subject type")
    parser.add_argument("--start-date", required=True, help="First pricing date, YYYY-MM-DD")
    parser.add_argument("--end-date", help="Last pricing date, inclusive, YYYY-MM-DD")
    parser.add_argument("--pricing-horizon", type=int, help="Number of nights to price")
    parser.add_argument("--capacity", help="Listing guest capacity")
    parser.add_argument("--adults", help="Adults to use for rate searches; defaults to capacity or 2")
    parser.add_argument("--bedrooms", help="Bedroom count for vacation-rental searches")
    parser.add_argument("--bathrooms", help="Bathroom count for vacation-rental searches")
    parser.add_argument("--currency", default="USD")
    parser.add_argument("--event-limit", type=int, default=20)
    parser.add_argument("--hotel-limit", type=int, default=20)
    parser.add_argument("--tavily-query-count", type=int, default=4)
    parser.add_argument("--tavily-max-results", type=int, default=5)
    parser.add_argument("--max-workers", type=int, default=6)
    parser.add_argument("--task-timeout-seconds", type=int, default=180)
    parser.add_argument("--log-path", default=str(DEFAULT_LOG_PATH))
    parser.add_argument("--output-path", help="Combined JSON output path")
    parser.add_argument("--dry-run", action="store_true", help="Print the fan-out plan without calling APIs")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    args.summary_property_ids = parse_summary_property_ids(args)

    start = parse_iso_date(args.start_date, "start_date")
    if args.end_date:
        end = parse_iso_date(args.end_date, "end_date")
        if end < start:
            raise ValueError("end_date must be on or after start_date")
        horizon = (end - start).days + 1
    else:
        if not args.pricing_horizon or args.pricing_horizon <= 0:
            raise ValueError("provide --end-date or a positive --pricing-horizon")
        horizon = args.pricing_horizon
        end = start + dt.timedelta(days=horizon - 1)

    log_path = Path(args.log_path)
    output_path = Path(args.output_path) if args.output_path else DEFAULT_OUTPUT_DIR / f"{args.run_id}-market-data.json"
    tasks = build_tasks(args, end, horizon)

    if args.dry_run:
        print(json.dumps({"tasks": tasks, "output_path": str(output_path), "summary_property_ids": args.summary_property_ids}, indent=2, ensure_ascii=False))
        return 0

    log_event(
        run_id=args.run_id,
        stage="market_data_parallel",
        status="started",
        message=f"Starting parallel market-data fan-out: {len(tasks)} local data source(s)",
        tool="tools/run_parallel_market_data.py",
        log_path=log_path,
        metadata={"address": args.address, "property_type": args.property_type, "start_date": start.isoformat(), "end_date": end.isoformat()},
    )

    env = load_dotenv(os.environ)
    results: list[dict[str, Any]] = []
    summary_write_errors: list[dict[str, str]] = []
    max_workers = max(1, min(args.max_workers, len(tasks)))
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(run_task, task, env, log_path, args.task_timeout_seconds) for task in tasks]
        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            try:
                for summary_property_id in args.summary_property_ids:
                    write_market_data_summary(args, result, start, end, horizon, env, property_id=summary_property_id)
                result["summary_write"] = {
                    "status": "completed",
                    "table": "market_data_summary",
                    "property_ids": args.summary_property_ids,
                }
            except Exception as exc:  # noqa: BLE001 - persistence failure must be returned to the caller.
                error = str(exc)
                result["summary_write"] = {"status": "failed", "table": "market_data_summary", "error": error}
                summary_write_errors.append({"stage": result.get("stage", "unknown"), "tool": result.get("tool", "unknown"), "error": error})
                log_event(
                    run_id=args.run_id,
                    stage=result.get("stage", "market_data_parallel"),
                    status="failed",
                    message=f"Market-data summary write failed for {result.get('label', 'unknown source')}",
                    tool="postgres/market_data_summary",
                    error=error,
                    log_path=log_path,
                )
            results.append(result)

    results.sort(key=lambda item: item["stage"])
    hotel_home_dashboard: dict[str, Any] | None = None
    hotel_home_dashboard_write: dict[str, Any] | None = None
    dashboard_write_error: str | None = None
    if args.property_type == "hotel":
        try:
            hotel_home_dashboard = build_hotel_home_dashboard_data(args, results, start, end, horizon, env)
            write_hotel_home_dashboard(args, hotel_home_dashboard, env)
            hotel_home_dashboard_write = {"status": "completed", "table": "hotel_home_dashboard", "id": "home"}
        except Exception as exc:  # noqa: BLE001 - dashboard persistence is part of the hotel market-data contract.
            dashboard_write_error = str(exc)
            hotel_home_dashboard_write = {"status": "failed", "table": "hotel_home_dashboard", "id": "home", "error": dashboard_write_error}
            log_event(
                run_id=args.run_id,
                stage="market_data_parallel",
                status="failed",
                message="Hotel home dashboard write failed",
                tool="postgres/hotel_home_dashboard",
                error=dashboard_write_error,
                log_path=log_path,
            )

    status_counts: dict[str, int] = {}
    for result in results:
        status_counts[result["status"]] = status_counts.get(result["status"], 0) + 1

    if summary_write_errors:
        overall_status = "failed"
        overall_message = "Parallel market-data fan-in completed but one or more summary writes failed"
    elif dashboard_write_error:
        overall_status = "failed"
        overall_message = "Parallel market-data fan-in completed but hotel home dashboard write failed"
    elif status_counts.get("completed") == len(results):
        overall_status = "completed"
        overall_message = "Parallel market-data fan-in completed; all local data sources returned"
    elif status_counts.get("completed", 0) > 0:
        overall_status = "completed"
        overall_message = "Parallel market-data fan-in completed with partial results"
    else:
        overall_status = "failed"
        overall_message = "Parallel market-data fan-in failed; no local data source completed"

    output = {
        "run_id": args.run_id,
        "account_id": args.account_id,
        "property_id": args.property_id,
        "summary_property_ids": args.summary_property_ids,
        "address": args.address,
        "property_type": args.property_type,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "pricing_horizon": horizon,
        "currency": args.currency,
        "status": overall_status,
        "status_counts": status_counts,
        "results": results,
        "summary_write_errors": summary_write_errors,
        "hotel_home_dashboard_write": hotel_home_dashboard_write,
        "hotel_home_dashboard": hotel_home_dashboard,
        "moodtrip_note": (
            "MoodTrip hotel comps are MCP-hosted and are not launched by this local subprocess helper. "
            "Run moodtrip__searchHotelsWithRates as a separate fan-out task when that MCP tool is available."
        ),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8")

    log_event(
        run_id=args.run_id,
        stage="market_data_parallel",
        status=overall_status,
        message=f"{overall_message}; wrote {output_path}",
        tool="tools/run_parallel_market_data.py",
        log_path=log_path,
        metadata={"status_counts": status_counts, "output_path": str(output_path)},
    )

    print(json.dumps(output, indent=2, ensure_ascii=False, sort_keys=True))
    return 0 if overall_status == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
