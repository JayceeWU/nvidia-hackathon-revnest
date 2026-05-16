#!/usr/bin/env python3
"""Persist compact RevNest pricing reasoning-step summaries to PostgreSQL."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
TOOLS_DIR = ROOT / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import run_pricing_agent  # noqa: E402


def utc_timestamp() -> str:
    return dt.datetime.now(dt.UTC).isoformat().replace("+00:00", "Z")


def parse_json_value(raw: str | None, default: Any) -> Any:
    if not raw:
        return default
    value = json.loads(raw)
    return value


def compact_text(value: str, limit: int = 900) -> str:
    text = " ".join(str(value).split())
    return text[:limit] + ("..." if len(text) > limit else "")


def slug(value: object, fallback: str = "none") -> str:
    text = str(value or fallback).strip().lower()
    text = re.sub(r"[^a-z0-9_.-]+", "-", text).strip("-")
    return text[:80] or fallback


def record_id(run_id: str, property_id: str | None, substage: str, group_key: str | None) -> str:
    raw = "|".join([run_id, property_id or "global", substage, group_key or "all"])
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]
    return f"reasoning-{slug(run_id)}-{slug(property_id, 'global')}-{slug(substage)}-{slug(group_key, 'all')}-{digest}"


def ensure_reasoning_record_type_sql() -> str:
    return """
ALTER TABLE pricing_record
DROP CONSTRAINT IF EXISTS pricing_record_record_type_check;

ALTER TABLE pricing_record
ADD CONSTRAINT pricing_record_record_type_check
CHECK (record_type IN ('pending_task', 'price_log', 'reasoning_step'));
""".strip()


def sanitize_payload(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): sanitize_payload(child) for key, child in value.items()}
    if isinstance(value, list):
        return [sanitize_payload(item) for item in value]
    return value


def build_reasoning_payload(
    *,
    run_id: str,
    property_id: str | None,
    stage: str,
    substage: str,
    summary: str,
    facts: Any = None,
    metrics: Any = None,
    tool: str | None = None,
    sources: Any = None,
    confidence: str | None = None,
    group_key: str | None = None,
    timestamp: str | None = None,
) -> dict[str, Any]:
    return {
        "source": "reasoning_step_logger",
        "runId": run_id,
        "propertyId": property_id,
        "stage": stage,
        "substage": substage,
        "groupKey": group_key,
        "summary": compact_text(summary),
        "facts": sanitize_payload(facts or []),
        "metrics": sanitize_payload(metrics or {}),
        "tool": tool,
        "sources": sanitize_payload(sources or []),
        "confidence": confidence,
        "timestamp": timestamp or utc_timestamp(),
    }


def build_upsert_sql(account_id: str, record_id_value: str, payload: dict[str, Any]) -> str:
    return "\n\n".join(
        [
            ensure_reasoning_record_type_sql(),
            """
INSERT INTO pricing_record (id, account_id, record_type, data)
VALUES ({record_id}, {account_id}::uuid, 'reasoning_step', {payload}::jsonb)
ON CONFLICT (id)
DO UPDATE SET
  account_id = EXCLUDED.account_id,
  record_type = EXCLUDED.record_type,
  data = EXCLUDED.data,
  updated_at = now()
RETURNING id;
""".strip().format(
                record_id=run_pricing_agent.sql_literal(record_id_value),
                account_id=run_pricing_agent.sql_literal(account_id),
                payload=run_pricing_agent.sql_literal(json.dumps(payload, ensure_ascii=False, sort_keys=True)),
            ),
        ]
    )


def upsert_reasoning_step(
    *,
    account_id: str,
    run_id: str,
    property_id: str | None,
    stage: str,
    substage: str,
    summary: str,
    facts: Any = None,
    metrics: Any = None,
    tool: str | None = None,
    sources: Any = None,
    confidence: str | None = None,
    group_key: str | None = None,
    database_url: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    if not account_id:
        raise ValueError("account_id is required")
    if not run_id:
        raise ValueError("run_id is required")
    if not substage:
        raise ValueError("substage is required")
    if not summary:
        raise ValueError("summary is required")
    stage = stage or "pricing_decision"
    rec_id = record_id(run_id, property_id, substage, group_key)
    payload = build_reasoning_payload(
        run_id=run_id,
        property_id=property_id,
        stage=stage,
        substage=substage,
        summary=summary,
        facts=facts,
        metrics=metrics,
        tool=tool,
        sources=sources,
        confidence=confidence,
        group_key=group_key,
    )
    sql = build_upsert_sql(account_id, rec_id, payload)
    result = {
        "status": "completed",
        "dry_run": dry_run,
        "table": "pricing_record",
        "record_type": "reasoning_step",
        "record_id": rec_id,
        "data": payload,
    }
    if dry_run:
        result["sql"] = sql
        return result
    env = run_pricing_agent.load_dotenv(os.environ)
    if database_url:
        env["CLAW_DATABASE_URL"] = database_url
    output = run_pricing_agent.run_psql_sql(sql, env)
    result["psql_output_tail"] = output.splitlines()[-3:] if output else []
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Upsert one compact pricing reasoning step into pricing_record.")
    parser.add_argument("--account-id", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--property-id")
    parser.add_argument("--stage", default="pricing_decision")
    parser.add_argument("--substage", required=True)
    parser.add_argument("--summary", required=True)
    parser.add_argument("--facts-json")
    parser.add_argument("--metrics-json")
    parser.add_argument("--sources-json")
    parser.add_argument("--tool")
    parser.add_argument("--confidence")
    parser.add_argument("--group-key")
    parser.add_argument("--database-url")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    try:
        result = upsert_reasoning_step(
            account_id=args.account_id,
            run_id=args.run_id,
            property_id=args.property_id,
            stage=args.stage,
            substage=args.substage,
            summary=args.summary,
            facts=parse_json_value(args.facts_json, []),
            metrics=parse_json_value(args.metrics_json, {}),
            sources=parse_json_value(args.sources_json, []),
            tool=args.tool,
            confidence=args.confidence,
            group_key=args.group_key,
            database_url=args.database_url,
            dry_run=args.dry_run,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    except Exception as exc:
        print(json.dumps({"source": "reasoning_step_logger", "error": str(exc)}, ensure_ascii=False, indent=2))
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
