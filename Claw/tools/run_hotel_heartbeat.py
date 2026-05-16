#!/usr/bin/env python3
"""
Run the RevNest hotel pricing heartbeat.

By default the heartbeat starts one all-room-types hotel pricing workflow for
the account. Use --per-room-type to fall back to the legacy one-workflow-per-room
mode. Use --dry-run to verify command generation without launching OpenClaw/NIM
work.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
import urllib.parse
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / ".env"
DATA_DIR = ROOT / "data"
COMPOSE_FILE = DATA_DIR / "docker-compose.yml"
RUNS_DIR = ROOT / "runs"
LOCK_PATH = RUNS_DIR / "hotel-heartbeat.lock"
DEFAULT_DATABASE_URL = "postgres://postgres:postgres@localhost:55434/dev"
HOTEL_ACCOUNT_ID = "00000000-0000-0000-0000-000000000103"
HOTEL_ACCOUNT_EMAIL = "hotel@revnest.ai"
DEFAULT_INTERVAL_MINUTES = 30


def emit(payload: dict[str, Any], exit_code: int = 0) -> None:
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    raise SystemExit(exit_code)


def load_local_env(path: Path = ENV_PATH) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def database_url_from(args: argparse.Namespace) -> str:
    load_local_env()
    return args.database_url or os.getenv("CLAW_DATABASE_URL") or os.getenv("DATABASE_URL") or DEFAULT_DATABASE_URL


def sql_literal(value: object) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def database_parts(database_url: str) -> dict[str, str]:
    parsed = urllib.parse.urlparse(database_url)
    return {
        "database": (parsed.path or "/dev").lstrip("/") or "dev",
        "user": urllib.parse.unquote(parsed.username or "postgres"),
        "password": urllib.parse.unquote(parsed.password or "postgres"),
    }


def hotel_property_sql(account_id: str) -> str:
    return f"""
WITH hotel_account AS (
  SELECT id
  FROM account
  WHERE id = {sql_literal(account_id)}::uuid
)
SELECT COALESCE(json_agg(row_to_json(property_rows)), '[]'::json)
FROM (
  SELECT to_jsonb(p) AS property
  FROM property p
  JOIN hotel_account a ON a.id = p.account_id
  WHERE p.data->>'propertyType' = 'Hotel Room Type'
  ORDER BY p.id
) property_rows;
""".strip()


def run_local_psql(database_url: str, sql: str, psql_command: str) -> dict[str, Any]:
    if shutil.which(psql_command) is None:
        return {
            "ok": False,
            "method": "local_psql",
            "missing_client": True,
            "error": f"{psql_command} was not found.",
        }
    result = subprocess.run(
        [psql_command, database_url, "-v", "ON_ERROR_STOP=1", "-t", "-A", "-c", sql],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    return {
        "ok": result.returncode == 0,
        "method": "local_psql",
        "returncode": result.returncode,
        "stdout": result.stdout.strip(),
        "stderr": result.stderr.strip(),
    }


def run_docker_compose_psql(database_url: str, sql: str, service: str) -> dict[str, Any]:
    if shutil.which("docker") is None:
        return {
            "ok": False,
            "method": "docker_compose_psql",
            "missing_client": True,
            "error": "docker was not found.",
        }
    if not COMPOSE_FILE.exists():
        return {
            "ok": False,
            "method": "docker_compose_psql",
            "error": f"Compose file not found: {COMPOSE_FILE}",
        }

    parts = database_parts(database_url)
    result = subprocess.run(
        [
            "docker",
            "compose",
            "-f",
            str(COMPOSE_FILE),
            "exec",
            "-T",
            "-e",
            f"PGPASSWORD={parts['password']}",
            service,
            "psql",
            "-v",
            "ON_ERROR_STOP=1",
            "-t",
            "-A",
            "-U",
            parts["user"],
            "-d",
            parts["database"],
            "-c",
            sql,
        ],
        cwd=DATA_DIR,
        text=True,
        capture_output=True,
        check=False,
    )
    return {
        "ok": result.returncode == 0,
        "method": "docker_compose_psql",
        "returncode": result.returncode,
        "stdout": result.stdout.strip(),
        "stderr": result.stderr.strip(),
    }


def run_read(database_url: str, sql: str, args: argparse.Namespace) -> dict[str, Any]:
    attempts: list[dict[str, Any]] = []
    for method in ("local-psql", "docker-compose"):
        if method == "local-psql":
            result = run_local_psql(database_url, sql, args.psql_command)
        else:
            result = run_docker_compose_psql(database_url, sql, args.docker_service)
        attempts.append(result)
        if result.get("ok"):
            result["attempts"] = attempts
            return result
        if method == "local-psql" and result.get("missing_client"):
            continue
    final = attempts[-1] if attempts else {"ok": False, "error": "No read methods attempted"}
    final["attempts"] = attempts
    return final


def load_hotel_properties(args: argparse.Namespace) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    database_url = database_url_from(args)
    result = run_read(database_url, hotel_property_sql(args.account_id), args)
    if not result.get("ok"):
        raise RuntimeError(result.get("stderr") or result.get("error") or "Failed to read hotel properties")
    try:
        rows = json.loads(result.get("stdout") or "[]")
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Could not parse property query JSON: {exc}") from exc
    if not isinstance(rows, list):
        raise RuntimeError("Hotel property query did not return a JSON list")
    normalized = [row.get("property", row) if isinstance(row, dict) else row for row in rows]
    return normalized, result


def cents_to_dollars(cents: object) -> int | float:
    dollars = round(float(cents) / 100, 2)
    return int(dollars) if dollars.is_integer() else dollars

def row_data(row: dict[str, Any]) -> dict[str, Any]:
    data = row.get("data")
    return data if isinstance(data, dict) else {}


def first_value(row: dict[str, Any], *keys: str) -> Any:
    data = row_data(row)
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return value
        value = data.get(key)
        if value not in (None, ""):
            return value
    return None


def parse_number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    cleaned = "".join(char for char in str(value) if char.isdigit() or char in ".-")
    if not cleaned or cleaned in {".", "-", "-."}:
        return None
    return float(cleaned)


def parse_price_range(value: Any) -> tuple[float | None, float | None]:
    if not value:
        return None, None
    parts = str(value).replace("–", "-").replace("—", "-").split("-", 1)
    if len(parts) != 2:
        return None, None
    return parse_number(parts[0]), parse_number(parts[1])


def display_number(value: float) -> int | float:
    return int(value) if value.is_integer() else value


def guardrail_dollars(row: dict[str, Any], cents_key: str, dollar_keys: tuple[str, ...], range_index: int) -> int | float:
    cents = first_value(row, cents_key)
    if cents not in (None, ""):
        return cents_to_dollars(cents)

    value = first_value(row, *dollar_keys)
    parsed = parse_number(value)
    if parsed is not None:
        return display_number(parsed)

    price_range = first_value(row, "priceRange", "price_range")
    range_values = parse_price_range(price_range)
    parsed = range_values[range_index]
    if parsed is not None:
        return display_number(parsed)

    raise RuntimeError(f"Property {row.get('id')} is missing {cents_key}/{dollar_keys[0]}")


def pricing_horizon_days(row: dict[str, Any]) -> int:
    value = first_value(row, "pricing_horizon", "pricingHorizon", "horizon")
    parsed = parse_number(value)
    if parsed is not None:
        return int(parsed)

    duration = first_value(row, "planDuration", "plan_duration")
    parsed = parse_number(duration)
    if parsed is not None:
        return int(parsed)

    raise RuntimeError(f"Property {row.get('id')} is missing pricing_horizon/pricingHorizon")


def timestamp_slug(now: dt.datetime | None = None) -> str:
    value = now or dt.datetime.now(dt.UTC)
    return value.strftime("%Y%m%dT%H%M%SZ")


def property_location(row: dict[str, Any]) -> str:
    data = row_data(row)
    location = data.get("location")
    if location:
        return str(location)
    city = row.get("city") or data.get("city")
    state = row.get("state") or data.get("state")
    return ", ".join(str(part) for part in (city, state) if part)


def build_workflow_command(row: dict[str, Any], args: argparse.Namespace, batch_timestamp: str) -> dict[str, Any]:
    property_id = str(row["id"])
    run_id = f"hotel-heartbeat-{property_id}-{batch_timestamp}"
    conversation_id = f"revy-heartbeat-{property_id}"
    log_path = RUNS_DIR / f"{run_id}.log"
    min_price = guardrail_dollars(
        row,
        "min_price_cents",
        ("minPrice", "min_price", "minPriceUsd", "min_price_usd"),
        0,
    )
    max_price = guardrail_dollars(
        row,
        "max_price_cents",
        ("maxPrice", "max_price", "maxPriceUsd", "max_price_usd"),
        1,
    )
    pricing_horizon = pricing_horizon_days(row)
    location = property_location(row)
    data = row_data(row)
    message_extra = (
        "Automated hotel heartbeat pricing refresh. "
        f"Account: {HOTEL_ACCOUNT_EMAIL}. Property: {property_id}. "
        f"Room type: {data.get('roomType') or data.get('name') or property_id}. "
        f"Room count: {first_value(row, 'room_count', 'roomCount') or 'unknown'}. "
        f"Capacity: {first_value(row, 'capacity') or data.get('guests') or 'unknown'}. "
        f"Location: {location or 'unknown'}."
    )
    command = [
        "python3",
        "tools/run_pricing_agent.py",
        "--clear-log",
        "--session-id",
        run_id,
        "--run-id",
        run_id,
        "--conversation-id",
        conversation_id,
        "--log-path",
        str(log_path),
        "--account-id",
        args.account_id,
        "--property-type",
        "hotel",
        "--runtime-mode",
        "nemoclaw",
        "--property-id",
        property_id,
        "--min-price",
        str(min_price),
        "--max-price",
        str(max_price),
        "--pricing-horizon",
        str(pricing_horizon),
        "--thinking",
        args.thinking,
        "--timeout-seconds",
        str(args.timeout_seconds),
        "--message-extra",
        message_extra,
    ]
    return {
        "property_id": property_id,
        "property_name": (row.get("data") or {}).get("name") if isinstance(row.get("data"), dict) else property_id,
        "location": location,
        "run_id": run_id,
        "conversation_id": conversation_id,
        "log_path": str(log_path),
        "min_price": min_price,
        "max_price": max_price,
        "pricing_horizon": pricing_horizon,
        "command": command,
    }


def build_batch_workflow_command(args: argparse.Namespace, batch_timestamp: str) -> dict[str, Any]:
    run_id = f"hotel-heartbeat-all-room-types-{batch_timestamp}"
    log_path = RUNS_DIR / f"{run_id}.log"
    message_extra = (
        "Automated hotel heartbeat all-room-types pricing refresh. "
        f"Account: {HOTEL_ACCOUNT_EMAIL}. "
        "Load every Hotel Room Type property for this account, fetch shared market data once, "
        "then publish one guarded price calendar per room type."
    )
    command = [
        "python3",
        "tools/run_pricing_agent.py",
        "--clear-log",
        "--session-id",
        run_id,
        "--run-id",
        run_id,
        "--log-path",
        str(log_path),
        "--account-id",
        args.account_id,
        "--property-type",
        "hotel",
        "--runtime-mode",
        "nemoclaw",
        "--hotel-scope",
        "all-room-types",
        "--thinking",
        args.thinking,
        "--timeout-seconds",
        str(args.timeout_seconds),
        "--message-extra",
        message_extra,
    ]
    return {
        "scope": "all-room-types",
        "run_id": run_id,
        "log_path": str(log_path),
        "command": command,
    }


def process_is_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class HeartbeatLock:
    def __init__(self, lock_path: Path, dry_run: bool = False) -> None:
        self.lock_path = lock_path
        self.dry_run = dry_run
        self.acquired = False

    def __enter__(self) -> "HeartbeatLock":
        if self.dry_run:
            return self
        RUNS_DIR.mkdir(parents=True, exist_ok=True)
        if self.lock_path.exists():
            try:
                data = json.loads(self.lock_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                data = {}
            pid = data.get("pid")
            if isinstance(pid, int) and process_is_running(pid):
                raise RuntimeError(f"Hotel heartbeat already running with pid {pid}")
            self.lock_path.unlink(missing_ok=True)
        self.lock_path.write_text(
            json.dumps(
                {
                    "pid": os.getpid(),
                    "started_at": dt.datetime.now(dt.UTC).isoformat().replace("+00:00", "Z"),
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        self.acquired = True
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        if self.acquired:
            self.lock_path.unlink(missing_ok=True)


def run_command(command: list[str], timeout_seconds: int) -> dict[str, Any]:
    started = dt.datetime.now(dt.UTC)
    result = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
        timeout=timeout_seconds + 120,
    )
    finished = dt.datetime.now(dt.UTC)
    return {
        "returncode": result.returncode,
        "started_at": started.isoformat().replace("+00:00", "Z"),
        "finished_at": finished.isoformat().replace("+00:00", "Z"),
        "stdout_tail": result.stdout[-4000:],
        "stderr_tail": result.stderr[-4000:],
    }


def run_batch(args: argparse.Namespace) -> dict[str, Any]:
    batch_timestamp = timestamp_slug()

    if args.per_room_type:
        rows, read_result = load_hotel_properties(args)
        if args.limit is not None:
            rows = rows[: args.limit]
        commands = [build_workflow_command(row, args, batch_timestamp) for row in rows]
        scope = "per-room-type"
        property_count = len(rows)
        read_method = read_result.get("method")
    else:
        if args.limit is not None:
            raise RuntimeError("--limit is only supported with --per-room-type")
        rows, read_result = load_hotel_properties(args)
        commands = [build_batch_workflow_command(args, batch_timestamp)]
        scope = "all-room-types"
        property_count = len(rows)
        read_method = read_result.get("method")

    payload: dict[str, Any] = {
        "source": "hotel_heartbeat",
        "account_id": args.account_id,
        "account_email": HOTEL_ACCOUNT_EMAIL,
        "property_type": "hotel",
        "hotel_scope": scope,
        "dry_run": args.dry_run,
        "batch_timestamp": batch_timestamp,
        "property_count": property_count,
        "read_method": read_method,
        "commands": commands,
    }
    if args.dry_run:
        return payload

    with HeartbeatLock(LOCK_PATH, dry_run=False):
        results = []
        for item in commands:
            item_result = dict(item)
            item_result["result"] = run_command(item["command"], args.timeout_seconds)
            results.append(item_result)
        payload["results"] = results
        payload["ok"] = all(item["result"]["returncode"] == 0 for item in results)
        return payload


def run_once(args: argparse.Namespace) -> int:
    try:
        payload = run_batch(args)
    except RuntimeError as exc:
        payload = {
            "source": "hotel_heartbeat",
            "status": "skipped" if "already running" in str(exc) else "failed",
            "error": str(exc),
        }
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0 if payload["status"] == "skipped" else 1
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    if args.dry_run:
        return 0
    return 0 if payload.get("ok") else 1


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("value must be at least 1")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the RevNest hotel pricing heartbeat")
    parser.add_argument("--account-id", default=HOTEL_ACCOUNT_ID, help="Hotel account id")
    parser.add_argument("--database-url", help="PostgreSQL connection URL")
    parser.add_argument("--psql-command", default="psql")
    parser.add_argument("--docker-service", default="postgres", help="Docker Compose database service name")
    parser.add_argument("--interval-minutes", type=positive_int, default=DEFAULT_INTERVAL_MINUTES)
    parser.add_argument("--loop", action="store_true", help="Run continuously every --interval-minutes")
    parser.add_argument("--dry-run", action="store_true", help="Print discovered properties and commands without running workflows")
    parser.add_argument("--per-room-type", action="store_true", help="Fall back to the legacy one-workflow-per-room-type heartbeat")
    parser.add_argument("--limit", type=positive_int, help="Limit properties for local smoke testing in --per-room-type mode")
    parser.add_argument("--thinking", default="medium", help="OpenClaw thinking level")
    parser.add_argument("--timeout-seconds", type=positive_int, default=1800, help="Workflow timeout")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if not args.loop:
        return run_once(args)

    while True:
        exit_code = run_once(args)
        if exit_code != 0 and not args.dry_run:
            print(json.dumps({"source": "hotel_heartbeat", "status": "sleeping_after_error", "exit_code": exit_code}))
        time.sleep(args.interval_minutes * 60)


if __name__ == "__main__":
    raise SystemExit(main())
