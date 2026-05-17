#!/usr/bin/env python3
"""Remove test-fixture hotel dashboard signals from non-e2e accounts."""

from __future__ import annotations

import argparse
import json
import os
import subprocess


DEFAULT_DATABASE_URL = "postgres://postgres:postgres@localhost:55434/dev"


def run_psql(database_url: str, sql: str) -> str:
    result = subprocess.run(
        ["psql", database_url, "-v", "ON_ERROR_STOP=1", "-t", "-A", "-c", sql],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "psql failed")
    return result.stdout.strip()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database-url",
        default=os.environ.get("CLAW_DATABASE_URL") or os.environ.get("DATABASE_URL") or DEFAULT_DATABASE_URL,
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    predicate = """
FROM hotel_home_dashboard h
JOIN account a ON a.id = h.account_id
WHERE h.data->'marketDataRun'->>'source' = 'demo2-e2e-fixture'
  AND a.email NOT LIKE 'demo2-e2e-%'
  AND a.name NOT LIKE 'Demo2 E2E%'
"""
    if args.dry_run:
        sql = f"""
SELECT COALESCE(json_agg(json_build_object(
  'id', h.id,
  'account_id', h.account_id,
  'email', a.email,
  'source', h.data->'marketDataRun'->>'source'
) ORDER BY a.email, h.id), '[]'::json)::text
{predicate};
"""
        print(json.dumps({"dry_run": True, "rows": json.loads(run_psql(args.database_url, sql) or "[]")}, indent=2, sort_keys=True))
        return 0

    sql = f"""
WITH deleted AS (
  DELETE FROM hotel_home_dashboard h
  USING account a
  WHERE a.id = h.account_id
    AND h.data->'marketDataRun'->>'source' = 'demo2-e2e-fixture'
    AND a.email NOT LIKE 'demo2-e2e-%'
    AND a.name NOT LIKE 'Demo2 E2E%'
  RETURNING h.id, h.account_id, a.email
)
SELECT COALESCE(json_agg(row_to_json(deleted) ORDER BY email, id), '[]'::json)::text
FROM deleted;
"""
    print(json.dumps({"deleted": json.loads(run_psql(args.database_url, sql) or "[]")}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
