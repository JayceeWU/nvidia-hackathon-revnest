#!/usr/bin/env python3
"""Deterministic hotel agent fixture used by the demo2 e2e test.

This script intentionally mirrors the side effects the WebApp expects from a
hotel all-room-types Revy run:

- append progress events to the run log,
- upsert hotel market dashboard data,
- upsert property_price forecast rows for every room type,
- stage MockHotel pending approval tasks via the same review helper used by the
  real agent workflow.

It is only launched when WebApp runs with REVNEST_AGENT_RUN_FIXTURE=demo2.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
TOOLS_DIR = ROOT / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import pricing_reasoning_trace  # noqa: E402
import revnest_mcp_server  # noqa: E402


DEFAULT_CLAW_DATABASE_URL = "postgres://postgres:postgres@localhost:55434/test"
DEFAULT_MOCKHOTEL_DATABASE_URL = "postgres://postgres:postgres@localhost:55432/dev"


def sql_literal(value: object) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def run_psql(database_url: str, sql: str) -> str:
    result = subprocess.run(
        ["psql", database_url, "-v", "ON_ERROR_STOP=1", "-t", "-A", "-c", sql],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stdout.strip() or "psql failed")
    return result.stdout.strip()


def psql_json(database_url: str, sql: str):
    text = run_psql(database_url, sql)
    return json.loads(text or "null")


def emit(log_path: Path, *, run_id: str, stage: str, status: str, message: str, tool: str, **extra: Any) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    event = {
        "timestamp": dt.datetime.now(dt.UTC).isoformat().replace("+00:00", "Z"),
        "run_id": run_id,
        "workflow": "pricing-workflow",
        "skill": "pricing-workflow",
        "stage": stage,
        "status": status,
        "message": message,
        "tool": tool,
        **extra,
    }
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")


def strategy_memory(section: str) -> list[dict[str, Any]]:
    return [
        {
            "source": "Demo2_E2E_Hotel_Strategy_Manual.md",
            "section": section,
            "score": 0.98,
            "content": "Use room-type guardrails, PMS current prices, occupancy, and market signals before staging human approval tasks.",
        }
    ]


def parse_price_cents(value: Any) -> int:
    return int(round(float(value) * 100))


def load_properties(database_url: str, account_id: str) -> list[dict[str, Any]]:
    sql = f"""
SELECT COALESCE(json_agg(row_to_json(rows) ORDER BY id), '[]'::json)
FROM (
  SELECT id, min_price_cents, max_price_cents, pricing_horizon, room_count, capacity, bed, bath, data
  FROM property
  WHERE account_id = {sql_literal(account_id)}::uuid
    AND data->>'propertyType' = 'Hotel Room Type'
  ORDER BY id
) rows;
"""
    return psql_json(database_url, sql)


def load_mock_prices(database_url: str, property_ids: list[str], start_date: str, end_date: str) -> dict[str, dict[str, Any]]:
    ids_sql = ", ".join(sql_literal(item) for item in property_ids)
    sql = f"""
SELECT COALESCE(json_agg(row_to_json(rows) ORDER BY id), '[]'::json)
FROM (
  SELECT
    room_type.id,
    room_type.name,
    room_type.room_type AS "roomType",
    room_type.room_count AS "roomCount",
    room_type.capacity,
    json_object_agg(room_type_price.stay_date::text, room_type_price.price_cents / 100.0 ORDER BY room_type_price.stay_date) AS prices
  FROM room_type
  JOIN room_type_price ON room_type_price.room_type_id = room_type.id
  WHERE room_type.id IN ({ids_sql})
    AND room_type_price.stay_date BETWEEN {sql_literal(start_date)}::date AND {sql_literal(end_date)}::date
  GROUP BY room_type.id, room_type.name, room_type.room_type, room_type.room_count, room_type.capacity
  ORDER BY room_type.id
) rows;
"""
    rows = psql_json(database_url, sql)
    return {row["id"]: row for row in rows}


def build_calendars(
    properties: list[dict[str, Any]],
    mock_rates: dict[str, dict[str, Any]],
    start_date: dt.date,
    target_property_id: str,
) -> dict[str, list[dict[str, Any]]]:
    calendars: dict[str, list[dict[str, Any]]] = {}
    for prop in properties:
        property_id = prop["id"]
        prices = mock_rates.get(property_id, {}).get("prices") or {}
        rows: list[dict[str, Any]] = []
        for offset in range(3):
            day = (start_date + dt.timedelta(days=offset)).isoformat()
            current_price = float(prices.get(day) or (prop["data"].get("fixedPrice") or prop["min_price_cents"] / 100))
            if property_id == target_property_id and offset == 0:
                suggested_price = max(prop["min_price_cents"] / 100 + 40, 190)
                range_low = prop["min_price_cents"] / 100
                range_high = min(prop["max_price_cents"] / 100, suggested_price + 70)
                summary = "PMS price is below the room-type minimum strategy band."
            else:
                suggested_price = current_price
                range_low = max(0, current_price - 25)
                range_high = current_price + 25
                summary = "This room type remains inside the supported strategy band."
            rows.append(
                {
                    "date": day,
                    "current_price": round(current_price, 2),
                    "final_price_after_guardrails": round(suggested_price, 2),
                    "suggested_price_range_low": round(range_low, 2),
                    "suggested_price_range_high": round(range_high, 2),
                    "estimated_occupancy": 0.78,
                    "confidence": "high",
                    "summary": summary,
                    "reason": summary,
                    "strategy_memory_initial": strategy_memory("Initial hotel strategy"),
                    "strategy_memory_review": strategy_memory("Reviewed hotel strategy"),
                    "strategy_validation_status": "supported",
                    "corrections_applied": [],
                }
            )
        calendars[property_id] = rows
    return calendars


def upsert_property_prices(database_url: str, calendars: dict[str, list[dict[str, Any]]]) -> None:
    values = []
    for property_id, rows in sorted(calendars.items()):
        for row in rows:
            values.append(
                "("
                + ", ".join(
                    [
                        sql_literal(property_id),
                        f"{sql_literal(row['date'])}::date",
                        str(parse_price_cents(row["current_price"])),
                        str(parse_price_cents(row["final_price_after_guardrails"])),
                    ]
                )
                + ")"
            )
    if not values:
        return
    sql = """
INSERT INTO property_price (property_id, price_date, fixed_price_cents, agent_price_cents)
VALUES
  {values}
ON CONFLICT (property_id, price_date)
DO UPDATE SET
  fixed_price_cents = EXCLUDED.fixed_price_cents,
  agent_price_cents = EXCLUDED.agent_price_cents,
  updated_at = now();
""".format(values=",\n  ".join(values))
    run_psql(database_url, sql)


def upsert_conversations(database_url: str, account_id: str, run_id: str, calendars: dict[str, list[dict[str, Any]]], properties: list[dict[str, Any]]) -> None:
    names = {prop["id"]: prop["data"].get("name") or prop["id"] for prop in properties}
    values = []
    for property_id, rows in sorted(calendars.items()):
        conversation_id = f"demo2-e2e-{run_id}-{property_id}"
        final_message = f"Revy updated {names[property_id]} for {len(rows)} dates and staged PMS approval when needed."
        data = {
            "conversationId": conversation_id,
            "source": "demo2-e2e-fixture",
            "runId": run_id,
            "propertyId": property_id,
            "messages": [{"role": "agent", "text": final_message, "at": dt.datetime.now(dt.UTC).isoformat().replace("+00:00", "Z")}],
            "priceCalendar": rows,
        }
        values.append(
            "("
            + ", ".join(
                [
                    sql_literal(conversation_id),
                    f"{sql_literal(account_id)}::uuid",
                    sql_literal(property_id),
                    sql_literal(f"Revy pricing for {names[property_id]}"),
                    "now()",
                    f"{sql_literal(json.dumps(data, ensure_ascii=False, sort_keys=True))}::jsonb",
                ]
            )
            + ")"
        )
    if not values:
        return
    sql = """
INSERT INTO revy_conversation (id, account_id, property_id, title, final_message_at, data)
VALUES
  {values}
ON CONFLICT (id)
DO UPDATE SET
  property_id = EXCLUDED.property_id,
  title = EXCLUDED.title,
  final_message_at = EXCLUDED.final_message_at,
  data = EXCLUDED.data,
  updated_at = now();
""".format(values=",\n  ".join(values))
    run_psql(database_url, sql)


def upsert_hotel_dashboard(database_url: str, account_id: str, run_id: str, start_date: str, end_date: str) -> None:
    now = dt.datetime.now(dt.UTC).isoformat().replace("+00:00", "Z")
    data = {
        "demandSignals": {
            "weather": {
                "location": "Santa Cruz, CA",
                "summary": "Sunny demand window",
                "high_f": 72,
                "low_f": 56,
                "precip_pct": 4,
                "trend": "up",
                "collectedAt": now,
                "footnote": "Weather signal updated for the pricing window",
                "days": [
                    {"day": "D1", "high": 72, "conditions": "sunny"},
                    {"day": "D2", "high": 70, "conditions": "sunny"},
                    {"day": "D3", "high": 69, "conditions": "clear"},
                ],
            },
            "events": {
                "location": "Santa Cruz",
                "headline": "Increasing Demand",
                "upcoming_count": 3,
                "trend": "up",
                "collectedAt": now,
                "footnote": "Local event pressure detected",
                "next": [],
            },
            "competitor": {
                "location": "Santa Cruz, CA",
                "median_rate": 244,
                "sample_size": 6,
                "delta_pct": 5,
                "trend": "up",
                "collectedAt": now,
            },
            "occupancy": {
                "portfolio_rate": 0.82,
                "booked_room_nights": 42,
                "available_room_nights": 51,
                "delta_vs_last_month_pct": 6,
                "trend": "up",
                "collectedAt": now,
            },
        },
        "marketDataRun": {
            "runId": run_id,
            "propertyId": "hotel-home",
            "propertyType": "hotel",
            "startDate": start_date,
            "endDate": end_date,
            "pricingHorizon": 3,
            "collectedAt": now,
            "updatedAt": now,
            "source": "demo2-e2e-fixture",
        },
    }
    sql = """
INSERT INTO hotel_home_dashboard (id, account_id, data)
VALUES ('home', {account_id}::uuid, {data}::jsonb)
ON CONFLICT (account_id, id)
DO UPDATE SET data = EXCLUDED.data, updated_at = now();
""".format(account_id=sql_literal(account_id), data=sql_literal(json.dumps(data, ensure_ascii=False, sort_keys=True)))
    run_psql(database_url, sql)



def emit_demo_reasoning_trace(
    *,
    log_path: Path,
    database_url: str,
    account_id: str,
    run_id: str,
    properties: list[dict[str, Any]],
    mock_rates: dict[str, dict[str, Any]],
    calendars: dict[str, list[dict[str, Any]]],
    target_property_id: str,
    review: dict[str, Any],
) -> None:
    target_rows = calendars.get(target_property_id) or next(iter(calendars.values()), [])
    target_row = target_rows[0] if target_rows else {}
    target_property = next((prop for prop in properties if prop["id"] == target_property_id), properties[0])
    target_name = target_property.get("data", {}).get("name") or target_property_id
    room_type_count = len(properties)
    total_rooms = sum(int(prop.get("room_count") or prop.get("data", {}).get("roomCount") or 0) for prop in properties)
    current_price = target_row.get("current_price")
    final_price = target_row.get("final_price_after_guardrails")
    pending_count = int(review.get("pending_task_count") or 0)
    min_price = round(float(target_property.get("min_price_cents") or 0) / 100, 2)
    max_price = round(float(target_property.get("max_price_cents") or 0) / 100, 2)

    steps = [
        {
            "substage": "supply_snapshot",
            "summary": f"MockHotel exposed {room_type_count} room types and {total_rooms} rooms, so supply is evaluated as hotel inventory rather than a single listing.",
            "facts": [f"{room_type_count} room types", f"{total_rooms} total rooms", "read-only MockHotel PMS prices"],
            "metrics": {"room_type_count": room_type_count, "total_rooms": total_rooms, "mockhotel_rate_sets": len(mock_rates)},
            "sources": ["MockHotel room_type", "MockHotel room_type_price"],
            "property_id": None,
        },
        {
            "substage": "demand_snapshot",
            "summary": "Hotel demand is elevated by Santa Cruz market signals: sunny weather, event pressure, and positive occupancy trend.",
            "facts": ["sunny demand window", "3 local event signals", "portfolio occupancy trend is up"],
            "metrics": {"event_count": 3, "portfolio_occupancy": 0.82, "weather_high_f": 72},
            "sources": ["hotel_home_dashboard", "local market signals"],
            "property_id": None,
        },
        {
            "substage": "supply_demand_synthesis",
            "summary": "Supply is available but demand is elevated, so Revy uses a supported strategy band instead of writing directly to PMS.",
            "facts": ["available hotel inventory", "elevated demand signals", "human approval boundary required"],
            "metrics": {"demand_level": "elevated", "approval_boundary": True},
            "sources": ["strategy_memory", "Safe PMS policy"],
            "property_id": None,
        },
        {
            "substage": "occupancy_result",
            "summary": "Estimated occupancy is 78% for the pricing window, matching the hotel strategy evidence used by the calculator.",
            "facts": ["portfolio rate 82%", "room-level estimate 78%", "3-night pricing horizon"],
            "metrics": {"estimated_occupancy": 0.78, "portfolio_occupancy": 0.82, "pricing_horizon": len(target_rows)},
            "sources": ["occupancy estimate", "strategy_memory"],
            "property_id": None,
        },
        {
            "substage": "guardrail_check",
            "summary": f"{target_name} keeps final recommendations inside the room-type guardrails of USD {min_price:.0f}-USD {max_price:.0f}.",
            "facts": [target_name, "room-type min/max guardrails", "no direct PMS write"],
            "metrics": {"min_price": min_price, "max_price": max_price},
            "sources": ["property guardrails", "pricing-output-publisher"],
            "property_id": target_property_id,
        },
        {
            "substage": "calculator_run",
            "summary": f"The deterministic calculator compared PMS USD {current_price} with Revy USD {final_price} for {target_name} before staging approval.",
            "facts": ["current PMS price read", "guarded Revy recommendation calculated", "pending task classified after comparison"],
            "metrics": {"current_price": current_price, "final_price_after_guardrails": final_price, "pending_task_count": pending_count},
            "sources": ["property_price", "review_hotel_price_adjustments"],
            "property_id": target_property_id,
        },
        {
            "substage": "final_calendar",
            "summary": f"Revy saved guarded forecast rows for {len(calendars)} room type(s) and left MockHotel writes behind the approval gate.",
            "facts": ["property_price forecasts updated", "MockHotel writes blocked until approval", "room-type calendars saved"],
            "metrics": {"room_type_calendars": len(calendars), "pending_task_count": pending_count},
            "sources": ["tools/revpar_estimate.py", "Safe PMS approval boundary"],
            "property_id": target_property_id,
        },
        {
            "substage": "final_reasoning_verification",
            "summary": "Final verification approved the safe flow: read-only PMS evidence, guarded forecast output, and human approval before live PMS writes.",
            "facts": ["read-only PMS evidence", "forecast rows only", "human approval required before PMS write"],
            "metrics": {"status": "approved", "pms_write_blocked": True, "pending_task_count": pending_count},
            "sources": ["safe-pms-policy", "revnest-safe-pms"],
            "property_id": target_property_id,
            "status": "completed",
        },
    ]

    for step in steps:
        pricing_reasoning_trace.emit_compact_reasoning_step(
            log_path=log_path,
            account_id=account_id,
            run_id=run_id,
            property_id=step.get("property_id"),
            substage=step["substage"],
            summary=step["summary"],
            facts=step["facts"],
            metrics=step["metrics"],
            tool="demo2_agent_fixture.py",
            sources=step["sources"],
            confidence="high" if step["substage"] == "final_reasoning_verification" else "medium",
            database_url=database_url,
            engine="demo_fixture",
            model="demo2-e2e-fixture",
            endpoint="local-fixture",
            status=step.get("status", "info"),
            group_key="demo2-hotel-safe-pms",
        )


def mark_properties_finished(database_url: str, account_id: str, run_id: str, conversation_id: str | None) -> None:
    payload = {
        "lastAgentRunId": run_id,
        "agentRunStatus": "completed",
        "agentRunFinishedAt": dt.datetime.now(dt.UTC).isoformat().replace("+00:00", "Z"),
        **({"lastRevyConversationId": conversation_id} if conversation_id else {}),
    }
    sql = """
UPDATE property
SET data = data - 'activeAgentRunId' - 'agentRunStartedAt' - 'agentRunHotelScope' || {payload}::jsonb,
    updated_at = now()
WHERE account_id = {account_id}::uuid
  AND data->>'activeAgentRunId' = {run_id};
""".format(
        payload=sql_literal(json.dumps(payload, ensure_ascii=False, sort_keys=True)),
        account_id=sql_literal(account_id),
        run_id=sql_literal(run_id),
    )
    run_psql(database_url, sql)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--account-id", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--conversation-id")
    parser.add_argument("--log-path", required=True)
    parser.add_argument("--property-type", default="hotel")
    parser.add_argument("--hotel-scope", default="all-room-types")
    args, _unknown = parser.parse_known_args()

    claw_database_url = os.environ.get("CLAW_TEST_DATABASE_URL") or DEFAULT_CLAW_DATABASE_URL
    mockhotel_database_url = os.environ.get("MOCKHOTEL_DATABASE_URL") or os.environ.get("MOCK_HOTEL_DATABASE_URL") or DEFAULT_MOCKHOTEL_DATABASE_URL
    stay_date_text = os.environ.get("REVNEST_DEMO2_E2E_STAY_DATE")
    start_date = dt.date.fromisoformat(stay_date_text) if stay_date_text else dt.date.today() + dt.timedelta(days=4)
    end_date = start_date + dt.timedelta(days=2)
    target_property_id = os.environ.get("REVNEST_DEMO2_E2E_TARGET_PROPERTY_ID", "")
    log_path = Path(args.log_path)

    emit(log_path, run_id=args.run_id, stage="agent_start", status="started", message="Demo2 fixture agent started.", tool="demo2-agent-fixture")
    properties = load_properties(claw_database_url, args.account_id)
    if not properties:
        raise RuntimeError("Demo2 fixture found no hotel room type properties")
    property_ids = [prop["id"] for prop in properties]
    if not target_property_id:
        target_property_id = property_ids[0]
    emit(log_path, run_id=args.run_id, stage="context", status="completed", message=f"Loaded {len(properties)} hotel room types.", tool="demo2-agent-fixture")

    mock_rates = load_mock_prices(mockhotel_database_url, property_ids, start_date.isoformat(), end_date.isoformat())
    emit(log_path, run_id=args.run_id, stage="market_data_parallel", status="completed", message="Loaded MockHotel PMS current prices.", tool="demo2-agent-fixture")

    calendars = build_calendars(properties, mock_rates, start_date, target_property_id)
    upsert_hotel_dashboard(claw_database_url, args.account_id, args.run_id, start_date.isoformat(), end_date.isoformat())
    emit(log_path, run_id=args.run_id, stage="weather", status="completed", message="Updated Market Signals Dashboard.", tool="demo2-agent-fixture")

    upsert_property_prices(claw_database_url, calendars)
    upsert_conversations(claw_database_url, args.account_id, args.run_id, calendars, properties)
    emit(log_path, run_id=args.run_id, stage="revpar_publish", status="completed", message="Updated property_price forecasts for every room type.", tool="demo2-agent-fixture")

    room_type_properties = {
        prop["id"]: {
            "property_id": prop["id"],
            "name": prop["data"].get("name") or prop["id"],
            "roomType": prop["data"].get("roomType") or prop["data"].get("name") or prop["id"],
            "data": prop["data"],
        }
        for prop in properties
    }
    review = revnest_mcp_server.review_hotel_price_adjustments_impl(
        account_id=args.account_id,
        run_id=args.run_id,
        price_calendars_by_property_id=calendars,
        room_type_properties=room_type_properties,
        mock_hotel_room_types=list(mock_rates.values()),
        start_date=start_date.isoformat(),
        end_date=end_date.isoformat(),
        dry_run=False,
        database_url=claw_database_url,
    )
    emit_demo_reasoning_trace(
        log_path=log_path,
        database_url=claw_database_url,
        account_id=args.account_id,
        run_id=args.run_id,
        properties=properties,
        mock_rates=mock_rates,
        calendars=calendars,
        target_property_id=target_property_id,
        review=review,
    )
    emit(
        log_path,
        run_id=args.run_id,
        stage="pricing_decision",
        status="completed",
        message=f"Staged {review.get('pending_task_count', 0)} pending task(s).",
        tool="review_hotel_price_adjustments",
        metadata={"pending_task_count": review.get("pending_task_count", 0)},
    )
    mark_properties_finished(claw_database_url, args.account_id, args.run_id, args.conversation_id)
    emit(log_path, run_id=args.run_id, stage="agent_finish", status="completed", message="Demo2 fixture agent completed.", tool="demo2-agent-fixture")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
