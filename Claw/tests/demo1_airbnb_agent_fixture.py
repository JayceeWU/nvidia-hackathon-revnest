#!/usr/bin/env python3
"""Deterministic Airbnb OpenClaw fixture used by the demo1 e2e test."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path
import subprocess
from typing import Any


DEFAULT_DATABASE_URL = "postgres://postgres:postgres@localhost:55434/dev"


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
    return json.loads(run_psql(database_url, sql) or "null")


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


def load_property(database_url: str, account_id: str, property_id: str) -> dict[str, Any]:
    sql = f"""
SELECT row_to_json(row)::text
FROM (
  SELECT id, account_id::text, min_price_cents, max_price_cents, pricing_horizon, my_place, room_count, capacity, data
  FROM property
  WHERE id = {sql_literal(property_id)}
    AND account_id = {sql_literal(account_id)}::uuid
  LIMIT 1
) row;
"""
    row = psql_json(database_url, sql)
    if not row:
        raise RuntimeError(f"Airbnb property {property_id} was not found for account {account_id}")
    return row


def upsert_property_profile(database_url: str, property_id: str, run_id: str, my_place: str | None) -> dict[str, Any]:
    patch = {
        "name": "Demo1 E2E Coastal Studio",
        "displayNameSource": "demo1_e2e_openclaw_fixture",
        "location": "Santa Cruz, CA",
        "streetAddress": "Demo1 E2E verified by OpenClaw",
        "guests": "1-2 guests",
        "bathroom": "Private",
        "beds": "1 Queen",
        "bed": "1 Queen",
        "bath": "Private",
        "bedSize": "Queen",
        "amenities": ["Ocean view", "WiFi", "Kitchen"],
        "occupancy": "78%",
        "revparLift": "Demo1 fixture completed",
        "lastOpenClawFixtureRunId": run_id,
        **({"myPlace": my_place, "airbnbUrl": my_place} if my_place else {}),
    }
    sql = f"""
UPDATE property
SET room_count = COALESCE(room_count, 1),
    capacity = COALESCE(capacity, 2),
    city = COALESCE(city, 'Santa Cruz'),
    state = COALESCE(state, 'CA'),
    bed = COALESCE(bed, '1 Queen'),
    bath = COALESCE(bath, 'Private'),
    data = data || {sql_literal(json.dumps(patch, ensure_ascii=False, sort_keys=True))}::jsonb,
    updated_at = now()
WHERE id = {sql_literal(property_id)}
RETURNING data::text;
"""
    run_psql(database_url, sql)
    return patch


def upsert_prices(database_url: str, property_id: str, min_price_cents: int, pricing_horizon: int) -> list[dict[str, Any]]:
    start = dt.date.today() + dt.timedelta(days=3)
    horizon = max(1, min(int(pricing_horizon or 2), 7))
    rows = []
    values = []
    base = max(30000, int(min_price_cents or 30000))
    for offset in range(horizon):
        day = start + dt.timedelta(days=offset)
        fixed = base
        agent = base + 2400 + offset * 900
        rows.append({"date": day.isoformat(), "current_price": fixed / 100, "agent_price": agent / 100})
        values.append(f"({sql_literal(property_id)}, {sql_literal(day.isoformat())}::date, {fixed}, {agent})")
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
    return rows


def upsert_conversation(
    database_url: str,
    account_id: str,
    property_id: str,
    run_id: str,
    conversation_id: str,
    price_rows: list[dict[str, Any]],
) -> None:
    final_message = "Demo1 OpenClaw fixture completed Airbnb onboarding and saved the first guarded price curve."
    data = {
        "conversationId": conversation_id,
        "source": "demo1-e2e-openclaw-fixture",
        "runId": run_id,
        "propertyId": property_id,
        "summary": final_message,
        "messages": [
            {
                "role": "agent",
                "text": final_message,
                "at": dt.datetime.now(dt.UTC).isoformat().replace("+00:00", "Z"),
            }
        ],
        "priceCalendar": price_rows,
    }
    sql = f"""
INSERT INTO revy_conversation (id, account_id, property_id, title, final_message_at, data)
VALUES (
  {sql_literal(conversation_id)},
  {sql_literal(account_id)}::uuid,
  {sql_literal(property_id)},
  'Demo1 Airbnb OpenClaw onboarding',
  now(),
  {sql_literal(json.dumps(data, ensure_ascii=False, sort_keys=True))}::jsonb
)
ON CONFLICT (id)
DO UPDATE SET
  property_id = EXCLUDED.property_id,
  title = EXCLUDED.title,
  final_message_at = EXCLUDED.final_message_at,
  data = EXCLUDED.data,
  updated_at = now();
"""
    run_psql(database_url, sql)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--account-id", required=True)
    parser.add_argument("--property-id", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--conversation-id")
    parser.add_argument("--log-path", required=True)
    parser.add_argument("--my-place")
    args, _unknown = parser.parse_known_args()

    database_url = os.environ.get("CLAW_DATABASE_URL") or os.environ.get("DATABASE_URL") or DEFAULT_DATABASE_URL
    conversation_id = args.conversation_id or f"demo1-e2e-{args.run_id}"
    log_path = Path(args.log_path)

    emit(log_path, run_id=args.run_id, stage="agent_start", status="started", message="Demo1 OpenClaw fixture started.", tool="openclaw-agent-fixture")
    prop = load_property(database_url, args.account_id, args.property_id)
    emit(log_path, run_id=args.run_id, stage="context", status="completed", message="Loaded Airbnb draft property and default URL input.", tool="agent-browser")
    upsert_property_profile(database_url, args.property_id, args.run_id, args.my_place or prop.get("my_place"))
    emit(log_path, run_id=args.run_id, stage="market_data_parallel", status="completed", message="OpenClaw fixture collected Airbnb market context.", tool="openclaw-agent-fixture")
    price_rows = upsert_prices(database_url, args.property_id, int(prop["min_price_cents"]), int(prop["pricing_horizon"]))
    emit(log_path, run_id=args.run_id, stage="revpar_publish", status="completed", message="Saved Airbnb property_price rows.", tool="revpar_estimate.write-prices")
    upsert_conversation(database_url, args.account_id, args.property_id, args.run_id, conversation_id, price_rows)
    emit(log_path, run_id=args.run_id, stage="agent_finish", status="completed", message="Demo1 OpenClaw fixture completed.", tool="openclaw-agent-fixture")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
