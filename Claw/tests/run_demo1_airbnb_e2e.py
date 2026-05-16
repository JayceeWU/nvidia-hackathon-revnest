#!/usr/bin/env python3
"""End-to-end Demo1 Airbnb add-property flow test.

Default mode starts a temporary WebApp production server with
REVNEST_AGENT_RUN_FIXTURE=demo1. The flow mirrors the default Airbnb URL wizard:
login, save a draft property with default data, start the Airbnb OpenClaw run,
wait for completion, activate the property, and verify it appears under
My Properties with saved forecast rows.

Use --live-agent with --no-start-webapp to exercise a real OpenClaw run against
an already running WebApp.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import http.cookiejar
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
WEBAPP_DIR = ROOT / "WebApp"
DEFAULT_DATABASE_URL = "postgres://postgres:postgres@localhost:55434/dev"
ACCOUNT_ID = "00000000-0000-0000-0000-0000000001e1"
ACCOUNT_EMAIL = "demo1-e2e-airbnb@revnest.ai"
ACCOUNT_PASSWORD = "demo1"
DEFAULT_AIRBNB_URL = "https://www.airbnb.com/rooms/1386388491046164092?photo_id=2119296775&source_impression_id=p3_1778635269_P3AqwMDcxp41Ckqm&previous_page_section_name=1000"
PROPERTY_ID = "airbnb-1386388491046164092"


class E2EError(RuntimeError):
    pass


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
    return json.loads(result.stdout.strip() or "null")


def setup_database(database_url: str) -> None:
    sql = f"""
BEGIN;
DELETE FROM property_price WHERE property_id = {sql_literal(PROPERTY_ID)};
DELETE FROM revy_conversation WHERE account_id = {sql_literal(ACCOUNT_ID)}::uuid OR property_id = {sql_literal(PROPERTY_ID)};
DELETE FROM pricing_record WHERE account_id = {sql_literal(ACCOUNT_ID)}::uuid;
DELETE FROM property WHERE id = {sql_literal(PROPERTY_ID)} OR account_id = {sql_literal(ACCOUNT_ID)}::uuid;
DELETE FROM account WHERE id = {sql_literal(ACCOUNT_ID)}::uuid;

INSERT INTO account (id, email, password_hash, name, role, account_type)
VALUES ({sql_literal(ACCOUNT_ID)}::uuid, {sql_literal(ACCOUNT_EMAIL)}, crypt({sql_literal(ACCOUNT_PASSWORD)}, gen_salt('bf')), 'Demo1 E2E Airbnb Host', 'host', 'airbnb');
COMMIT;
"""
    run_psql(database_url, sql, label="setup Demo1 Airbnb account")


def default_property_payload() -> dict[str, Any]:
    return {
        "id": PROPERTY_ID,
        "name": "Airbnb Listing 4092",
        "displayNameSource": "airbnb_url_fallback",
        "propertyType": "Airbnb",
        "roomCount": 1,
        "zipCode": "",
        "location": "Pending browser verification",
        "streetAddress": "Pending browser verification",
        "guests": "Pending verification",
        "bathroom": "Pending verification",
        "beds": "Pending verification",
        "bedSize": "Pending verification",
        "amenities": [],
        "fixedPrice": None,
        "agentAdr": None,
        "occupancy": "Pending",
        "revparLift": "Pending",
        "planDuration": "2 days",
        "priceRange": "$300-$700",
        "pricingConnection": "manual",
        "additionalInfo": "",
        "importFromAirbnb": True,
        "status": "draft",
        "onboardingSource": "airbnb_url",
        "airbnbUrl": DEFAULT_AIRBNB_URL,
        "myPlace": DEFAULT_AIRBNB_URL,
        "minPrice": 300,
        "maxPrice": 700,
        "pricingHorizon": 2,
        "supplementalInfo": "",
        "forecast": [],
    }


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

    def patch(self, path: str, payload: dict[str, Any], timeout: int = 30) -> dict[str, Any]:
        return self.request("PATCH", path, payload=payload, timeout=timeout)


def port_available(port: int) -> bool:
    with contextlib.closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex(("127.0.0.1", port)) != 0


def build_webapp(env: dict[str, str]) -> Path:
    next_bin = WEBAPP_DIR / "node_modules" / ".bin" / "next"
    if not next_bin.exists():
        raise E2EError("WebApp dependencies are missing. Run `npm --prefix WebApp install` first.")
    log_file = tempfile.NamedTemporaryFile(prefix="revnest-demo1-webapp-build-", suffix=".log", delete=False)
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
        raise E2EError(f"WebApp build failed before Demo1 e2e server start:\n{tail}")
    return log_path


def start_webapp(port: int, env: dict[str, str]) -> tuple[subprocess.Popen, Path]:
    if not port_available(port):
        raise E2EError(f"Port {port} is already in use. Pass --port with a free port or use --no-start-webapp.")
    next_bin = WEBAPP_DIR / "node_modules" / ".bin" / "next"
    log_file = tempfile.NamedTemporaryFile(prefix="revnest-demo1-webapp-", suffix=".log", delete=False)
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


def wait_for_http(client: HttpClient, timeout_seconds: int, server_log_path: Path | None = None) -> None:
    deadline = time.time() + timeout_seconds
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            client.get("/api/access-path", timeout=5)
            return
        except Exception as exc:  # noqa: BLE001 - reported below.
            last_error = exc
            time.sleep(1)
    tail = ""
    if server_log_path and server_log_path.exists():
        tail = "\nWebApp log tail:\n" + "\n".join(server_log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-40:])
    raise E2EError(f"WebApp did not become ready: {last_error}{tail}")


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


def query_price_rows(database_url: str) -> list[dict[str, Any]]:
    sql = f"""
SELECT COALESCE(json_agg(row_to_json(rows) ORDER BY price_date), '[]'::json)::text
FROM (
  SELECT property_id, price_date::text, fixed_price_cents, agent_price_cents
  FROM property_price
  WHERE property_id = {sql_literal(PROPERTY_ID)}
) rows;
"""
    return psql_json(database_url, sql, label="query Demo1 property_price rows")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", default=os.environ.get("CLAW_DATABASE_URL") or os.environ.get("DATABASE_URL") or DEFAULT_DATABASE_URL)
    parser.add_argument("--port", type=int, default=3211)
    parser.add_argument("--webapp-url")
    parser.add_argument("--no-start-webapp", action="store_true")
    parser.add_argument("--live-agent", action="store_true", help="Do not enable the deterministic Demo1 fixture; use a real OpenClaw run.")
    parser.add_argument("--skip-webapp-build", action="store_true")
    parser.add_argument("--timeout-seconds", type=int, default=None)
    args = parser.parse_args()

    timeout_seconds = args.timeout_seconds or (1800 if args.live_agent else 90)
    webapp_url = args.webapp_url or f"http://127.0.0.1:{args.port}"
    setup_database(args.database_url)

    server_process: subprocess.Popen | None = None
    server_log_path: Path | None = None
    if not args.no_start_webapp:
        env = {
            **os.environ,
            "DATABASE_URL": args.database_url,
            "CLAW_DATABASE_URL": args.database_url,
            "REVNEST_WEBAPP_PORT": str(args.port),
            "REVNEST_SESSION_SECRET": "demo1-e2e-local-session-secret",
            "REVNEST_INSECURE_LOCAL_COOKIES": "1",
        }
        if not args.live_agent:
            env["REVNEST_AGENT_RUN_FIXTURE"] = "demo1"
        if not args.skip_webapp_build:
            build_webapp(env)
        server_process, server_log_path = start_webapp(args.port, env)

    client = HttpClient(webapp_url)
    try:
        wait_for_http(client, timeout_seconds=60, server_log_path=server_log_path)
        login = client.post("/api/login", {"email": ACCOUNT_EMAIL, "password": ACCOUNT_PASSWORD})
        if login.get("user", {}).get("accountType") != "airbnb":
            raise E2EError(f"Login did not return an Airbnb account: {login}")

        saved = client.post("/api/properties", {"accountId": ACCOUNT_ID, "property": default_property_payload()})
        saved_property = saved.get("property") or {}
        if saved_property.get("status") != "draft":
            raise E2EError(f"Saved property did not start as draft: {saved_property}")

        run = client.post(
            "/api/agent-runs",
            {
                "accountId": ACCOUNT_ID,
                "propertyId": PROPERTY_ID,
                "propertyType": "airbnb",
                "runtimeMode": "host-openclaw",
                "myPlace": DEFAULT_AIRBNB_URL,
                "minPrice": 300,
                "maxPrice": 700,
                "pricingHorizon": 2,
                "supplementalInfo": "",
            },
            timeout=30,
        )
        run_id = run["runId"]
        if run.get("runtimeMode") != "host-openclaw":
            raise E2EError(f"Airbnb run did not resolve to host-openclaw: {run}")
        completed_run = wait_for_run(client, run_id, timeout_seconds=timeout_seconds)
        event_tools = {event.get("tool") for event in completed_run.get("events") or []}
        if not args.live_agent and "openclaw-agent-fixture" not in event_tools:
            raise E2EError(f"Demo1 fixture did not record an OpenClaw event: {completed_run.get('events')}")

        client.patch(
            f"/api/properties/{PROPERTY_ID}",
            {
                "accountId": ACCOUNT_ID,
                "data": {
                    "status": "active",
                    "activatedAt": dt.datetime.now(dt.UTC).isoformat().replace("+00:00", "Z"),
                    "activeAgentRunId": None,
                    "lastAgentRunId": run_id,
                    "agentRunStatus": "completed",
                },
            },
        )

        dashboard = client.get(f"/api/dashboard?accountId={ACCOUNT_ID}")
        properties = dashboard.get("properties") or []
        added = next((item for item in properties if item.get("id") == PROPERTY_ID), None)
        if not added:
            raise E2EError(f"My Properties did not include the added Airbnb property: {properties}")
        if added.get("status") != "active":
            raise E2EError(f"Added property was not active after successful run: {added}")
        if added.get("agentRunStatus") != "completed":
            raise E2EError(f"Added property did not show completed agent status: {added}")
        if not added.get("forecast"):
            raise E2EError(f"Added property did not have forecast rows for the chart: {added}")

        price_rows = query_price_rows(args.database_url)
        if len(price_rows) < 2:
            raise E2EError(f"OpenClaw run did not save expected property_price rows: {price_rows}")

        result = {
            "ok": True,
            "mode": "live-agent" if args.live_agent else "fixture-agent",
            "account_id": ACCOUNT_ID,
            "property_id": PROPERTY_ID,
            "run_id": run_id,
            "runtime_mode": completed_run.get("runtimeMode"),
            "run_status": completed_run.get("status"),
            "openclaw_event_seen": args.live_agent or "openclaw-agent-fixture" in event_tools,
            "my_properties_count": len(properties),
            "added_property": {
                "id": added.get("id"),
                "name": added.get("name"),
                "status": added.get("status"),
                "agentRunStatus": added.get("agentRunStatus"),
                "forecastCount": len(added.get("forecast") or []),
            },
            "property_price_rows": price_rows,
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


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except E2EError as exc:
        print(f"demo1_airbnb_e2e: FAIL\n{exc}", file=sys.stderr)
        raise SystemExit(1)
