#!/usr/bin/env python3
"""Verify hotel seed pending tasks match seeded Revy suggested prices."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATABASE_URL = "postgres://postgres:postgres@localhost:55434/dev"
HOTEL_ACCOUNT_ID = "00000000-0000-0000-0000-000000000103"
DATA_SQL_PATH = ROOT / "data" / "sql" / "data.sql"


def run_psql(database_url: str, sql: str):
    result = subprocess.run(
        ["psql", database_url, "-v", "ON_ERROR_STOP=1", "-t", "-A", "-c", sql],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "psql failed")
    text = result.stdout.strip()
    return json.loads(text or "[]")


def seed_pricing_record_count(record_type: str) -> int:
    text = DATA_SQL_PATH.read_text(encoding="utf-8")
    pattern = rf"^\s*'{re.escape(record_type)}',\s*$"
    return len(re.findall(pattern, text, flags=re.MULTILINE))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", default=os.environ.get("CLAW_DATABASE_URL") or os.environ.get("DATABASE_URL") or DEFAULT_DATABASE_URL)
    parser.add_argument("--account-id", default=HOTEL_ACCOUNT_ID)
    args = parser.parse_args()

    sql = f"""
WITH pending AS (
  SELECT
    id,
    data->>'propertyId' AS property_id,
    (data->>'priceDate')::date AS price_date,
    round((regexp_replace(data->>'currentPrice', '[^0-9.-]', '', 'g'))::numeric * 100)::integer AS current_price_cents,
    round((regexp_replace(data->>'agentSuggestedPrice', '[^0-9.-]', '', 'g'))::numeric * 100)::integer AS agent_price_cents,
    data->>'taskType' AS task_type,
    data->>'approvalGateLabel' AS approval_gate_label,
    data->>'reason' AS reason
  FROM pricing_record
  WHERE account_id = '{args.account_id}'::uuid
    AND record_type = 'pending_task'
    AND data->>'source' = 'mockhotel_price_review'
)
SELECT COALESCE(json_agg(row_to_json(checks)), '[]'::json)
FROM (
  SELECT
    p.id,
    p.property_id,
    p.price_date::text AS price_date,
    p.current_price_cents,
    pp.fixed_price_cents,
    p.agent_price_cents,
    pp.agent_price_cents AS seeded_agent_price_cents,
    p.task_type,
    p.approval_gate_label,
    p.reason,
    CASE
      WHEN pp.property_id IS NULL THEN 'missing_property_price'
      WHEN p.current_price_cents <> pp.fixed_price_cents THEN 'current_price_mismatch'
      WHEN p.agent_price_cents <> pp.agent_price_cents THEN 'agent_price_mismatch'
      WHEN p.task_type IS NULL OR p.approval_gate_label IS NULL THEN 'missing_classification'
      ELSE 'ok'
    END AS status
  FROM pending p
  LEFT JOIN property_price pp
    ON pp.property_id = p.property_id
   AND pp.price_date = p.price_date
  ORDER BY p.id
) checks;
"""
    rows = run_psql(args.database_url, sql)
    count_sql = f"""
SELECT json_build_object(
  'pending_task_count', COUNT(*) FILTER (
    WHERE record_type = 'pending_task'
      AND data->>'source' = 'mockhotel_price_review'
  ),
  'price_log_count', COUNT(*) FILTER (WHERE record_type = 'price_log')
)::text
FROM pricing_record
WHERE account_id = '{args.account_id}'::uuid;
"""
    counts = run_psql(args.database_url, count_sql)
    expected_pending_task_count = seed_pricing_record_count("pending_task")
    expected_price_log_count = seed_pricing_record_count("price_log")
    failures = [row for row in rows if row.get("status") != "ok"]
    output = {
        "source": "hotel_seed_consistency",
        "account_id": args.account_id,
        "pending_task_count": len(rows),
        "expected_pending_task_count": expected_pending_task_count,
        "price_log_count": int(counts.get("price_log_count") or 0),
        "expected_price_log_count": expected_price_log_count,
        "failed_count": len(failures),
        "rows": rows,
    }
    print(json.dumps(output, indent=2, ensure_ascii=False, sort_keys=True))
    if len(rows) != expected_pending_task_count:
        raise SystemExit(f"Expected {expected_pending_task_count} seeded MockHotel pending tasks")
    if output["price_log_count"] != expected_price_log_count:
        raise SystemExit(f"Expected {expected_price_log_count} seeded MockHotel price logs")
    if failures:
        raise SystemExit("Hotel seed pending tasks do not match property_price")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
