#!/usr/bin/env python3
"""
Local RevNest MCP server for OpenClaw revenue-management tools.

This server gives OpenClaw structured access to trusted RevNest operations while
keeping database credentials, shell quoting, and large JSON payloads out of the
agent prompt. Existing Python CLIs remain the fallback compatibility layer.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from typing import Any
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
TOOLS_DIR = ROOT / "tools"
DEFAULT_LOG_PATH = ROOT / "runs" / "airbnb-pricing-progress.log"
WORKFLOW_NAME = "pricing-workflow"

if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import guardrail_review  # noqa: E402
import progress_logger  # noqa: E402
import reasoning_step_logger  # noqa: E402
import revpar_estimate  # noqa: E402
import run_pricing_agent  # noqa: E402

TOOL_NAMES = [
    "list_hotel_room_types",
    "get_property_memory",
    "log_progress",
    "upsert_reasoning_step",
    "clear_progress",
    "review_guardrails",
    "collect_market_data_bundle",
    "estimate_revpar",
    "publish_price_calendar",
    "review_hotel_price_adjustments",
    "upsert_airbnb_property_profile",
]

HOTEL_DEVIATION_ABSOLUTE_THRESHOLD = 25.0
HOTEL_DEVIATION_PERCENT_THRESHOLD = 0.15
MOCKHOTEL_HOST_API_BASE_URL = "http://localhost:3001"
MOCKHOTEL_SANDBOX_API_BASE_URL = "http://host.openshell.internal:3001"

SENSITIVE_KEY_PARTS = (
    "password",
    "password_hash",
    "api_key",
    "apikey",
    "token",
    "secret",
    "email",
    "guest",
    "booking",
    "reservation",
    "payout",
    "profit",
    "margin",
)

PROFILE_COLUMN_KEYS = {
    "capacity": "capacity",
    "zip_code": "zipCode",
    "county": "county",
    "state": "state",
    "city": "city",
    "bed": "bed",
    "bath": "bath",
    "other_info": "otherInfo",
}

AIRBNB_PROFILE_JSON_KEYS = {
    "name": ("name", "propertyName", "property_name"),
    "listingTitle": ("listingTitle", "listing_title", "title", "propertyTitle", "property_title"),
    "listingType": ("listingType", "listing_type"),
    "roomType": ("roomType", "room_type"),
    "spaceType": ("spaceType", "space_type"),
    "neighborhood": ("neighborhood",),
    "location": ("location", "market", "address"),
    "myPlace": ("myPlace", "my_place"),
    "airbnbUrl": ("airbnbUrl", "airbnb_url"),
}


def local_env(database_url: str | None = None) -> dict[str, str]:
    env = run_pricing_agent.load_dotenv(os.environ)
    if database_url:
        env["CLAW_DATABASE_URL"] = database_url
    return env


def running_in_openshell_sandbox() -> bool:
    return Path("/sandbox").exists() or os.environ.get("OPENSHELL_GATEWAY") == "nemoclaw"


def default_mockhotel_api_base_url() -> str:
    if running_in_openshell_sandbox():
        return MOCKHOTEL_SANDBOX_API_BASE_URL
    return MOCKHOTEL_HOST_API_BASE_URL


def sanitize_payload(value: Any) -> Any:
    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        for key, child in value.items():
            normalized = str(key).replace("-", "_").lower()
            if any(part in normalized for part in SENSITIVE_KEY_PARTS):
                continue
            cleaned[key] = sanitize_payload(child)
        return cleaned
    if isinstance(value, list):
        return [sanitize_payload(item) for item in value]
    return value


def compact_error(error: BaseException | str, limit: int = 1200) -> str:
    text = str(error).strip()
    return text[:limit] + ("..." if len(text) > limit else "")


def json_dumps(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def parse_json_output(stdout: str) -> dict[str, Any] | None:
    text = stdout.strip()
    if not text:
        return None
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            payload = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return None
    return payload if isinstance(payload, dict) else None


def to_optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def dollars_from_cents(value: Any) -> int | float | None:
    return run_pricing_agent.cents_to_dollars(value)


def property_memory_payload(row: dict[str, Any]) -> dict[str, Any]:
    data = sanitize_payload(dict(row.get("data") or {}))
    profile = {
        "room_count": row.get("room_count"),
        "capacity": row.get("capacity"),
        "zip_code": row.get("zip_code"),
        "county": row.get("county"),
        "state": row.get("state"),
        "city": row.get("city"),
        "bed": row.get("bed"),
        "bath": row.get("bath"),
        "other_info": row.get("other_info"),
    }
    payload: dict[str, Any] = {
        "id": row.get("id"),
        "account_id": row.get("account_id"),
        "min_price": dollars_from_cents(row.get("min_price_cents")),
        "max_price": dollars_from_cents(row.get("max_price_cents")),
        "min_price_cents": row.get("min_price_cents"),
        "max_price_cents": row.get("max_price_cents"),
        "pricing_horizon": row.get("pricing_horizon"),
        "my_place": row.get("my_place"),
        "profile": {key: value for key, value in profile.items() if value not in (None, "")},
        "data": data,
    }
    try:
        start_date, timezone_name, timezone_source = run_pricing_agent.local_pricing_start_date(row)
        payload["pricing_start_date"] = start_date
        payload["pricing_timezone"] = timezone_name
        payload["pricing_timezone_source"] = timezone_source
    except Exception as exc:  # noqa: BLE001 - memory should still be useful if timezone inference fails.
        payload["pricing_timezone_error"] = compact_error(exc)
    if data.get("propertyType") == "Hotel Room Type":
        try:
            payload["room_type_property"] = sanitize_payload(run_pricing_agent.build_room_type_property(row))
        except Exception as exc:  # noqa: BLE001
            payload["room_type_resolution_error"] = compact_error(exc)
    return payload


def list_hotel_room_types_impl(
    account_id: str,
    pricing_horizon: int | None = None,
    database_url: str | None = None,
) -> dict[str, Any]:
    env = local_env(database_url)
    rows = run_pricing_agent.read_hotel_room_type_rows(env, account_id)
    if not rows:
        raise ValueError("No Hotel Room Type properties were found for this account.")
    run_pricing_agent.validate_single_hotel_market(rows)
    room_type_properties = [run_pricing_agent.build_room_type_property(row, pricing_horizon) for row in rows]
    room_type_properties = sanitize_payload(room_type_properties)
    property_ids = [item["property_id"] for item in room_type_properties]
    anchor = room_type_properties[0]
    return {
        "status": "completed",
        "account_id": account_id,
        "hotel_scope": "all-room-types",
        "room_type_count": len(room_type_properties),
        "market_anchor_property_id": anchor["property_id"],
        "summary_property_ids": property_ids,
        "market_location": anchor.get("market_location"),
        "market_address": run_pricing_agent.room_type_market_address(anchor),
        "pricing_horizon_shared_market": int(pricing_horizon or max(item["pricing_horizon"] for item in room_type_properties)),
        "room_type_properties": room_type_properties,
    }


def get_property_memory_impl(account_id: str, property_id: str, database_url: str | None = None) -> dict[str, Any]:
    env = local_env(database_url)
    row = run_pricing_agent.read_property_row(env, account_id, property_id)
    if not row:
        raise ValueError(f"Property {property_id} was not found for account {account_id}.")
    return {"status": "completed", "property": property_memory_payload(row)}


def log_progress_impl(
    run_id: str,
    stage: str,
    status: str,
    message: str,
    property_id: str | None = None,
    substage: str | None = None,
    workflow: str | None = None,
    skill: str | None = None,
    called_skill: str | None = None,
    caller_skill: str | None = None,
    tool: str | None = None,
    error: str | None = None,
    metadata: dict[str, Any] | None = None,
    log_path: str | None = None,
) -> dict[str, Any]:
    path = Path(log_path or DEFAULT_LOG_PATH)
    payload = progress_logger.append_event(
        path,
        run_id=run_id,
        stage=stage,
        status=status,
        message=message,
        property_id=property_id,
        substage=substage,
        workflow=workflow,
        skill=skill,
        called_skill=called_skill,
        caller_skill=caller_skill,
        tool=tool,
        error=error,
        metadata=sanitize_payload(metadata) if metadata else None,
    )
    return {"status": "completed", "log_path": str(path), "event": payload}


def upsert_reasoning_step_impl(
    account_id: str,
    run_id: str,
    substage: str,
    summary: str,
    property_id: str | None = None,
    stage: str = "pricing_decision",
    facts: Any = None,
    metrics: dict[str, Any] | None = None,
    tool: str | None = None,
    sources: Any = None,
    confidence: str | None = None,
    group_key: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    return sanitize_payload(
        reasoning_step_logger.upsert_reasoning_step(
            account_id=account_id,
            run_id=run_id,
            property_id=property_id,
            stage=stage,
            substage=substage,
            summary=summary,
            facts=facts,
            metrics=metrics or {},
            tool=tool,
            sources=sources or [],
            confidence=confidence,
            group_key=group_key,
            dry_run=dry_run,
        )
    )


def clear_progress_impl(log_path: str | None = None) -> dict[str, Any]:
    return progress_logger.clear_log(log_path or DEFAULT_LOG_PATH)


def review_guardrails_impl(
    min_price: float | str,
    max_price: float | str,
    capacity: int | str | None = None,
    bedrooms: int | str | None = None,
    beds: int | str | None = None,
    bathrooms: float | str | None = None,
    property_type: str | None = None,
    market: str | None = None,
    comp_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    args = SimpleNamespace(
        min_price=str(min_price),
        max_price=str(max_price),
        capacity=None if capacity is None else str(capacity),
        bedrooms=None if bedrooms is None else str(bedrooms),
        beds=None if beds is None else str(beds),
        bathrooms=None if bathrooms is None else str(bathrooms),
        property_type=property_type,
        market=market,
        comp_summary_json=json_dumps(comp_summary or {}) if comp_summary else None,
    )
    return sanitize_payload(guardrail_review.review_guardrails(args))


def collect_market_data_bundle_impl(
    run_id: str,
    account_id: str,
    property_id: str,
    address: str,
    start_date: str,
    property_type: str = "airbnb",
    end_date: str | None = None,
    pricing_horizon: int | None = None,
    paging_horizon: int | str | None = None,
    summary_property_ids: list[str] | None = None,
    capacity: int | str | None = None,
    adults: int | str | None = None,
    bedrooms: int | str | None = None,
    bathrooms: float | str | None = None,
    currency: str = "USD",
    event_limit: int = 20,
    hotel_limit: int = 20,
    tavily_query_count: int = 4,
    tavily_max_results: int = 5,
    max_workers: int = 6,
    task_timeout_seconds: int = 180,
    timeout_seconds: int = 480,
    log_path: str | None = None,
    output_path: str | None = None,
    dry_run: bool = False,
    database_url: str | None = None,
) -> dict[str, Any]:
    resolved_pricing_horizon = pricing_horizon if pricing_horizon not in (None, "") else paging_horizon
    if not end_date and not resolved_pricing_horizon:
        raise ValueError("collect_market_data_bundle requires end_date or pricing_horizon")

    cmd = [
        sys.executable,
        str(TOOLS_DIR / "run_parallel_market_data.py"),
        "--run-id",
        run_id,
        "--account-id",
        account_id,
        "--property-id",
        property_id,
        "--address",
        address,
        "--property-type",
        property_type,
        "--start-date",
        start_date,
        "--currency",
        currency,
        "--event-limit",
        str(event_limit),
        "--hotel-limit",
        str(hotel_limit),
        "--tavily-query-count",
        str(tavily_query_count),
        "--tavily-max-results",
        str(tavily_max_results),
        "--max-workers",
        str(max_workers),
        "--task-timeout-seconds",
        str(task_timeout_seconds),
        "--log-path",
        str(log_path or DEFAULT_LOG_PATH),
        "--stdout-mode",
        "summary",
    ]
    if end_date:
        cmd.extend(["--end-date", end_date])
    if resolved_pricing_horizon:
        cmd.extend(["--pricing-horizon", str(resolved_pricing_horizon)])
    if summary_property_ids:
        cmd.extend(["--summary-property-ids-json", json_dumps(summary_property_ids)])
    optional_values = {
        "--capacity": capacity,
        "--adults": adults,
        "--bedrooms": bedrooms,
        "--bathrooms": bathrooms,
        "--output-path": output_path,
    }
    for flag, value in optional_values.items():
        if value not in (None, ""):
            cmd.extend([flag, str(value)])
    if dry_run:
        cmd.append("--dry-run")

    env = local_env(database_url)
    started = dt.datetime.now(dt.UTC)
    proc = subprocess.run(
        cmd,
        cwd=ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout_seconds,
        check=False,
    )
    duration = (dt.datetime.now(dt.UTC) - started).total_seconds()
    payload = parse_json_output(proc.stdout)
    status = "completed" if proc.returncode == 0 else "failed"
    return sanitize_payload(
        {
            "status": status,
            "returncode": proc.returncode,
            "duration_seconds": round(duration, 3),
            "payload": compact_market_data_payload(payload),
            "error": None if proc.returncode == 0 else compact_error(proc.stderr or proc.stdout),
            "stderr_tail": compact_error(proc.stderr, limit=2000) if proc.stderr else None,
        }
    )


def compact_market_data_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}

    results = []
    for item in payload.get("results") or []:
        if not isinstance(item, dict):
            continue
        result: dict[str, Any] = {
            "stage": item.get("stage") or item.get("label"),
            "status": item.get("status"),
            "tool": item.get("tool"),
            "summary": item.get("summary"),
            "error": compact_error(item.get("error")) if item.get("error") else None,
            "duration_seconds": item.get("duration_seconds"),
        }
        source_json = item.get("json")
        if isinstance(source_json, dict):
            for key in ("summary", "status", "source", "tool", "demand_signal", "rate_summary", "stats", "totals"):
                if key in source_json:
                    result[key] = source_json.get(key)
            if isinstance(source_json.get("events"), list):
                result["event_count"] = len(source_json["events"])
                result["sample_events"] = source_json["events"][:3]
            if isinstance(source_json.get("hotels"), list):
                result["hotel_count"] = len(source_json["hotels"])
                result["sample_hotels"] = source_json["hotels"][:3]
            if isinstance(source_json.get("daily"), list):
                result["daily"] = source_json["daily"][:7]
        results.append(sanitize_payload(result))

    return sanitize_payload(
        {
            "status": payload.get("status"),
            "run_id": payload.get("run_id"),
            "account_id": payload.get("account_id"),
            "property_id": payload.get("property_id"),
            "property_type": payload.get("property_type"),
            "address": payload.get("address"),
            "start_date": payload.get("start_date"),
            "end_date": payload.get("end_date"),
            "pricing_horizon": payload.get("pricing_horizon"),
            "currency": payload.get("currency"),
            "output_path": payload.get("output_path"),
            "status_counts": payload.get("status_counts"),
            "summary_write_errors": payload.get("summary_write_errors"),
            "moodtrip_note": payload.get("moodtrip_note"),
            "results": results,
        }
    )


def estimate_revpar_impl(
    property_id: str,
    price_calendar: Any,
    rooms: int = 1,
    occupancy_rate: float | str = 1.0,
) -> dict[str, Any]:
    args = SimpleNamespace(
        price_calendar_json=json_dumps(price_calendar),
        property_id=property_id,
        rooms=int(rooms),
        occupancy_rate=occupancy_rate,
    )
    rows = revpar_estimate.prepared_rows(args)
    summary = revpar_estimate.estimate_revpar(rows, int(rooms))
    daily = [
        {
            "date": row["date"],
            "current_price": revpar_estimate.cents_to_dollars(row["fixed_price_cents"]) if row.get("current_price_available") else None,
            "current_price_available": row.get("current_price_available", False),
            "agent_price": revpar_estimate.cents_to_dollars(row["agent_price_cents"]),
            "occupancy_rate": row["occupancy_rate"],
            "agent_revpar": revpar_estimate.cents_to_dollars(row["agent_price_cents"] * row["occupancy_rate"]),
        }
        for row in rows
    ]
    return {
        "status": "completed",
        "source": "revnest-revenue-tools",
        "tool": "estimate_revpar",
        "property_id": property_id,
        "currency": "USD",
        "money_unit": "dollars",
        "database_storage_unit": "cents",
        "summary": summary,
        "daily": daily,
    }


def publish_price_calendar_impl(
    account_id: str,
    property_id: str,
    price_calendar: Any,
    rooms: int = 1,
    occupancy_rate: float | str = 1.0,
    min_price: float | str | None = None,
    max_price: float | str | None = None,
    pricing_horizon: int | None = None,
    run_id: str | None = None,
    conversation_id: str | None = None,
    final_message: str | None = None,
    conversation_title: str | None = None,
    conversation_summary: str | None = None,
    property_name: str | None = None,
    property_type: str = "Airbnb",
    account_type: str | None = None,
    location: str | None = None,
    property_data: dict[str, Any] | None = None,
    conversation_data: dict[str, Any] | None = None,
    trace_events: list[dict[str, Any]] | None = None,
    trace_log_path: str | None = None,
    user_message: str | None = None,
    final_message_at: str | None = None,
    no_create_property: bool = False,
    dry_run: bool = False,
    database_url: str | None = None,
) -> dict[str, Any]:
    args = SimpleNamespace(
        price_calendar_json=json_dumps(price_calendar),
        property_id=property_id,
        rooms=int(rooms),
        occupancy_rate=occupancy_rate,
        database_url=database_url,
        psql_command="psql",
        write_method="auto",
        docker_service="postgres",
        no_create_property=no_create_property,
        account_id=account_id,
        account_email=revpar_estimate.DEFAULT_ACCOUNT_EMAIL,
        account_name=revpar_estimate.DEFAULT_ACCOUNT_NAME,
        account_type=account_type or ("hotel" if str(property_type).strip().lower().startswith("hotel") else "airbnb"),
        min_price=None if min_price is None else str(min_price),
        max_price=None if max_price is None else str(max_price),
        pricing_horizon=pricing_horizon,
        property_name=property_name,
        property_type=property_type,
        location=location,
        property_data_json=json_dumps(sanitize_payload(property_data or {})) if property_data else None,
        run_id=run_id,
        conversation_id=conversation_id,
        conversation_title=conversation_title,
        conversation_summary=conversation_summary,
        conversation_data_json=json_dumps(sanitize_payload(conversation_data or {})) if conversation_data else None,
        trace_events_json=json_dumps(sanitize_payload(trace_events or [])) if trace_events else None,
        trace_log_path=trace_log_path,
        user_message=user_message,
        final_message=final_message,
        final_message_at=final_message_at,
        dry_run=dry_run,
        include_sql=False,
    )
    rows = revpar_estimate.prepared_rows(args, require_strategy_validation=True)
    summary = revpar_estimate.estimate_revpar(rows, int(rooms))
    resolved_conversation_id = revpar_estimate.conversation_id_from(args, rows) if final_message else None
    statements: list[str] = []
    if not no_create_property:
        statements.append(revpar_estimate.build_ensure_property_sql(args, rows, summary))
    statements.append(revpar_estimate.build_upsert_sql(property_id, rows))
    if final_message:
        statements.append(revpar_estimate.build_revy_conversation_sql(args, rows, summary))
    sql = "\n\n".join(statements)

    conversation_write = (
        {"status": "pending", "table": "revy_conversation", "conversation_id": resolved_conversation_id}
        if final_message
        else {"status": "skipped", "reason": "final_message was not provided"}
    )
    if dry_run:
        return {
            "status": "completed",
            "dry_run": True,
            "property_id": property_id,
            "rows_to_write": len(rows),
            "summary": summary,
            "conversation_write": conversation_write,
        }

    write_result = revpar_estimate.run_write(revpar_estimate.database_url_from(args), sql, args)
    if final_message:
        conversation_write = {
            "status": "completed" if write_result.get("ok") else "failed",
            "table": "revy_conversation",
            "conversation_id": resolved_conversation_id,
        }
    return sanitize_payload(
        {
            "status": "completed" if write_result.get("ok") else "failed",
            "source": "revnest-revenue-tools",
            "tool": "publish_price_calendar",
            "property_id": property_id,
            "property_registration": not no_create_property,
            "currency": "USD",
            "money_unit": "dollars",
            "database_storage_unit": "cents",
            "rows_written": len(rows) if write_result.get("ok") else 0,
            "summary": summary,
            "conversation_write": conversation_write,
            "write_result": write_result,
        }
    )


def parse_iso_date(value: Any, field_name: str) -> str:
    text = str(value or "").strip()
    try:
        parsed = dt.date.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be YYYY-MM-DD") from exc
    return parsed.isoformat()


def parse_money_amount(value: Any, field_name: str) -> float:
    if value is None or value == "":
        raise ValueError(f"{field_name} is required")
    if isinstance(value, int | float):
        amount = float(value)
    else:
        amount = float(str(value).replace("$", "").replace(",", "").strip())
    if not amount or amount < 0:
        raise ValueError(f"{field_name} must be a positive dollar amount")
    return round(amount, 2)


def format_usd(value: float) -> str:
    rounded = round(float(value), 2)
    if rounded.is_integer():
        return f"${int(rounded)}"
    return f"${rounded:.2f}"


def format_signed_percent(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value * 100:+.0f}%"


def calendar_rows_from_payload(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        rows = value
    elif isinstance(value, dict):
        rows = []
        for key in ("price_calendar", "priceCalendar", "calendar", "prices", "daily"):
            if isinstance(value.get(key), list):
                rows = value[key]
                break
    else:
        rows = []
    if not rows:
        return []
    return [dict(row) for row in rows if isinstance(row, dict)]


def normalize_price_calendars_by_property_id(payload: Any) -> dict[str, list[dict[str, Any]]]:
    calendars: dict[str, list[dict[str, Any]]] = {}
    if isinstance(payload, dict):
        for property_id, value in payload.items():
            rows = calendar_rows_from_payload(value)
            if rows:
                calendars[str(property_id)] = rows
        return calendars
    if isinstance(payload, list):
        grouped: dict[str, list[dict[str, Any]]] = {}
        for row in payload:
            if not isinstance(row, dict):
                continue
            property_id = to_optional_text(row.get("property_id") or row.get("propertyId"))
            if property_id:
                grouped.setdefault(property_id, []).append(dict(row))
        return grouped
    return calendars


def price_from_calendar_row(row: dict[str, Any]) -> float:
    for key in (
        "final_price_after_guardrails",
        "finalPriceAfterGuardrails",
        "agent_price",
        "agentPrice",
        "recommended_price",
        "recommendedPrice",
        "new_price",
        "newPrice",
        "price",
    ):
        if row.get(key) not in (None, ""):
            return parse_money_amount(row[key], key)
    raise ValueError("calendar row is missing a final suggested price")


def optional_price_from_calendar_row(row: dict[str, Any], keys: tuple[str, ...]) -> float | None:
    for key in keys:
        if row.get(key) not in (None, ""):
            return parse_money_amount(row[key], key)
    return None


def date_from_calendar_row(row: dict[str, Any]) -> str:
    for key in ("date", "price_date", "priceDate", "stay_date", "stayDate"):
        if row.get(key):
            return parse_iso_date(row[key], key)
    raise ValueError("calendar row is missing a date")


def infer_calendar_date_range(
    calendars_by_property_id: dict[str, list[dict[str, Any]]],
    start_date: str | None,
    end_date: str | None,
) -> tuple[str, str]:
    if start_date and end_date:
        start = parse_iso_date(start_date, "start_date")
        end = parse_iso_date(end_date, "end_date")
    else:
        dates = [date_from_calendar_row(row) for rows in calendars_by_property_id.values() for row in rows]
        if not dates:
            raise ValueError("price_calendars_by_property_id did not contain any dated rows")
        start = parse_iso_date(start_date, "start_date") if start_date else min(dates)
        end = parse_iso_date(end_date, "end_date") if end_date else max(dates)
    if end < start:
        raise ValueError("end_date must be on or after start_date")
    return start, end


def bool_from_calendar_row(row: dict[str, Any], keys: tuple[str, ...]) -> bool:
    for key in keys:
        value = row.get(key)
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"true", "yes", "1"}:
                return True
            if normalized in {"false", "no", "0", ""}:
                return False
        if value:
            return True
    return False


def list_from_calendar_row(row: dict[str, Any], keys: tuple[str, ...]) -> list[str]:
    for key in keys:
        value = row.get(key)
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        text = to_optional_text(value)
        if text:
            return [text]
    return []


def classify_hotel_pending_task(
    row: dict[str, Any],
    current_price: float,
    suggested_price: float,
    absolute_diff: float,
    percent_diff: float | None,
    absolute_threshold: float,
    percent_threshold: float,
) -> dict[str, Any]:
    range_low = optional_price_from_calendar_row(
        row,
        (
            "suggested_price_range_low",
            "suggestedPriceRangeLow",
            "price_range_low",
            "priceRangeLow",
        ),
    )
    range_high = optional_price_from_calendar_row(
        row,
        (
            "suggested_price_range_high",
            "suggestedPriceRangeHigh",
            "price_range_high",
            "priceRangeHigh",
        ),
    )
    if range_low is not None and range_high is not None and range_low > range_high:
        range_low, range_high = range_high, range_low

    current_position = "unavailable"
    outside_strategy_range = False
    if range_low is not None and current_price < range_low:
        current_position = "below_range"
        outside_strategy_range = True
    elif range_high is not None and current_price > range_high:
        current_position = "above_range"
        outside_strategy_range = True
    elif range_low is not None or range_high is not None:
        current_position = "within_range"

    material_difference = (
        percent_diff is not None
        and absolute_diff >= absolute_threshold
        and percent_diff >= percent_threshold
    )
    confidence = str(row.get("confidence") or "").strip().lower()
    confidence_low = confidence in {"low", "weak", "very_low", "very low"}
    guardrail_warning = to_optional_text(row.get("guardrail_warning") or row.get("guardrailWarning"))
    guardrail_adjustments = list_from_calendar_row(row, ("guardrail_adjustments", "guardrailAdjustments"))
    guardrail_issue = bool_from_calendar_row(row, ("guardrail_review_needed", "guardrailReviewNeeded")) or bool(
        guardrail_warning or guardrail_adjustments
    )

    drivers: list[str] = []
    if outside_strategy_range:
        if current_position == "below_range":
            drivers.append("current MockHotel price is below Revy's strategy range")
        elif current_position == "above_range":
            drivers.append("current MockHotel price is above Revy's strategy range")
    if material_difference:
        drivers.append(
            f"final recommendation differs by {format_usd(absolute_diff)} and "
            f"{format_signed_percent(percent_diff)}"
        )
    if confidence_low:
        drivers.append(f"calculator confidence is {confidence}")
    if guardrail_issue:
        drivers.append(guardrail_warning or "guardrail review is needed")

    classification = None
    if outside_strategy_range:
        classification = "price_adjustment_required"
    elif material_difference or confidence_low or guardrail_issue:
        classification = "price_review_recommended"

    label = {
        "price_adjustment_required": "Price adjustment required",
        "price_review_recommended": "Price review recommended",
    }.get(classification)
    description = {
        "price_adjustment_required": (
            "Current MockHotel PMS price is outside Revy's strategy range. "
            "A human must approve before any live PMS sync."
        ),
        "price_review_recommended": (
            "Current MockHotel PMS price is still inside Revy's strategy range, "
            "but Revy found a material delta, low confidence, or guardrail issue. "
            "Human review is recommended before PMS sync."
        ),
    }.get(classification)
    approval_gate_label = {
        "price_adjustment_required": "Approval required",
        "price_review_recommended": "Review recommended",
    }.get(classification)

    return {
        "classification": classification,
        "classificationLabel": label,
        "classificationDescription": description,
        "approvalGateLabel": approval_gate_label,
        "should_review": classification is not None,
        "outside_strategy_range": outside_strategy_range,
        "material_difference": material_difference,
        "confidence_low": confidence_low,
        "guardrail_issue": guardrail_issue,
        "reviewDrivers": drivers,
        "strategyRange": {
            "low": range_low,
            "high": range_high,
            "currentPosition": current_position,
        },
    }


def room_type_properties_by_id(room_type_properties: Any) -> dict[str, dict[str, Any]]:
    if isinstance(room_type_properties, dict):
        items = []
        for key, value in room_type_properties.items():
            if isinstance(value, dict):
                item = dict(value)
                item.setdefault("property_id", key)
                items.append(item)
    elif isinstance(room_type_properties, list):
        items = [dict(item) for item in room_type_properties if isinstance(item, dict)]
    else:
        items = []
    result: dict[str, dict[str, Any]] = {}
    for item in items:
        data = item.get("data") if isinstance(item.get("data"), dict) else {}
        property_id = to_optional_text(item.get("property_id") or item.get("propertyId") or item.get("id") or data.get("id"))
        if property_id:
            result[property_id] = item
    return result


def room_type_display_name(property_id: str, metadata: dict[str, Any] | None, mock_room_type: dict[str, Any] | None) -> str:
    metadata = metadata or {}
    data = metadata.get("data") if isinstance(metadata.get("data"), dict) else {}
    for value in (
        metadata.get("name"),
        metadata.get("room_type"),
        metadata.get("roomType"),
        data.get("name"),
        data.get("roomType"),
        mock_room_type.get("name") if mock_room_type else None,
        mock_room_type.get("roomType") if mock_room_type else None,
        mock_room_type.get("room_type") if mock_room_type else None,
    ):
        text = to_optional_text(value)
        if text:
            return text
    return property_id


def mock_hotel_room_types_from_payload(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict) and isinstance(payload.get("roomTypes"), list):
        return [dict(item) for item in payload["roomTypes"] if isinstance(item, dict)]
    if isinstance(payload, dict) and isinstance(payload.get("room_types"), list):
        return [dict(item) for item in payload["room_types"] if isinstance(item, dict)]
    if isinstance(payload, list):
        return [dict(item) for item in payload if isinstance(item, dict)]
    return []


def mock_hotel_rates_by_room_type(payload: Any) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for room_type in mock_hotel_room_types_from_payload(payload):
        room_type_id = to_optional_text(room_type.get("id") or room_type.get("room_type_id") or room_type.get("roomTypeId"))
        prices = room_type.get("prices") if isinstance(room_type.get("prices"), dict) else {}
        if not room_type_id:
            continue
        parsed_prices = {}
        for date, price in prices.items():
            parsed_prices[parse_iso_date(date, "MockHotel price date")] = parse_money_amount(price, "MockHotel price")
        room_type["prices"] = parsed_prices
        result[room_type_id] = room_type
    return result


def fetch_mock_hotel_current_prices(
    start_date: str,
    end_date: str,
    room_type_ids: list[str],
    timeout_seconds: int = 20,
) -> dict[str, Any]:
    token = os.environ.get("MOCKHOTEL_AGENT_TOKEN")
    if not token:
        raise ValueError("MOCKHOTEL_AGENT_TOKEN is required to fetch MockHotel current prices")
    base_url = (
        os.environ.get("MOCKHOTEL_API_BASE_URL")
        or os.environ.get("REVNEST_MOCKHOTEL_API_BASE_URL")
        or default_mockhotel_api_base_url()
    ).rstrip("/")
    params = {
        "start": start_date,
        "end": end_date,
        "roomTypeIds": ",".join(room_type_ids),
    }
    url = f"{base_url}/api/agent/current-prices?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "Authorization": f"Bearer {token}"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310 - local configured service URL.
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"MockHotel current price fetch failed with HTTP {exc.code}: {compact_error(detail)}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"MockHotel current price fetch failed: {compact_error(exc)}") from exc
    payload = json.loads(body)
    if not isinstance(payload, dict):
        raise RuntimeError("MockHotel current price response was not a JSON object")
    return sanitize_payload(payload)


def build_hotel_price_adjustment_tasks(
    account_id: str,
    run_id: str,
    calendars_by_property_id: dict[str, list[dict[str, Any]]],
    mock_hotel_rates: dict[str, dict[str, Any]],
    room_type_metadata: dict[str, dict[str, Any]],
    absolute_threshold: float,
    percent_threshold: float,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    tasks: list[dict[str, Any]] = []
    comparisons: list[dict[str, Any]] = []
    missing_rates: list[dict[str, Any]] = []
    suggested_at = dt.datetime.now(dt.UTC).strftime("%Y-%m-%d %H:%M UTC")

    for property_id, rows in sorted(calendars_by_property_id.items()):
        mock_room_type = mock_hotel_rates.get(property_id)
        prices = mock_room_type.get("prices") if mock_room_type else None
        metadata = room_type_metadata.get(property_id, {})
        property_name = room_type_display_name(property_id, metadata, mock_room_type)
        if not isinstance(prices, dict):
            missing_rates.append({"property_id": property_id, "reason": "room type missing from MockHotel response"})
            continue

        for row in rows:
            date = date_from_calendar_row(row)
            suggested_price = price_from_calendar_row(row)
            current_price = prices.get(date)
            if current_price is None:
                missing_rates.append({"property_id": property_id, "date": date, "reason": "date missing from MockHotel response"})
                continue
            diff = round(suggested_price - current_price, 2)
            absolute_diff = round(abs(diff), 2)
            percent_diff = abs(diff) / current_price if current_price > 0 else None
            signed_percent = diff / current_price if current_price > 0 else None
            review_classification = classify_hotel_pending_task(
                row,
                current_price,
                suggested_price,
                absolute_diff,
                percent_diff,
                absolute_threshold,
                percent_threshold,
            )
            comparison = {
                "property_id": property_id,
                "property": property_name,
                "date": date,
                "current_price": current_price,
                "suggested_price": suggested_price,
                "deviation_abs": absolute_diff,
                "deviation_pct": percent_diff,
                "strategy_range": review_classification["strategyRange"],
                "classification": review_classification["classification"],
                "classification_label": review_classification["classificationLabel"],
                "review_drivers": review_classification["reviewDrivers"],
                "should_review": review_classification["should_review"],
            }
            comparisons.append(comparison)
            if not review_classification["should_review"]:
                continue

            change_type = "Increase" if diff > 0 else "Decrease"
            pending_task_type = review_classification["classificationLabel"]
            reason = to_optional_text(row.get("reason") or row.get("summary")) or (
                "Revy's guarded recommendation differs from MockHotel's current rate after market, "
                "guardrail, and room-type scarcity review."
            )
            review_drivers = review_classification["reviewDrivers"]
            review_reason = "; ".join(review_drivers) if review_drivers else "Revy recommends human review before PMS sync."
            task_id = f"task-hotel-review-{property_id}-{date}"
            tasks.append(
                {
                    "id": task_id,
                    "propertyId": property_id,
                    "property_id": property_id,
                    "property": property_name,
                    "priceDate": date,
                    "type": pending_task_type,
                    "taskType": review_classification["classification"],
                    "taskTypeLabel": review_classification["classificationLabel"],
                    "taskTypeDescription": review_classification["classificationDescription"],
                    "approvalGateLabel": review_classification["approvalGateLabel"],
                    "priceDirection": change_type,
                    "changeType": change_type,
                    "currentPrice": format_usd(current_price),
                    "agentSuggestedPrice": format_usd(suggested_price),
                    "change": format_signed_percent(signed_percent),
                    "agentSuggestedAt": suggested_at,
                    "reason": reason,
                    "reviewReason": review_reason,
                    "action": review_classification["classificationLabel"],
                    "status": "Needs approval",
                    "classification": review_classification["classification"],
                    "classificationLabel": review_classification["classificationLabel"],
                    "classificationDescription": review_classification["classificationDescription"],
                    "approvalRequirement": (
                        "required"
                        if review_classification["classification"] == "price_adjustment_required"
                        else "recommended"
                    ),
                    "strategyRange": review_classification["strategyRange"],
                    "reviewDrivers": review_drivers,
                    "outsideStrategyRange": review_classification["outside_strategy_range"],
                    "materialDifference": review_classification["material_difference"],
                    "confidenceLow": review_classification["confidence_low"],
                    "guardrailIssue": review_classification["guardrail_issue"],
                    "runId": run_id,
                    "accountId": account_id,
                    "threshold": {
                        "absoluteUsd": absolute_threshold,
                        "percent": percent_threshold,
                    },
                    "deviationAbs": absolute_diff,
                    "deviationPct": percent_diff,
                    "source": "mockhotel_price_review",
                    "mockHotelCurrentPrice": current_price,
                    "revySuggestedPrice": suggested_price,
                    "currency": "USD",
                }
            )
    return tasks, comparisons, missing_rates


def sql_text_array(values: list[str]) -> str:
    if not values:
        return "ARRAY[]::text[]"
    return "ARRAY[" + ", ".join(run_pricing_agent.sql_literal(value) for value in values) + "]::text[]"


def build_pending_task_sql(
    account_id: str,
    tasks: list[dict[str, Any]],
    property_ids: list[str],
    start_date: str,
    end_date: str,
) -> str:
    active_ids = [task["id"] for task in tasks]
    stale_filter = ""
    if active_ids:
        stale_filter = f"AND NOT (id = ANY({sql_text_array(active_ids)}))"
    statements = [
        f"""
WITH stale AS (
  DELETE FROM pricing_record
  WHERE account_id = {run_pricing_agent.sql_literal(account_id)}::uuid
    AND record_type = 'pending_task'
    AND data->>'source' = 'mockhotel_price_review'
    AND COALESCE(data->>'propertyId', data->>'property_id') = ANY({sql_text_array(property_ids)})
    AND data->>'priceDate' ~ '^[0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}}$'
    AND (data->>'priceDate')::date BETWEEN {run_pricing_agent.sql_literal(start_date)}::date AND {run_pricing_agent.sql_literal(end_date)}::date
    {stale_filter}
  RETURNING id
)
SELECT count(*) AS stale_tasks_deleted FROM stale;
""".strip()
    ]
    if tasks:
        values = []
        for task in tasks:
            values.append(
                "("
                + ", ".join(
                    [
                        run_pricing_agent.sql_literal(task["id"]),
                        f"{run_pricing_agent.sql_literal(account_id)}::uuid",
                        "'pending_task'",
                        f"{run_pricing_agent.sql_literal(json_dumps(sanitize_payload(task)))}::jsonb",
                    ]
                )
                + ")"
            )
        joined_values = ",\n  ".join(values)
        statements.append(
            "INSERT INTO pricing_record (id, account_id, record_type, data)\n"
            f"VALUES\n  {joined_values}\n"
            "ON CONFLICT (id)\n"
            "DO UPDATE SET\n"
            "  account_id = EXCLUDED.account_id,\n"
            "  record_type = EXCLUDED.record_type,\n"
            "  data = EXCLUDED.data,\n"
            "  updated_at = now();"
        )
    statements.append(f"SELECT {len(tasks)}::integer AS pending_tasks_upserted;")
    return "\n\n".join(statements)


def write_hotel_pending_tasks(
    account_id: str,
    tasks: list[dict[str, Any]],
    property_ids: list[str],
    start_date: str,
    end_date: str,
    database_url: str | None = None,
) -> dict[str, Any]:
    sql = build_pending_task_sql(account_id, tasks, property_ids, start_date, end_date)
    output = run_pricing_agent.run_psql_sql(sql, local_env(database_url))
    return {
        "status": "completed",
        "table": "pricing_record",
        "record_type": "pending_task",
        "tasks_upserted": len(tasks),
        "property_ids": property_ids,
        "date_range": {"start": start_date, "end": end_date},
        "psql_output_tail": output.splitlines()[-3:] if output else [],
    }


def send_discord_hotel_review_summary(
    account_id: str,
    run_id: str,
    tasks: list[dict[str, Any]],
    dry_run: bool = False,
    timeout_seconds: int = 10,
) -> dict[str, Any]:
    if dry_run:
        return {"status": "skipped", "reason": "dry_run"}
    if not tasks:
        return {"status": "skipped", "reason": "no_pending_tasks"}
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        return {"status": "skipped", "reason": "DISCORD_WEBHOOK_URL is not configured"}

    largest = sorted(tasks, key=lambda task: float(task.get("deviationAbs") or 0), reverse=True)[:8]
    lines = [
        f"Revy found {len(tasks)} MockHotel price adjustment(s) needing approval.",
        f"Run: {run_id}",
        f"Account: {account_id}",
    ]
    for task in largest:
        label = task.get("classificationLabel") or "Review recommended"
        lines.append(
            f"- {label}: {task['property']} {task['priceDate']}: {task['currentPrice']} -> "
            f"{task['agentSuggestedPrice']} ({task['change']})"
        )
    if len(tasks) > len(largest):
        lines.append(f"- plus {len(tasks) - len(largest)} more")
    content = "\n".join(lines)[:1900]
    request = urllib.request.Request(
        webhook_url,
        data=json.dumps({"content": content, "allowed_mentions": {"parse": []}}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310 - configured Discord webhook URL.
            response.read()
        return {"status": "completed", "task_count": len(tasks)}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        return {"status": "failed", "error": f"HTTP {exc.code}: {compact_error(detail)}"}
    except urllib.error.URLError as exc:
        return {"status": "failed", "error": compact_error(exc)}


def review_hotel_price_adjustments_impl(
    account_id: str,
    run_id: str,
    price_calendars_by_property_id: Any,
    room_type_properties: Any = None,
    start_date: str | None = None,
    end_date: str | None = None,
    mock_hotel_room_types: Any = None,
    absolute_threshold: float | str = HOTEL_DEVIATION_ABSOLUTE_THRESHOLD,
    percent_threshold: float | str = HOTEL_DEVIATION_PERCENT_THRESHOLD,
    dry_run: bool = False,
    database_url: str | None = None,
) -> dict[str, Any]:
    calendars_by_property_id = normalize_price_calendars_by_property_id(price_calendars_by_property_id)
    if not calendars_by_property_id:
        raise ValueError("price_calendars_by_property_id must contain at least one property calendar")
    for property_id, calendar in calendars_by_property_id.items():
        try:
            revpar_estimate.validate_strategy_guarded_calendar(calendar)
        except ValueError as exc:
            raise ValueError(f"Strategy validation failed for {property_id}: {exc}") from exc
    resolved_start_date, resolved_end_date = infer_calendar_date_range(calendars_by_property_id, start_date, end_date)
    property_ids = sorted(calendars_by_property_id)
    metadata_by_id = room_type_properties_by_id(room_type_properties)
    absolute = float(absolute_threshold)
    percent = float(percent_threshold)

    if mock_hotel_room_types is None:
        mock_payload = fetch_mock_hotel_current_prices(resolved_start_date, resolved_end_date, property_ids)
        mock_source = "mockhotel_api"
    else:
        mock_payload = {"roomTypes": mock_hotel_room_types}
        mock_source = "provided_mock_hotel_room_types"
    mock_rates = mock_hotel_rates_by_room_type(mock_payload)

    tasks, comparisons, missing_rates = build_hotel_price_adjustment_tasks(
        account_id,
        run_id,
        calendars_by_property_id,
        mock_rates,
        metadata_by_id,
        absolute,
        percent,
    )

    largest_deviations = sorted(comparisons, key=lambda item: item["deviation_abs"], reverse=True)[:10]
    if dry_run:
        database_write = {"status": "skipped", "reason": "dry_run", "tasks_to_write": len(tasks)}
    else:
        database_write = write_hotel_pending_tasks(
            account_id,
            tasks,
            property_ids,
            resolved_start_date,
            resolved_end_date,
            database_url,
        )
    discord = send_discord_hotel_review_summary(account_id, run_id, tasks, dry_run=dry_run)

    return sanitize_payload(
        {
            "status": "completed",
            "source": "revnest-revenue-tools",
            "tool": "review_hotel_price_adjustments",
            "dry_run": dry_run,
            "account_id": account_id,
            "run_id": run_id,
            "date_range": {"start": resolved_start_date, "end": resolved_end_date},
            "threshold": {"absoluteUsd": absolute, "percent": percent},
            "mock_hotel_source": mock_source,
            "room_type_count": len(property_ids),
            "comparisons_count": len(comparisons),
            "pending_task_count": len(tasks),
            "missing_rate_count": len(missing_rates),
            "pending_tasks": tasks,
            "largest_deviations": largest_deviations,
            "missing_rates": missing_rates[:20],
            "database_write": database_write,
            "discord": discord,
        }
    )


def upsert_airbnb_property_profile_impl(
    account_id: str,
    property_id: str,
    profile: dict[str, Any],
    database_url: str | None = None,
) -> dict[str, Any]:
    if not isinstance(profile, dict) or not profile:
        raise ValueError("profile must be a non-empty JSON object")

    column_values: dict[str, Any] = {}
    json_payload: dict[str, Any] = {}
    for column, json_key in PROFILE_COLUMN_KEYS.items():
        value = profile.get(column, profile.get(json_key))
        if value in (None, ""):
            continue
        if column == "capacity":
            parsed = int(value)
            if parsed < 0:
                raise ValueError("capacity cannot be negative")
            value = parsed
        else:
            value = str(value).strip()
        column_values[column] = value
        json_payload[json_key] = value

    if "bed" in column_values:
        json_payload.setdefault("beds", column_values["bed"])
    if "bath" in column_values:
        json_payload.setdefault("bathroom", column_values["bath"])
    for json_key, keys in AIRBNB_PROFILE_JSON_KEYS.items():
        value = run_pricing_agent.first_non_empty(*(profile.get(key) for key in keys))
        text_value = run_pricing_agent.normalize_optional_text(value)
        if text_value:
            json_payload[json_key] = text_value

    if json_payload:
        my_place = run_pricing_agent.normalize_optional_text(
            run_pricing_agent.first_non_empty(json_payload.get("myPlace"), json_payload.get("airbnbUrl"))
        )
        json_payload["name"] = run_pricing_agent.human_readable_airbnb_property_name(
            property_id,
            my_place,
            json_payload,
            json_payload.get("name"),
        )
        json_payload.setdefault("displayNameSource", "airbnb_human_readable")

    if not column_values and not json_payload:
        raise ValueError("profile did not contain any supported property fields")

    assignments = [f"{column} = {run_pricing_agent.sql_value(value)}" for column, value in column_values.items()]
    set_parts = assignments + [
        f"data = data || {run_pricing_agent.sql_literal(json_dumps(sanitize_payload(json_payload)))}::jsonb",
        "updated_at = now()",
    ]
    sql = f"""
UPDATE property
SET {", ".join(set_parts)}
WHERE account_id = {run_pricing_agent.sql_literal(account_id)}::uuid
  AND id = {run_pricing_agent.sql_literal(property_id)}
RETURNING json_build_object(
  'id', id,
  'account_id', account_id::text,
  'capacity', capacity,
  'zip_code', zip_code,
  'county', county,
  'state', state,
  'city', city,
  'bed', bed,
  'bath', bath,
  'other_info', other_info,
  'data', data
)::text;
"""
    output = run_pricing_agent.run_psql_sql(sql, local_env(database_url))
    if not output:
        raise ValueError(f"Property {property_id} was not found for account {account_id}.")
    json_line = next((line.strip() for line in reversed(output.splitlines()) if line.strip().startswith(("{", "["))), "")
    if not json_line:
        raise ValueError(f"Expected JSON property row from PostgreSQL, got: {output[-500:]}")
    row = json.loads(json_line)
    return {"status": "completed", "property": sanitize_payload(row)}


def create_mcp_server() -> Any:
    try:
        from mcp.server.fastmcp import FastMCP
    except ModuleNotFoundError as exc:  # pragma: no cover - depends on runtime install.
        raise RuntimeError("Install Claw/requirements.txt before starting the RevNest MCP server.") from exc

    mcp = FastMCP("revnest-revenue-tools")

    @mcp.tool()
    def list_hotel_room_types(account_id: str, pricing_horizon: int | None = None) -> dict[str, Any]:
        """Load every Hotel Room Type property for an account and validate one shared market."""
        return list_hotel_room_types_impl(account_id, pricing_horizon)

    @mcp.tool()
    def get_property_memory(account_id: str, property_id: str) -> dict[str, Any]:
        """Read trusted RevNest property memory without exposing database credentials."""
        return get_property_memory_impl(account_id, property_id)

    @mcp.tool()
    def log_progress(
        run_id: str,
        stage: str,
        status: str,
        message: str,
        property_id: str | None = None,
        substage: str | None = None,
        workflow: str | None = None,
        skill: str | None = None,
        called_skill: str | None = None,
        caller_skill: str | None = None,
        tool: str | None = None,
        error: str | None = None,
        metadata: dict[str, Any] | None = None,
        log_path: str | None = None,
    ) -> dict[str, Any]:
        """Append one WebApp-compatible JSONL workflow progress event."""
        return log_progress_impl(run_id, stage, status, message, property_id, substage, workflow, skill, called_skill, caller_skill, tool, error, metadata, log_path)

    @mcp.tool()
    def upsert_reasoning_step(
        account_id: str,
        run_id: str,
        substage: str,
        summary: str,
        property_id: str | None = None,
        stage: str = "pricing_decision",
        facts: Any = None,
        metrics: dict[str, Any] | None = None,
        tool: str | None = None,
        sources: Any = None,
        confidence: str | None = None,
        group_key: str | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Upsert one compact pricing reasoning summary to pricing_record."""
        return upsert_reasoning_step_impl(account_id, run_id, substage, summary, property_id, stage, facts, metrics, tool, sources, confidence, group_key, dry_run)

    @mcp.tool()
    def clear_progress(log_path: str | None = None) -> dict[str, Any]:
        """Truncate the pricing progress JSONL file."""
        return clear_progress_impl(log_path)

    @mcp.tool()
    def review_guardrails(
        min_price: float | str,
        max_price: float | str,
        capacity: int | str | None = None,
        bedrooms: int | str | None = None,
        beds: int | str | None = None,
        bathrooms: float | str | None = None,
        property_type: str | None = None,
        market: str | None = None,
        comp_summary: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Review min/max guardrails for plausibility before final pricing."""
        return review_guardrails_impl(min_price, max_price, capacity, bedrooms, beds, bathrooms, property_type, market, comp_summary)

    @mcp.tool()
    def collect_market_data_bundle(
        run_id: str,
        account_id: str,
        property_id: str,
        address: str,
        start_date: str,
        property_type: str = "airbnb",
        end_date: str | None = None,
        pricing_horizon: int | None = None,
        paging_horizon: int | str | None = None,
        summary_property_ids: list[str] | None = None,
        capacity: int | str | None = None,
        adults: int | str | None = None,
        bedrooms: int | str | None = None,
        bathrooms: float | str | None = None,
        currency: str = "USD",
        event_limit: int = 20,
        hotel_limit: int = 20,
        tavily_query_count: int = 4,
        tavily_max_results: int = 5,
        max_workers: int = 6,
        task_timeout_seconds: int = 180,
        timeout_seconds: int = 480,
        log_path: str | None = None,
        output_path: str | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Run the shared market-data fan-out/fan-in bundle through a structured MCP call."""
        return collect_market_data_bundle_impl(run_id, account_id, property_id, address, start_date, property_type, end_date, pricing_horizon, paging_horizon, summary_property_ids, capacity, adults, bedrooms, bathrooms, currency, event_limit, hotel_limit, tavily_query_count, tavily_max_results, max_workers, task_timeout_seconds, timeout_seconds, log_path, output_path, dry_run)

    @mcp.tool()
    def estimate_revpar(property_id: str, price_calendar: Any, rooms: int = 1, occupancy_rate: float | str = 1.0) -> dict[str, Any]:
        """Estimate ADR, revenue, and RevPAR from a guarded price calendar without writing to DB."""
        return estimate_revpar_impl(property_id, price_calendar, rooms, occupancy_rate)

    @mcp.tool()
    def publish_price_calendar(
        account_id: str,
        property_id: str,
        price_calendar: Any,
        rooms: int = 1,
        occupancy_rate: float | str = 1.0,
        min_price: float | str | None = None,
        max_price: float | str | None = None,
        pricing_horizon: int | None = None,
        run_id: str | None = None,
        conversation_id: str | None = None,
        final_message: str | None = None,
        conversation_title: str | None = None,
        conversation_summary: str | None = None,
        property_name: str | None = None,
        property_type: str = "Airbnb",
        account_type: str | None = None,
        location: str | None = None,
        property_data: dict[str, Any] | None = None,
        conversation_data: dict[str, Any] | None = None,
        trace_events: list[dict[str, Any]] | None = None,
        trace_log_path: str | None = None,
        user_message: str | None = None,
        final_message_at: str | None = None,
        no_create_property: bool = False,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Write guarded prices to property_price and optionally upsert one revy_conversation."""
        return publish_price_calendar_impl(account_id, property_id, price_calendar, rooms, occupancy_rate, min_price, max_price, pricing_horizon, run_id, conversation_id, final_message, conversation_title, conversation_summary, property_name, property_type, account_type, location, property_data, conversation_data, trace_events, trace_log_path, user_message, final_message_at, no_create_property, dry_run)

    @mcp.tool()
    def review_hotel_price_adjustments(
        account_id: str,
        run_id: str,
        price_calendars_by_property_id: Any,
        room_type_properties: Any = None,
        start_date: str | None = None,
        end_date: str | None = None,
        absolute_threshold: float | str = HOTEL_DEVIATION_ABSOLUTE_THRESHOLD,
        percent_threshold: float | str = HOTEL_DEVIATION_PERCENT_THRESHOLD,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Compare hotel recommendations against MockHotel rates and create approval tasks for large deviations."""
        return review_hotel_price_adjustments_impl(
            account_id,
            run_id,
            price_calendars_by_property_id,
            room_type_properties,
            start_date,
            end_date,
            None,
            absolute_threshold,
            percent_threshold,
            dry_run,
        )

    @mcp.tool()
    def upsert_airbnb_property_profile(account_id: str, property_id: str, profile: dict[str, Any]) -> dict[str, Any]:
        """Persist verified Airbnb profile fields extracted by pricing-context."""
        return upsert_airbnb_property_profile_impl(account_id, property_id, profile)

    return mcp


def self_test_payload() -> dict[str, Any]:
    dependency_available = True
    dependency_error = None
    try:
        import mcp  # noqa: F401
    except Exception as exc:  # noqa: BLE001
        dependency_available = False
        dependency_error = compact_error(exc)
    sample_calendar = [
        {"date": "2026-05-16", "current_price": 100, "final_price_after_guardrails": 120, "occupancy_rate": 0.8},
        {"date": "2026-05-17", "current_price": 110, "final_price_after_guardrails": 130, "occupancy_rate": 0.7},
    ]
    strategy_citation = [{"source": "Dream_Inn_Santa_Cruz_Pricing_Strategy_Manual.docx", "section": "BAR and compression"}]
    validated_sample_calendar = [
        {
            "date": "2026-05-16",
            "final_price_after_guardrails": 140,
            "strategy_memory_initial": strategy_citation,
            "strategy_memory_review": strategy_citation,
            "strategy_validation_status": "supported",
            "corrections_applied": [],
        }
    ]
    return {
        "status": "completed" if dependency_available else "dependency_missing",
        "mcp_dependency_available": dependency_available,
        "mcp_dependency_error": dependency_error,
        "tool_names": TOOL_NAMES,
        "pure_tool_checks": {
            "review_guardrails": review_guardrails_impl(80, 260, capacity=4, bedrooms=2, beds=2, bathrooms=1, property_type="entire home")["severity"],
            "estimate_revpar": estimate_revpar_impl("self-test", sample_calendar, rooms=1)["summary"]["agent_revpar"],
            "review_hotel_price_adjustments": review_hotel_price_adjustments_impl(
                "00000000-0000-0000-0000-000000000103",
                "self-test",
                {"self-test-room": validated_sample_calendar},
                [{"property_id": "self-test-room", "name": "Self Test Room"}],
                mock_hotel_room_types=[{"id": "self-test-room", "name": "Self Test Room", "prices": {"2026-05-16": "100.00"}}],
                dry_run=True,
            )["pending_task_count"],
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="RevNest local MCP server for revenue-management tools")
    parser.add_argument("--list-tools-json", action="store_true", help="Print the static RevNest MCP tool names and exit")
    parser.add_argument("--self-test", action="store_true", help="Run dependency and pure-function smoke checks without starting MCP stdio")
    args = parser.parse_args()
    if args.list_tools_json:
        print(json.dumps({"tools": TOOL_NAMES}, indent=2, ensure_ascii=False, sort_keys=True))
        return 0
    if args.self_test:
        payload = self_test_payload()
        print(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True))
        return 0
    create_mcp_server().run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
