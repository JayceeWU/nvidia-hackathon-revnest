#!/usr/bin/env python3
"""Create the fixed evidence package layout for a full hotel NemoClaw agent run.

Default mode is design/capture-only: it records DB and WebApp snapshots plus the
exact command to run. Pass --run-agent to execute the long hotel workflow.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path
import subprocess
import urllib.error
import urllib.request


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_DIR = ROOT / "nemoclaw" / "evidence" / "full_hotel_agent_run"
DEFAULT_DATABASE_URL = "postgres://postgres:postgres@localhost:55434/dev"
HOTEL_ACCOUNT_ID = "00000000-0000-0000-0000-000000000103"


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")


def run_command(command: list[str], *, timeout: int | None = None) -> dict:
    result = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
        check=False,
    )
    return {
        "command": command,
        "returncode": result.returncode,
        "stdout": result.stdout,
    }


def psql_json(database_url: str, sql: str) -> dict:
    result = run_command(["psql", database_url, "-v", "ON_ERROR_STOP=1", "-t", "-A", "-c", sql])
    payload = {
        "ok": result["returncode"] == 0,
        "command": result["command"],
        "raw": result["stdout"],
    }
    if payload["ok"]:
        try:
            payload["data"] = json.loads(result["stdout"].strip() or "{}")
        except json.JSONDecodeError as exc:
            payload["ok"] = False
            payload["error"] = f"Could not parse psql JSON: {exc}"
    return payload


def db_snapshot(database_url: str, account_id: str) -> dict:
    sql = f"""
WITH pending AS (
  SELECT COALESCE(json_agg(data ORDER BY id), '[]'::json) AS rows
  FROM pricing_record
  WHERE account_id = '{account_id}'::uuid
    AND record_type = 'pending_task'
),
prices AS (
  SELECT COALESCE(json_agg(row_to_json(price_rows) ORDER BY property_id, price_date), '[]'::json) AS rows
  FROM (
    SELECT property_id, price_date::text, fixed_price_cents, agent_price_cents
    FROM property_price
    WHERE property_id LIKE 'dream-inn-%'
    ORDER BY property_id, price_date
  ) price_rows
),
conversations AS (
  SELECT COALESCE(json_agg(row_to_json(conversation_rows) ORDER BY final_message_at DESC), '[]'::json) AS rows
  FROM (
    SELECT id, property_id, title, final_message_at::text
    FROM revy_conversation
    WHERE account_id = '{account_id}'::uuid
    ORDER BY final_message_at DESC
    LIMIT 8
  ) conversation_rows
)
SELECT json_build_object(
  'account_id', '{account_id}',
  'captured_at', now(),
  'pending_tasks', (SELECT rows FROM pending),
  'property_prices', (SELECT rows FROM prices),
  'revy_conversations', (SELECT rows FROM conversations)
)::text;
"""
    return psql_json(database_url, sql)


def fetch_webapp_snapshot(account_id: str, webapp_url: str) -> dict:
    url = f"{webapp_url.rstrip('/')}/api/dashboard?accountId={account_id}"
    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            text = response.read().decode("utf-8", errors="replace")
            return {
                "ok": True,
                "url": url,
                "status": response.status,
                "data": json.loads(text),
            }
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        return {"ok": False, "url": url, "error": str(exc)}


def run_agent_command(run_id: str, timeout_seconds: int) -> list[str]:
    return [
        "python3",
        "tools/run_pricing_agent.py",
        "--clear-log",
        "--account-id",
        HOTEL_ACCOUNT_ID,
        "--property-type",
        "hotel",
        "--hotel-scope",
        "all-room-types",
        "--runtime-mode",
        "nemoclaw",
        "--session-id",
        run_id,
        "--run-id",
        run_id,
        "--thinking",
        "medium",
        "--verbose",
        "on",
        "--timeout-seconds",
        str(timeout_seconds),
    ]


def render_readme(payload: dict) -> str:
    command = " ".join(payload["agent_command"])
    return f"""# Full Hotel Agent Run Evidence

This folder is the fixed evidence layout for the live hotel NemoClaw run.

## Runtime

- Account: `{payload["account_id"]}`
- Runtime: Hotel -> NemoClaw `my-assistant`
- Policy: `revnest-safe-pms`
- Run id: `{payload["run_id"]}`
- Generated at: `{payload["generated_at"]}`
- Agent executed: `{str(payload["agent_executed"]).lower()}`

## Evidence Files

- `db_before.json`: `property_price`, pending tasks, and recent
  `revy_conversation` rows before the run.
- `agent_stdout.log`: full stdout/stderr from the agent when `--run-agent` is
  used.
- `db_after.json`: same DB snapshot after the run.
- `webapp_before.json` / `webapp_after.json`: WebApp dashboard API snapshots.
- `run_command.sh`: exact command for the full live run.

## Live Run Command

```bash
{command}
```

## Judge Story

1. Before: DB snapshot shows current forecast rows and pending tasks.
2. During: agent stdout shows OpenClaw running inside NemoClaw, using the hotel
   all-room-types branch.
3. After: DB snapshot and WebApp API show Revy forecast rows, saved
   `revy_conversation`, and pending tasks. MockHotel live PMS writes remain gated
   by WebApp Accept.
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", default=os.environ.get("CLAW_DATABASE_URL") or os.environ.get("DATABASE_URL") or DEFAULT_DATABASE_URL)
    parser.add_argument("--webapp-url", default=os.environ.get("REVNEST_WEBAPP_URL", "http://localhost:3000"))
    parser.add_argument("--run-agent", action="store_true", help="Execute the long hotel NemoClaw agent run.")
    parser.add_argument("--no-write", action="store_true", help="Print the evidence manifest without updating evidence files.")
    parser.add_argument("--timeout-seconds", type=int, default=1800)
    args = parser.parse_args()

    generated_at = dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    run_id = f"hotel-full-evidence-{generated_at.replace(':', '').replace('-', '').replace('Z', 'Z')}"
    command = run_agent_command(run_id, args.timeout_seconds)
    db_before = db_snapshot(args.database_url, HOTEL_ACCOUNT_ID)
    webapp_before = fetch_webapp_snapshot(HOTEL_ACCOUNT_ID, args.webapp_url)

    agent_result = {"skipped": True, "reason": "Pass --run-agent to execute the full hotel workflow."}
    if args.run_agent:
        agent_result = run_command(command, timeout=args.timeout_seconds + 120)
    db_after = db_snapshot(args.database_url, HOTEL_ACCOUNT_ID)
    webapp_after = fetch_webapp_snapshot(HOTEL_ACCOUNT_ID, args.webapp_url)
    manifest = {
        "account_id": HOTEL_ACCOUNT_ID,
        "agent_command": command,
        "agent_executed": bool(args.run_agent),
        "agent_result": {key: value for key, value in agent_result.items() if key != "stdout"},
        "generated_at": generated_at,
        "run_id": run_id,
        "runtime": "hotel-nemoclaw",
        "sandbox": "my-assistant",
        "policy": "revnest-safe-pms",
    }
    if not args.no_write:
        EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
        write_json(EVIDENCE_DIR / "db_before.json", db_before)
        write_json(EVIDENCE_DIR / "webapp_before.json", webapp_before)
        (EVIDENCE_DIR / "run_command.sh").write_text("#!/usr/bin/env bash\nset -euo pipefail\ncd /home/asus/revnest/Claw\n" + " ".join(command) + "\n", encoding="utf-8")
        (EVIDENCE_DIR / "run_command.sh").chmod(0o755)
        (EVIDENCE_DIR / "agent_stdout.log").write_text(agent_result.get("stdout", json.dumps(agent_result, indent=2)) + "\n", encoding="utf-8")
        write_json(EVIDENCE_DIR / "db_after.json", db_after)
        write_json(EVIDENCE_DIR / "webapp_after.json", webapp_after)
        write_json(EVIDENCE_DIR / "manifest.json", manifest)
        (EVIDENCE_DIR / "README.md").write_text(render_readme(manifest), encoding="utf-8")
    print(json.dumps({"ok": True, "evidence_dir": str(EVIDENCE_DIR), **manifest}, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
