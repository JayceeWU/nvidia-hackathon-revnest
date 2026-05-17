#!/usr/bin/env python3
"""End-to-end Demo2 hotel flow test.

Default mode starts a temporary WebApp dev server with
REVNEST_AGENT_RUN_FIXTURE=demo2 so the full WebApp/API/DB flow is deterministic
and quick. Use --live-agent with --no-start-webapp to exercise a real
NemoClaw/OpenClaw run against an already running WebApp.
"""

from __future__ import annotations

import argparse
import contextlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import http.cookiejar
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import datetime as dt
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
WEBAPP_DIR = ROOT / "WebApp"
DEFAULT_CLAW_DATABASE_URL = "postgres://postgres:postgres@localhost:55434/test"
DEFAULT_MOCKHOTEL_DATABASE_URL = "postgres://postgres:postgres@localhost:55432/dev"
DEFAULT_ACCOUNT_ID = "00000000-0000-0000-0000-0000000002e2"
TARGET_PROPERTY_ID = "demo2-e2e-standard-king"
SECOND_PROPERTY_ID = "demo2-e2e-ocean-queen"
PROPERTY_IDS = [TARGET_PROPERTY_ID, SECOND_PROPERTY_ID]


class E2EError(RuntimeError):
    pass


class DiscordWebhookCapture:
    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []
        self._lock = threading.Lock()

        messages = self.messages
        lock = self._lock

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802 - stdlib handler API.
                length = int(self.headers.get("Content-Length") or "0")
                raw = self.rfile.read(length).decode("utf-8", errors="replace")
                try:
                    payload = json.loads(raw or "{}")
                except json.JSONDecodeError:
                    payload = {"raw": raw}
                with lock:
                    messages.append({"path": self.path, "payload": payload, "raw": raw})
                self.send_response(204)
                self.end_headers()

            def log_message(self, _format: str, *args: object) -> None:
                return

        self._server = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self._server.server_port}/discord-webhook"
        self._thread = threading.Thread(target=self._server.serve_forever, name="discord-webhook-capture", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)

    def snapshot(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self.messages)


def sql_literal(value: object) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def run_psql(database_url: str, sql: str, *, label: str) -> str:
    result = subprocess.run(
        ["psql", database_url, "-v", "ON_ERROR_STOP=1"],
        input=sql,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if result.returncode != 0:
        raise E2EError(f"{label} failed:\n{result.stdout.strip()}")
    return result.stdout.strip()


def psql_json(database_url: str, sql: str, *, label: str):
    result = subprocess.run(
        ["psql", database_url, "-v", "ON_ERROR_STOP=1", "-t", "-A", "-c", sql],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if result.returncode != 0:
        raise E2EError(f"{label} failed:\n{result.stdout.strip()}")
    text = result.stdout.strip()
    return json.loads(text or "null")


def iso_date(value: dt.date) -> str:
    return value.isoformat()


def setup_claw_database(database_url: str, account_id: str, stay_date: dt.date) -> None:
    property_values = []
    rooms = [
        {
            "id": TARGET_PROPERTY_ID,
            "name": "Demo2 E2E Standard King",
            "roomType": "Demo2 E2E Standard King",
            "roomCount": 8,
            "capacity": 2,
            "bed": "1 King",
            "bath": "Private",
            "min": 150,
            "max": 300,
            "fixed": 80,
        },
        {
            "id": SECOND_PROPERTY_ID,
            "name": "Demo2 E2E Ocean Queen",
            "roomType": "Demo2 E2E Ocean Queen",
            "roomCount": 6,
            "capacity": 4,
            "bed": "2 Queen",
            "bath": "Private",
            "min": 180,
            "max": 340,
            "fixed": 220,
        },
    ]
    for room in rooms:
        data = {
            "id": room["id"],
            "name": room["name"],
            "propertyType": "Hotel Room Type",
            "roomType": room["roomType"],
            "roomCount": room["roomCount"],
            "location": "Santa Cruz, CA",
            "streetAddress": "175 W Cliff Dr",
            "guests": f"1-{room['capacity']} guests",
            "bathroom": room["bath"],
            "beds": room["bed"],
            "bedSize": room["bed"],
            "fixedPrice": room["fixed"],
            "agentAdr": room["fixed"],
            "adr": f"${room['fixed']}",
            "revpar": "$0",
            "occupancy": "0%",
            "planDuration": "3 days",
            "pricingHorizon": 3,
            "minPrice": room["min"],
            "maxPrice": room["max"],
            "priceRange": f"${room['min']}-${room['max']}",
            "pricingConnection": "demo2-e2e-mockhotel",
            "source": "demo2_e2e",
            "capacity": room["capacity"],
            "city": "Santa Cruz",
            "state": "CA",
            "county": "Santa Cruz County",
            "zipCode": "95060",
            "bed": room["bed"],
            "bath": room["bath"],
            "otherInfo": "Temporary Demo2 e2e room type.",
        }
        property_values.append(
            "("
            + ", ".join(
                [
                    sql_literal(room["id"]),
                    f"{sql_literal(account_id)}::uuid",
                    str(room["min"] * 100),
                    str(room["max"] * 100),
                    "3",
                    str(room["roomCount"]),
                    str(room["capacity"]),
                    "'95060'",
                    "'Santa Cruz County'",
                    "'CA'",
                    "'Santa Cruz'",
                    sql_literal(room["bed"]),
                    sql_literal(room["bath"]),
                    "'Temporary Demo2 e2e room type.'",
                    f"{sql_literal(json.dumps(data, sort_keys=True))}::jsonb",
                ]
            )
            + ")"
        )
    baseline_dashboard = {
        "demandSignals": {
            "weather": {"summary": "Baseline", "location": "Santa Cruz, CA", "trend": "neutral"},
            "events": {"headline": "Baseline", "location": "Santa Cruz", "trend": "neutral"},
            "competitor": {"median_rate": 210, "trend": "neutral"},
            "occupancy": {"portfolio_rate": 0.5, "trend": "neutral"},
        },
        "marketDataRun": {
            "runId": "demo2-e2e-baseline",
            "startDate": iso_date(stay_date),
            "endDate": iso_date(stay_date + dt.timedelta(days=2)),
            "updatedAt": "2026-01-01T00:00:00.000Z",
        },
    }
    ids_array = "ARRAY[" + ", ".join(sql_literal(item) for item in PROPERTY_IDS) + "]::text[]"
    sql = f"""
BEGIN;
DELETE FROM pricing_record WHERE account_id = {sql_literal(account_id)}::uuid;
DELETE FROM revy_conversation WHERE account_id = {sql_literal(account_id)}::uuid;
DELETE FROM hotel_home_dashboard WHERE account_id = {sql_literal(account_id)}::uuid;
DELETE FROM property_price WHERE property_id = ANY({ids_array});
DELETE FROM property WHERE account_id = {sql_literal(account_id)}::uuid OR id = ANY({ids_array});
DELETE FROM account WHERE id = {sql_literal(account_id)}::uuid;

INSERT INTO account (id, email, password_hash, name, role, account_type)
VALUES ({sql_literal(account_id)}::uuid, 'demo2-e2e-hotel@revnest.ai', crypt('demo2', gen_salt('bf')), 'Demo2 E2E Hotel Operator', 'host', 'hotel');

INSERT INTO property (
  id, account_id, min_price_cents, max_price_cents, pricing_horizon, room_count,
  capacity, zip_code, county, state, city, bed, bath, other_info, data
)
VALUES
  {",\n  ".join(property_values)};

INSERT INTO hotel_home_dashboard (id, account_id, data)
VALUES ('home', {sql_literal(account_id)}::uuid, {sql_literal(json.dumps(baseline_dashboard, sort_keys=True))}::jsonb);
COMMIT;
"""
    run_psql(database_url, sql, label="setup Claw database")


def setup_mockhotel_database(database_url: str, stay_date: dt.date) -> None:
    dates = [stay_date + dt.timedelta(days=offset) for offset in range(3)]
    room_values = [
        f"({sql_literal(TARGET_PROPERTY_ID)}, 'Demo2 E2E Standard King', 'Demo2 E2E Standard King', 8, 2, '1 King', 'Private', 15000, 30000, 19000, 3, 'demo2_e2e', '{{}}'::jsonb)",
        f"({sql_literal(SECOND_PROPERTY_ID)}, 'Demo2 E2E Ocean Queen', 'Demo2 E2E Ocean Queen', 6, 4, '2 Queen', 'Private', 18000, 34000, 22000, 3, 'demo2_e2e', '{{}}'::jsonb)",
    ]
    price_values = []
    for day in dates:
        target_price = 8000 if day == stay_date else 19000
        price_values.append(f"({sql_literal(TARGET_PROPERTY_ID)}, {sql_literal(iso_date(day))}::date, {target_price}, (SELECT id FROM account ORDER BY created_at, id LIMIT 1))")
        price_values.append(f"({sql_literal(SECOND_PROPERTY_ID)}, {sql_literal(iso_date(day))}::date, 22000, (SELECT id FROM account ORDER BY created_at, id LIMIT 1))")
    ids_array = "ARRAY[" + ", ".join(sql_literal(item) for item in PROPERTY_IDS) + "]::text[]"
    sql = f"""
BEGIN;
INSERT INTO account (id, username, password_hash, role)
VALUES ('00000000-0000-0000-0000-0000000002e2', 'demo2-e2e-manager', crypt('demo2', gen_salt('bf')), 'manager')
ON CONFLICT (username) DO UPDATE SET role = EXCLUDED.role;

DELETE FROM room_type_price WHERE room_type_id = ANY({ids_array});
DELETE FROM room_type WHERE id = ANY({ids_array});

INSERT INTO room_type (
  id, name, room_type, room_count, capacity, bed, bath, min_price_cents,
  max_price_cents, base_price_cents, pricing_horizon, source, data
)
VALUES
  {",\n  ".join(room_values)};

INSERT INTO room_type_price (room_type_id, stay_date, price_cents, updated_by)
VALUES
  {",\n  ".join(price_values)};
COMMIT;
"""
    run_psql(database_url, sql, label="setup MockHotel database")


def assert_mockhotel_outside_min(database_url: str, stay_date: dt.date) -> dict[str, Any]:
    sql = f"""
SELECT json_build_object(
  'room_type_id', room_type.id,
  'stay_date', room_type_price.stay_date::text,
  'price_cents', room_type_price.price_cents,
  'min_price_cents', room_type.min_price_cents,
  'outside_min_max', room_type_price.price_cents < room_type.min_price_cents OR room_type_price.price_cents > room_type.max_price_cents
)::text
FROM room_type
JOIN room_type_price ON room_type_price.room_type_id = room_type.id
WHERE room_type.id = {sql_literal(TARGET_PROPERTY_ID)}
  AND room_type_price.stay_date = {sql_literal(iso_date(stay_date))}::date;
"""
    row = psql_json(database_url, sql, label="verify MockHotel outside min/max setup")
    if not row or not row.get("outside_min_max"):
        raise E2EError(f"MockHotel setup did not put {TARGET_PROPERTY_ID} outside min/max: {row}")
    return row


class HttpClient:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self.cookie_jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cookie_jar))

    def request(self, method: str, path: str, payload: dict[str, Any] | None = None, timeout: int = 30) -> dict[str, Any]:
        data = None
        headers = {"Accept": "application/json"}
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(f"{self.base_url}{path}", data=data, headers=headers, method=method)
        try:
            with self.opener.open(request, timeout=timeout) as response:
                body = response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise E2EError(f"{method} {path} returned HTTP {exc.code}: {body}") from exc
        return json.loads(body or "{}")

    def get(self, path: str, timeout: int = 30) -> dict[str, Any]:
        return self.request("GET", path, timeout=timeout)

    def post(self, path: str, payload: dict[str, Any], timeout: int = 30) -> dict[str, Any]:
        return self.request("POST", path, payload=payload, timeout=timeout)


def wait_for_http(client: HttpClient, timeout_seconds: int, server_log_path: Path | None = None) -> None:
    deadline = time.time() + timeout_seconds
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            client.get("/api/access-path", timeout=5)
            return
        except Exception as exc:  # noqa: BLE001 - surfaced with context below.
            last_error = exc
            time.sleep(1)
    tail = ""
    if server_log_path and server_log_path.exists():
        tail = "\nWebApp log tail:\n" + "\n".join(server_log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-40:])
    raise E2EError(f"WebApp did not become ready: {last_error}{tail}")


def port_available(port: int) -> bool:
    with contextlib.closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex(("127.0.0.1", port)) != 0


def build_webapp(env: dict[str, str]) -> Path:
    next_bin = WEBAPP_DIR / "node_modules" / ".bin" / "next"
    if not next_bin.exists():
        raise E2EError("WebApp dependencies are missing. Run `npm --prefix WebApp install` first.")
    log_file = tempfile.NamedTemporaryFile(prefix="revnest-demo2-webapp-build-", suffix=".log", delete=False)
    log_path = Path(log_file.name)
    result = subprocess.run(
        [str(next_bin), "build"],
        cwd=WEBAPP_DIR,
        env=env,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )
    log_file.close()
    if result.returncode != 0:
        tail = "\n".join(log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-80:])
        raise E2EError(f"WebApp build failed before e2e server start:\n{tail}")
    return log_path


def start_webapp(port: int, env: dict[str, str]) -> tuple[subprocess.Popen, Path]:
    if not port_available(port):
        raise E2EError(f"Port {port} is already in use. Pass --port with a free port or use --no-start-webapp.")
    next_bin = WEBAPP_DIR / "node_modules" / ".bin" / "next"
    if not next_bin.exists():
        raise E2EError("WebApp dependencies are missing. Run `npm --prefix WebApp install` first.")
    log_file = tempfile.NamedTemporaryFile(prefix="revnest-demo2-webapp-", suffix=".log", delete=False)
    log_path = Path(log_file.name)
    process = subprocess.Popen(
        [str(next_bin), "start", "-H", "127.0.0.1", "-p", str(port)],
        cwd=WEBAPP_DIR,
        env=env,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        text=True,
    )
    log_file.close()
    return process, log_path


def wait_for_run(client: HttpClient, run_id: str, timeout_seconds: int) -> dict[str, Any]:
    deadline = time.time() + timeout_seconds
    last = None
    while time.time() < deadline:
        last = client.get(f"/api/agent-runs/{run_id}", timeout=10)
        if last.get("status") in {"completed", "failed", "stopped"}:
            if last.get("status") != "completed":
                raise E2EError(f"Agent run ended with {last.get('status')}: {json.dumps(last, indent=2)[:2000]}")
            return last
        time.sleep(1)
    raise E2EError(f"Timed out waiting for run {run_id}; last status: {json.dumps(last, indent=2)[:2000]}")


def wait_for_discord_summary(capture: DiscordWebhookCapture, run_id: str, target_task: dict[str, Any], timeout_seconds: int = 10) -> dict[str, Any]:
    deadline = time.time() + timeout_seconds
    last_messages: list[dict[str, Any]] = []
    while time.time() < deadline:
        messages = capture.snapshot()
        last_messages = messages
        for message in messages:
            content = str((message.get("payload") or {}).get("content") or "")
            if run_id in content:
                required_tokens = [
                    "Revy found",
                    "MockHotel price adjustment",
                    str(target_task.get("property") or ""),
                    str(target_task.get("priceDate") or ""),
                    str(target_task.get("currentPrice") or ""),
                    str(target_task.get("agentSuggestedPrice") or ""),
                ]
                missing = [token for token in required_tokens if token and token not in content]
                if missing:
                    raise E2EError(f"Discord summary for run {run_id} is missing tokens {missing}: {content}")
                return message
        time.sleep(0.2)
    raise E2EError(f"Discord webhook did not receive a summary for run {run_id}: {last_messages}")


def query_property_price_rows(database_url: str, account_id: str, stay_date: dt.date) -> list[dict[str, Any]]:
    ids_array = "ARRAY[" + ", ".join(sql_literal(item) for item in PROPERTY_IDS) + "]::text[]"
    sql = f"""
SELECT COALESCE(json_agg(row_to_json(rows) ORDER BY property_id), '[]'::json)::text
FROM (
  SELECT property_id, price_date::text, fixed_price_cents, agent_price_cents
  FROM property_price
  WHERE property_id = ANY({ids_array})
    AND price_date = {sql_literal(iso_date(stay_date))}::date
) rows;
"""
    return psql_json(database_url, sql, label="query property_price rows")


def query_mockhotel_price(database_url: str, stay_date: dt.date) -> dict[str, Any]:
    sql = f"""
SELECT json_build_object(
  'room_type_id', room_type_id,
  'stay_date', stay_date::text,
  'price_cents', price_cents
)::text
FROM room_type_price
WHERE room_type_id = {sql_literal(TARGET_PROPERTY_ID)}
  AND stay_date = {sql_literal(iso_date(stay_date))}::date;
"""
    return psql_json(database_url, sql, label="query MockHotel accepted price")


def query_latest_price_log(database_url: str, account_id: str, property_id: str, stay_date: dt.date) -> dict[str, Any] | None:
    sql = f"""
SELECT data::text
FROM pricing_record
WHERE account_id = {sql_literal(account_id)}::uuid
  AND record_type = 'price_log'
  AND data->>'propertyId' = {sql_literal(property_id)}
  AND data->>'priceDate' = {sql_literal(iso_date(stay_date))}
ORDER BY created_at DESC, id DESC
LIMIT 1;
"""
    return psql_json(database_url, sql, label="query accepted price log")


def simulate_discord_prompt_accept(client: HttpClient, account_id: str, task: dict[str, Any], prompt_text: str) -> dict[str, Any]:
    """Discord prompt approval must route through WebApp accept, never PMS writes."""
    response = client.post(
        "/api/pricing-records",
        {
            "accountId": account_id,
            "taskId": task["id"],
            "action": "apply",
            "feedback": f"Discord prompt accepted: {prompt_text}",
        },
        timeout=30,
    )
    return {
        "prompt": prompt_text,
        "path": "webapp_accept_task",
        "direct_mockhotel_write_attempted": False,
        "response": response,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database-url",
        default=os.environ.get("CLAW_TEST_DATABASE_URL") or DEFAULT_CLAW_DATABASE_URL,
    )
    parser.add_argument("--mockhotel-database-url", default=os.environ.get("MOCKHOTEL_DATABASE_URL") or os.environ.get("MOCK_HOTEL_DATABASE_URL") or DEFAULT_MOCKHOTEL_DATABASE_URL)
    parser.add_argument("--account-id", default=DEFAULT_ACCOUNT_ID)
    parser.add_argument("--port", type=int, default=3210)
    parser.add_argument("--webapp-url")
    parser.add_argument("--no-start-webapp", action="store_true")
    parser.add_argument("--live-agent", action="store_true", help="Do not enable the deterministic demo2 fixture; use a real agent run.")
    parser.add_argument("--skip-webapp-build", action="store_true", help="Reuse the existing WebApp production build before starting next start.")
    parser.add_argument("--skip-discord-check", action="store_true", help="Do not require the local Discord webhook notification assertion.")
    parser.add_argument("--timeout-seconds", type=int, default=None)
    parser.add_argument("--stay-date", default=(dt.date.today() + dt.timedelta(days=4)).isoformat())
    args = parser.parse_args()

    stay_date = dt.date.fromisoformat(args.stay_date)
    timeout_seconds = args.timeout_seconds or (1800 if args.live_agent else 90)
    webapp_url = args.webapp_url or f"http://127.0.0.1:{args.port}"

    setup_claw_database(args.database_url, args.account_id, stay_date)
    setup_mockhotel_database(args.mockhotel_database_url, stay_date)
    outside_setup = assert_mockhotel_outside_min(args.mockhotel_database_url, stay_date)

    discord_capture: DiscordWebhookCapture | None = None
    if not args.skip_discord_check:
        if args.no_start_webapp:
            raise E2EError(
                "Discord verification requires this test to start WebApp so it can inject a local DISCORD_WEBHOOK_URL. "
                "Drop --no-start-webapp or pass --skip-discord-check for externally managed live-agent runs."
            )

    server_process: subprocess.Popen | None = None
    server_log_path: Path | None = None
    if not args.no_start_webapp:
        env = {
            **os.environ,
            "DATABASE_URL": args.database_url,
            "CLAW_DATABASE_URL": args.database_url,
            "CLAW_TEST_DATABASE_URL": args.database_url,
            "MOCKHOTEL_DATABASE_URL": args.mockhotel_database_url,
            "REVNEST_WEBAPP_PORT": str(args.port),
            "REVNEST_SESSION_SECRET": "demo2-e2e-local-session-secret",
            "REVNEST_INSECURE_LOCAL_COOKIES": "1",
            "REVNEST_DEMO2_E2E_STAY_DATE": iso_date(stay_date),
            "REVNEST_DEMO2_E2E_TARGET_PROPERTY_ID": TARGET_PROPERTY_ID,
        }
        if not args.live_agent:
            env["REVNEST_AGENT_RUN_FIXTURE"] = "demo2"
            env["REVNEST_ALLOW_AGENT_FIXTURES"] = "1"
        if not args.skip_webapp_build:
            build_webapp(env)
        if not port_available(args.port):
            raise E2EError(f"Port {args.port} is already in use. Pass --port with a free port or use --no-start-webapp.")
        if not args.skip_discord_check:
            discord_capture = DiscordWebhookCapture()
            discord_capture.start()
            env["DISCORD_WEBHOOK_URL"] = discord_capture.url
        server_process, server_log_path = start_webapp(args.port, env)

    client = HttpClient(webapp_url)
    try:
        wait_for_http(client, timeout_seconds=60, server_log_path=server_log_path)
        client.post("/api/login", {"email": "demo2-e2e-hotel@revnest.ai", "password": "demo2"})

        before_dashboard = client.get(f"/api/dashboard?accountId={args.account_id}")
        before_pending_count = len(before_dashboard.get("pendingTasks") or [])
        before_market_run_id = (before_dashboard.get("hotelHomeDashboard") or {}).get("marketDataRun", {}).get("runId")

        run = client.post(
            "/api/agent-runs",
            {
                "accountId": args.account_id,
                "propertyType": "hotel",
                "hotelScope": "all-room-types",
                "runtimeMode": "split-demo",
                "supplementalInfo": "Demo2 e2e hotel batch pricing run.",
            },
            timeout=30,
        )
        run_id = run["runId"]
        completed_run = wait_for_run(client, run_id, timeout_seconds=timeout_seconds)
        client.get(f"/api/revy/status?accountId={args.account_id}")

        after_dashboard = client.get(f"/api/dashboard?accountId={args.account_id}")
        market_run = (after_dashboard.get("hotelHomeDashboard") or {}).get("marketDataRun") or {}
        if market_run.get("runId") != run_id:
            raise E2EError(f"Market Signals Dashboard did not update to run {run_id}: {market_run}")

        price_rows = query_property_price_rows(args.database_url, args.account_id, stay_date)
        updated_property_ids = {row["property_id"] for row in price_rows}
        if updated_property_ids != set(PROPERTY_IDS):
            raise E2EError(f"Not all My Properties chart rows updated for {stay_date}: {price_rows}")

        pending_tasks = after_dashboard.get("pendingTasks") or []
        new_tasks = [task for task in pending_tasks if task.get("runId") == run_id]
        if not new_tasks:
            raise E2EError(f"No new pending task was generated for run {run_id}: {pending_tasks}")
        target_task = next((task for task in new_tasks if task.get("propertyId") == TARGET_PROPERTY_ID), new_tasks[0])

        discord_message = None
        if discord_capture is not None:
            discord_message = wait_for_discord_summary(discord_capture, run_id, target_task)

        mockhotel_before_prompt_accept = query_mockhotel_price(args.mockhotel_database_url, stay_date)
        if mockhotel_before_prompt_accept.get("price_cents") != outside_setup.get("price_cents"):
            raise E2EError(
                "MockHotel changed before the WebApp accept path ran; direct PMS writes must stay blocked: "
                f"{mockhotel_before_prompt_accept}"
            )

        discord_prompt_accept = simulate_discord_prompt_accept(
            client,
            args.account_id,
            target_task,
            "帮我写入 MockHotel PMS",
        )
        if discord_prompt_accept["direct_mockhotel_write_attempted"]:
            raise E2EError(f"Discord prompt attempted a direct MockHotel write: {discord_prompt_accept}")

        accept_payload = discord_prompt_accept["response"]
        if not accept_payload.get("ok") or not (accept_payload.get("mockHotelSync") or {}).get("ok"):
            raise E2EError(f"Accept did not report successful MockHotel sync: {accept_payload}")

        accepted_log = query_latest_price_log(args.database_url, args.account_id, TARGET_PROPERTY_ID, stay_date) or accept_payload.get("log") or {}
        if accepted_log.get("approvalSource") != "webapp_accept_button":
            raise E2EError(f"Discord prompt accept did not route through WebApp approval source: {accepted_log}")
        if not accepted_log.get("acceptedBy"):
            raise E2EError(f"Accepted price log is missing acceptedBy metadata: {accepted_log}")

        accepted_price = int(round(float(str(target_task["agentSuggestedPrice"]).replace("$", "")) * 100))
        mockhotel_after = query_mockhotel_price(args.mockhotel_database_url, stay_date)
        if mockhotel_after.get("price_cents") != accepted_price:
            raise E2EError(f"MockHotel DB did not update to accepted price {accepted_price}: {mockhotel_after}")

        final_dashboard = client.get(f"/api/dashboard?accountId={args.account_id}")
        remaining_target_tasks = [
            task
            for task in final_dashboard.get("pendingTasks") or []
            if task.get("id") == target_task["id"]
        ]
        if remaining_target_tasks:
            raise E2EError(f"Accepted pending task still appears in dashboard: {remaining_target_tasks}")

        result = {
            "ok": True,
            "mode": "live-agent" if args.live_agent else "fixture-agent",
            "account_id": args.account_id,
            "stay_date": iso_date(stay_date),
            "mockhotel_outside_min_max_before": outside_setup,
            "before_pending_count": before_pending_count,
            "before_market_run_id": before_market_run_id,
            "run_id": run_id,
            "run_status": completed_run.get("status"),
            "market_dashboard_run_id": market_run.get("runId"),
            "updated_property_price_rows": price_rows,
            "new_pending_task_count": len(new_tasks),
            "discord_notification_count": len(discord_capture.snapshot()) if discord_capture is not None else None,
            "discord_notification": (discord_message or {}).get("payload") if discord_message else None,
            "discord_prompt_accept_path": discord_prompt_accept["path"],
            "direct_mockhotel_write_attempted": discord_prompt_accept["direct_mockhotel_write_attempted"],
            "accepted_task_id": target_task["id"],
            "approval_source": accepted_log.get("approvalSource"),
            "accepted_price_cents": accepted_price,
            "mockhotel_before_prompt_accept": mockhotel_before_prompt_accept,
            "mockhotel_after_accept": mockhotel_after,
        }
        print(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True))
        return 0
    finally:
        if server_process is not None:
            server_process.terminate()
            try:
                server_process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server_process.kill()
                server_process.wait(timeout=5)
        if discord_capture is not None:
            discord_capture.stop()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except E2EError as exc:
        print(f"demo2_hotel_e2e: FAIL\n{exc}", file=sys.stderr)
        raise SystemExit(1)
