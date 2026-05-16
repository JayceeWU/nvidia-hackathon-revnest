#!/usr/bin/env python3
"""
Run the RevNest pricing workflow agent with durable progress-log lifecycle events.

The model may time out before it emits any tool call. This wrapper writes a
start event before invoking OpenClaw, then writes a completion/failure event
after OpenClaw exits, so web clients watching the JSONL log are never left with
an empty stream.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import shlex
from pathlib import Path, PurePosixPath
import queue
import shutil
import subprocess
import sys
import threading
import time
import tempfile
import urllib.parse
import uuid
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import progress_logger


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LOG_PATH = ROOT / "runs" / "airbnb-pricing-progress.log"
DEFAULT_NEMOCLAW_SANDBOX = "my-assistant"
DEFAULT_NEMOCLAW_WORKDIR = "/sandbox/RevNest/Claw"
DEFAULT_RUNTIME_MODE = "split-demo"
DEFAULT_OPENCLAW_AGENT = os.environ.get("REVNEST_OPENCLAW_AGENT", "main")
DEFAULT_OPENCLAW_MAX_ATTEMPTS = int(os.environ.get("REVNEST_OPENCLAW_MAX_ATTEMPTS", "2"))
DEFAULT_OPENCLAW_IDLE_RETRY_SECONDS = int(os.environ.get("REVNEST_OPENCLAW_IDLE_RETRY_SECONDS", "60"))
WORKFLOW_NAME = "pricing-workflow"
DEFAULT_DATABASE_URL = "postgres://postgres:postgres@localhost:55434/dev"
LIFECYCLE_STAGES = {"agent_start", "agent_finish", "wrapper_retry"}

US_STATE_CODES = {
    "alabama": "AL",
    "alaska": "AK",
    "arizona": "AZ",
    "arkansas": "AR",
    "california": "CA",
    "colorado": "CO",
    "connecticut": "CT",
    "delaware": "DE",
    "district of columbia": "DC",
    "florida": "FL",
    "georgia": "GA",
    "hawaii": "HI",
    "idaho": "ID",
    "illinois": "IL",
    "indiana": "IN",
    "iowa": "IA",
    "kansas": "KS",
    "kentucky": "KY",
    "louisiana": "LA",
    "maine": "ME",
    "maryland": "MD",
    "massachusetts": "MA",
    "michigan": "MI",
    "minnesota": "MN",
    "mississippi": "MS",
    "missouri": "MO",
    "montana": "MT",
    "nebraska": "NE",
    "nevada": "NV",
    "new hampshire": "NH",
    "new jersey": "NJ",
    "new mexico": "NM",
    "new york": "NY",
    "north carolina": "NC",
    "north dakota": "ND",
    "ohio": "OH",
    "oklahoma": "OK",
    "oregon": "OR",
    "pennsylvania": "PA",
    "rhode island": "RI",
    "south carolina": "SC",
    "south dakota": "SD",
    "tennessee": "TN",
    "texas": "TX",
    "utah": "UT",
    "vermont": "VT",
    "virginia": "VA",
    "washington": "WA",
    "west virginia": "WV",
    "wisconsin": "WI",
    "wyoming": "WY",
}

US_STATE_TIMEZONES = {
    "AL": "America/Chicago",
    "AK": "America/Anchorage",
    "AZ": "America/Phoenix",
    "AR": "America/Chicago",
    "CA": "America/Los_Angeles",
    "CO": "America/Denver",
    "CT": "America/New_York",
    "DC": "America/New_York",
    "DE": "America/New_York",
    "FL": "America/New_York",
    "GA": "America/New_York",
    "HI": "Pacific/Honolulu",
    "IA": "America/Chicago",
    "ID": "America/Denver",
    "IL": "America/Chicago",
    "IN": "America/Indiana/Indianapolis",
    "KS": "America/Chicago",
    "KY": "America/New_York",
    "LA": "America/Chicago",
    "MA": "America/New_York",
    "MD": "America/New_York",
    "ME": "America/New_York",
    "MI": "America/Detroit",
    "MN": "America/Chicago",
    "MO": "America/Chicago",
    "MS": "America/Chicago",
    "MT": "America/Denver",
    "NC": "America/New_York",
    "ND": "America/Chicago",
    "NE": "America/Chicago",
    "NH": "America/New_York",
    "NJ": "America/New_York",
    "NM": "America/Denver",
    "NV": "America/Los_Angeles",
    "NY": "America/New_York",
    "OH": "America/New_York",
    "OK": "America/Chicago",
    "OR": "America/Los_Angeles",
    "PA": "America/New_York",
    "RI": "America/New_York",
    "SC": "America/New_York",
    "SD": "America/Chicago",
    "TN": "America/Chicago",
    "TX": "America/Chicago",
    "UT": "America/Denver",
    "VA": "America/New_York",
    "VT": "America/New_York",
    "WA": "America/Los_Angeles",
    "WI": "America/Chicago",
    "WV": "America/New_York",
    "WY": "America/Denver",
}

ZIP_STATE_RANGES = (
    (10, 27, "MA"),
    (28, 29, "RI"),
    (30, 38, "NH"),
    (39, 49, "ME"),
    (50, 59, "VT"),
    (60, 69, "CT"),
    (70, 89, "NJ"),
    (90, 149, "NY"),
    (150, 196, "PA"),
    (197, 199, "DE"),
    (200, 205, "DC"),
    (206, 219, "MD"),
    (220, 246, "VA"),
    (247, 268, "WV"),
    (270, 289, "NC"),
    (290, 299, "SC"),
    (300, 319, "GA"),
    (320, 349, "FL"),
    (350, 369, "AL"),
    (370, 385, "TN"),
    (386, 397, "MS"),
    (398, 399, "GA"),
    (400, 427, "KY"),
    (430, 459, "OH"),
    (460, 479, "IN"),
    (480, 499, "MI"),
    (500, 528, "IA"),
    (530, 549, "WI"),
    (550, 567, "MN"),
    (570, 577, "SD"),
    (580, 588, "ND"),
    (590, 599, "MT"),
    (600, 629, "IL"),
    (630, 658, "MO"),
    (660, 679, "KS"),
    (680, 693, "NE"),
    (700, 714, "LA"),
    (716, 729, "AR"),
    (730, 749, "OK"),
    (750, 799, "TX"),
    (800, 816, "CO"),
    (820, 831, "WY"),
    (832, 838, "ID"),
    (840, 847, "UT"),
    (850, 865, "AZ"),
    (870, 884, "NM"),
    (889, 898, "NV"),
    (900, 961, "CA"),
    (970, 979, "OR"),
    (980, 994, "WA"),
    (995, 999, "AK"),
)

EXPLICIT_TIMEZONE_KEYS = (
    "timeZone",
    "timezone",
    "tz",
    "ianaTimeZone",
    "iana_timezone",
    "propertyTimeZone",
    "property_timezone",
)


def timestamp_slug() -> str:
    return dt.datetime.now(dt.UTC).strftime("%Y%m%d-%H%M%S")


def load_dotenv(base_env: dict[str, str]) -> dict[str, str]:
    env = dict(base_env)
    dotenv_path = ROOT / ".env"
    if not dotenv_path.exists():
        return env

    for raw_line in dotenv_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'\"")
        if key and (key not in env or not env.get(key)):
            env[key] = value
    return env


def database_url_from(env: dict[str, str]) -> str:
    return env.get("CLAW_DATABASE_URL") or env.get("DATABASE_URL") or DEFAULT_DATABASE_URL


def sql_literal(value: object) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def parse_database_url(database_url: str) -> dict[str, str]:
    parsed = urllib.parse.urlparse(database_url)
    return {
        "database": (parsed.path or "/dev").lstrip("/") or "dev",
        "user": urllib.parse.unquote(parsed.username or "postgres"),
    }


def run_psycopg_sql(sql: str, database_url: str) -> str:
    try:
        import psycopg  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RuntimeError("psycopg is not installed") from exc

    rows_out: list[str] = []
    try:
        with psycopg.connect(database_url) as conn:
            with conn.cursor() as cur:
                cur.execute(sql)
                while True:
                    if cur.description:
                        for row in cur.fetchall():
                            rows_out.append("|".join("" if value is None else str(value) for value in row))
                    if not cur.nextset():
                        break
            conn.commit()
    except Exception as exc:  # noqa: BLE001 - preserve concise wrapper error context.
        raise RuntimeError(f"psycopg SQL failed: {exc}") from exc
    return "\n".join(rows_out)


def run_psql_sql(sql: str, env: dict[str, str]) -> str:
    database_url = database_url_from(env)
    if shutil.which("psql", path=env.get("PATH")):
        cmd = ["psql", database_url, "-v", "ON_ERROR_STOP=1", "-tA", "-c", sql]
        result = subprocess.run(cmd, cwd=ROOT, env=env, text=True, capture_output=True, check=False)
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "psql command failed").strip()
            raise RuntimeError(detail)
        return result.stdout.strip()

    try:
        return run_psycopg_sql(sql, database_url)
    except RuntimeError as psycopg_error:
        if "psycopg is not installed" not in str(psycopg_error):
            raise

    info = parse_database_url(database_url)
    cmd = [
        "docker",
        "compose",
        "-f",
        str(ROOT / "data" / "docker-compose.yml"),
        "exec",
        "-T",
        "postgres",
        "psql",
        "-U",
        info["user"],
        "-d",
        info["database"],
        "-v",
        "ON_ERROR_STOP=1",
        "-tA",
        "-c",
        sql,
    ]
    result = subprocess.run(cmd, cwd=ROOT, env=env, text=True, capture_output=True, check=False)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "psql command failed").strip()
        raise RuntimeError(detail)
    return result.stdout.strip()


def read_property_row(env: dict[str, str], account_id: str, property_id: str) -> dict | None:
    sql = f"""
SELECT json_build_object(
  'id', id,
  'account_id', account_id::text,
  'min_price_cents', min_price_cents,
  'max_price_cents', max_price_cents,
  'pricing_horizon', pricing_horizon,
  'my_place', my_place,
  'room_count', room_count,
  'capacity', capacity,
  'zip_code', zip_code,
  'county', county,
  'state', state,
  'city', city,
  'bed', bed,
  'bath', bath,
  'other_info', other_info,
  'data', data
)::text
FROM property
WHERE account_id = {sql_literal(account_id)}::uuid
  AND id = {sql_literal(property_id)}
LIMIT 1;
"""
    output = run_psql_sql(sql, env)
    if not output:
        return None
    return json.loads(output.splitlines()[-1])


def read_hotel_room_type_rows(env: dict[str, str], account_id: str) -> list[dict]:
    sql = f"""
SELECT COALESCE(json_agg(row_to_json(property_rows) ORDER BY id), '[]'::json)::text
FROM (
  SELECT
    id,
    account_id::text,
    min_price_cents,
    max_price_cents,
    pricing_horizon,
    my_place,
    room_count,
    capacity,
    zip_code,
    county,
    state,
    city,
    bed,
    bath,
    other_info,
    data
  FROM property
  WHERE account_id = {sql_literal(account_id)}::uuid
    AND data->>'propertyType' = 'Hotel Room Type'
) property_rows;
"""
    output = run_psql_sql(sql, env)
    if not output:
        return []
    return json.loads(output.splitlines()[-1])


def money_to_cents(value: object, field_name: str) -> int:
    if value is None or value == "":
        raise ValueError(f"{field_name} is required")
    text = str(value).strip().replace("$", "").replace(",", "")
    if not text:
        raise ValueError(f"{field_name} is required")
    return int(round(float(text) * 100))


def cents_to_dollars(cents: object | None) -> int | float | None:
    if cents is None:
        return None
    value = round(float(cents) / 100, 2)
    return int(value) if value.is_integer() else value


def parse_price_range(value: object) -> tuple[object | None, object | None]:
    if not isinstance(value, str):
        return None, None
    match = re.search(r"\$?([0-9][0-9,.]*)\s*-\s*\$?([0-9][0-9,.]*)", value)
    if not match:
        return None, None
    return match.group(1), match.group(2)


def parse_plan_duration(value: object) -> int | None:
    match = re.search(r"\d+", str(value or ""))
    return int(match.group(0)) if match else None


def value_from_data(data: dict, keys: tuple[str, ...]) -> object | None:
    for key in keys:
        if key in data and data[key] not in (None, ""):
            return data[key]
    return None


def normalize_optional_text(value: object | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None



def valid_timezone_name(value: object | None) -> str | None:
    name = normalize_optional_text(value)
    if not name:
        return None
    try:
        ZoneInfo(name)
    except ZoneInfoNotFoundError:
        return None
    return name


def normalize_state_code(value: object | None) -> str | None:
    text = normalize_optional_text(value)
    if not text:
        return None
    upper = text.upper()
    if upper in US_STATE_TIMEZONES:
        return upper
    return US_STATE_CODES.get(text.lower())


def state_code_from_zip(value: object | None) -> str | None:
    text = normalize_optional_text(value)
    if not text:
        return None
    match = re.search(r"\d{3}", text)
    if not match:
        return None
    prefix = int(match.group(0))
    for start, end, state_code in ZIP_STATE_RANGES:
        if start <= prefix <= end:
            return state_code
    return None


def state_code_from_text(value: object | None) -> str | None:
    text = normalize_optional_text(value)
    if not text:
        return None
    direct = normalize_state_code(text)
    if direct:
        return direct
    match = re.search(r"(?:^|[,\s])([A-Z]{2})(?:\b|,)", text.upper())
    if match and match.group(1) in US_STATE_TIMEZONES:
        return match.group(1)
    lowered = text.lower()
    for state_name, state_code in US_STATE_CODES.items():
        if re.search(rf"\b{re.escape(state_name)}\b", lowered):
            return state_code
    return None


def timezone_from_property(existing: dict | None) -> tuple[str, str]:
    existing = existing or {}
    data = dict(existing.get("data") or {})

    for key in EXPLICIT_TIMEZONE_KEYS:
        timezone_name = valid_timezone_name(data.get(key))
        if timezone_name:
            return timezone_name, f"property.data.{key}"

    state_candidates = (
        ("property.state", existing.get("state")),
        ("property.data.state", value_from_data(data, ("state", "stateCode", "state_code"))),
        ("property.data.location", value_from_data(data, ("location", "address", "streetAddress", "street_address", "market"))),
    )
    for source, state_value in state_candidates:
        state_code = state_code_from_text(state_value)
        if state_code and state_code in US_STATE_TIMEZONES:
            return US_STATE_TIMEZONES[state_code], source

    zip_state = state_code_from_zip(first_non_empty(existing.get("zip_code"), value_from_data(data, ("zipCode", "zip_code"))))
    if zip_state and zip_state in US_STATE_TIMEZONES:
        return US_STATE_TIMEZONES[zip_state], "property.zip_code"

    return "UTC", "fallback_utc"


def local_pricing_start_date(existing: dict | None) -> tuple[str, str, str]:
    timezone_name, source = timezone_from_property(existing)
    local_today = dt.datetime.now(ZoneInfo(timezone_name)).date().isoformat()
    return local_today, timezone_name, source


def generated_property_id(property_type: str, my_place: str | None) -> str:
    if my_place:
        match = re.search(r"/rooms/(\d+)", my_place)
        if match:
            return f"airbnb-{match.group(1)}"
    return f"{property_type}-{timestamp_slug()}-{uuid.uuid4().hex[:8]}"


def format_money(value: int | float) -> str:
    return str(value) if float(value).is_integer() else f"{value:.2f}"


PROFILE_FIELD_KEYS = {
    "room_count": ("roomCount", "room_count"),
    "capacity": ("capacity",),
    "zip_code": ("zipCode", "zip_code"),
    "county": ("county",),
    "state": ("state",),
    "city": ("city",),
    "bed": ("bed", "beds"),
    "bath": ("bath", "bathroom"),
    "other_info": ("otherInfo", "other_info"),
}

PROFILE_JSON_KEYS = {
    "room_count": "roomCount",
    "capacity": "capacity",
    "zip_code": "zipCode",
    "county": "county",
    "state": "state",
    "city": "city",
    "bed": "bed",
    "bath": "bath",
    "other_info": "otherInfo",
}


def first_non_empty(*values: object) -> object | None:
    for value in values:
        if value not in (None, ""):
            return value
    return None


def airbnb_room_id(value: object | None) -> str | None:
    text = normalize_optional_text(value)
    if not text:
        return None
    match = re.search(r"/rooms/(\d+)", text, re.I)
    return match.group(1) if match else None


def short_airbnb_room_suffix(room_id: object | None) -> str | None:
    text = normalize_optional_text(room_id)
    if not text:
        return None
    return text[-4:] if len(text) > 4 else text


def clean_airbnb_title(value: object | None) -> str | None:
    text = normalize_optional_text(value)
    if not text:
        return None
    text = re.sub(r"\s*[|-]\s*Airbnb\s*$", "", text, flags=re.I).strip()
    parts = [part.strip() for part in re.split(r"\s+(?:-|[|])\s+", text) if part.strip()]
    if len(parts) > 1 and re.search(r"\b(for rent|vacation rental|airbnb|united states|apartments?|homes?)\b", " ".join(parts[1:]), re.I):
        text = parts[0]
    return re.sub(r"^airbnb\s*[:|-]\s*", "", text, flags=re.I).strip() or None


def looks_like_placeholder_airbnb_name(value: object | None, property_id: str | None = None, room_id: str | None = None) -> bool:
    text = normalize_optional_text(value)
    if not text:
        return True
    lower = text.lower()
    if re.search(r"\b(pending browser verification|pending verification|not specified)\b", lower):
        return True
    if property_id and lower == property_id.lower():
        return True
    if re.match(r"^airbnb[-\s]+\d{6,}$", text, re.I):
        return True
    if re.match(r"^airbnb listing \d{1,6}$", text, re.I):
        return True
    if re.match(r"^airbnb stay(?:\s*-\s*listing \d{1,6})?$", text, re.I):
        return True
    if room_id and len(room_id) > 6 and room_id in text:
        return True
    return False


def compact_display_name(parts: list[object | None]) -> str | None:
    output: list[str] = []
    seen: set[str] = set()
    for value in parts:
        text = normalize_optional_text(value)
        if not text or looks_like_placeholder_airbnb_name(text):
            continue
        key = text.lower()
        if key in seen:
            continue
        output.append(text)
        seen.add(key)
    if not output:
        return None
    joined = " - ".join(output)
    return f"{joined[:93].rstrip()}..." if len(joined) > 96 else joined


def human_readable_airbnb_property_name(
    property_id: str | None,
    my_place: str | None,
    data: dict | None,
    current_name: object | None = None,
) -> str:
    data = data or {}
    room_id = (
        airbnb_room_id(my_place)
        or airbnb_room_id(value_from_data(data, ("airbnbUrl", "myPlace", "my_place")))
        or (property_id.removeprefix("airbnb-") if property_id and property_id.startswith("airbnb-") else None)
    )
    current = normalize_optional_text(current_name or value_from_data(data, ("name", "propertyName", "property_name")))
    if current and not looks_like_placeholder_airbnb_name(current, property_id, room_id):
        return current

    title = clean_airbnb_title(value_from_data(data, ("listingTitle", "listing_title", "title", "propertyTitle", "property_title")))
    city = normalize_optional_text(value_from_data(data, ("city",)))
    state = normalize_optional_text(value_from_data(data, ("state", "stateCode", "state_code")))
    location = normalize_optional_text(
        first_non_empty(
            value_from_data(data, ("neighborhood",)),
            f"{city}, {state}" if city and state else None,
            city,
            value_from_data(data, ("location", "market", "address")),
        )
    )
    listing_type = normalize_optional_text(
        value_from_data(
            data,
            (
                "listingType",
                "listing_type",
                "roomType",
                "room_type",
                "spaceType",
                "space_type",
                "propertyCategory",
                "property_category",
            ),
        )
    )

    profile_name = compact_display_name([title, location, listing_type])
    if profile_name:
        return profile_name
    if location or listing_type:
        fallback = compact_display_name([location, listing_type or "Airbnb Stay", f"Listing {short_airbnb_room_suffix(room_id)}" if room_id else None])
        if fallback:
            return fallback
    suffix = short_airbnb_room_suffix(room_id)
    return f"Airbnb Listing {suffix}" if suffix else "Airbnb Stay"


def row_data(row: dict) -> dict:
    data = row.get("data")
    return data if isinstance(data, dict) else {}


def room_type_name(row: dict) -> str:
    data = row_data(row)
    return (
        normalize_optional_text(value_from_data(data, ("roomType", "room_type", "name")))
        or normalize_optional_text(row.get("id"))
        or "hotel-room-type"
    )


def room_type_market_location(row: dict) -> dict[str, str | None]:
    data = row_data(row)
    city = normalize_optional_text(first_non_empty(row.get("city"), value_from_data(data, ("city",))))
    raw_state = first_non_empty(row.get("state"), value_from_data(data, ("state", "stateCode", "state_code")))
    state = normalize_state_code(raw_state) or normalize_optional_text(raw_state)
    zip_code = normalize_optional_text(first_non_empty(row.get("zip_code"), value_from_data(data, ("zipCode", "zip_code"))))
    return {"city": city, "state": state, "zip_code": zip_code}


def room_type_market_key(row: dict) -> tuple[str, str, str]:
    location = room_type_market_location(row)
    return (
        (location.get("city") or "").strip().lower(),
        (location.get("state") or "").strip().upper(),
        (location.get("zip_code") or "").strip(),
    )


def room_type_market_address(room_type: dict) -> str:
    location = room_type.get("market_location") or {}
    parts = [location.get("city"), location.get("state"), location.get("zip_code")]
    return ", ".join(str(part) for part in parts if part)


def room_type_values(row: dict, horizon_override: int | None = None) -> tuple[int, int, int]:
    data = row_data(row)
    range_min, range_max = parse_price_range(data.get("priceRange"))
    min_value = (
        cents_to_dollars(row.get("min_price_cents"))
        or value_from_data(data, ("minPrice", "min_price", "minPriceUsd", "min_price_usd"))
        or range_min
    )
    max_value = (
        cents_to_dollars(row.get("max_price_cents"))
        or value_from_data(data, ("maxPrice", "max_price", "maxPriceUsd", "max_price_usd"))
        or range_max
    )
    horizon_value = (
        horizon_override
        or row.get("pricing_horizon")
        or value_from_data(data, ("pricingHorizon", "pricing_horizon", "horizon"))
        or parse_plan_duration(data.get("planDuration"))
    )

    property_id = row.get("id")
    missing = []
    if min_value in (None, ""):
        missing.append("min_price")
    if max_value in (None, ""):
        missing.append("max_price")
    if horizon_value in (None, ""):
        missing.append("pricing_horizon")
    if missing:
        raise ValueError(f"Hotel room type {property_id} is missing required input(s): {', '.join(missing)}")

    min_cents = money_to_cents(min_value, f"{property_id}.min_price")
    max_cents = money_to_cents(max_value, f"{property_id}.max_price")
    horizon = int(horizon_value)
    if min_cents < 0:
        raise ValueError(f"Hotel room type {property_id} min_price cannot be negative")
    if max_cents < min_cents:
        raise ValueError(f"Hotel room type {property_id} max_price cannot be lower than min_price")
    if horizon < 1 or horizon > 730:
        raise ValueError(f"Hotel room type {property_id} pricing_horizon must be between 1 and 730")
    return min_cents, max_cents, horizon


def build_room_type_property(row: dict, horizon_override: int | None = None) -> dict:
    data = row_data(row)
    min_cents, max_cents, horizon = room_type_values(row, horizon_override)
    profile = property_profile_values(row, data)
    return {
        "property_id": str(row["id"]),
        "property_name": normalize_optional_text(value_from_data(data, ("name", "propertyName", "property_name"))) or room_type_name(row),
        "room_type": room_type_name(row),
        "min_price": cents_to_dollars(min_cents),
        "max_price": cents_to_dollars(max_cents),
        "min_price_cents": min_cents,
        "max_price_cents": max_cents,
        "pricing_horizon": horizon,
        "room_count": profile.get("room_count"),
        "capacity": profile.get("capacity"),
        "zip_code": profile.get("zip_code"),
        "county": profile.get("county"),
        "state": profile.get("state"),
        "city": profile.get("city"),
        "bed": profile.get("bed"),
        "bath": profile.get("bath"),
        "other_info": profile.get("other_info"),
        "market_location": room_type_market_location(row),
        "data": data,
    }


def validate_single_hotel_market(rows: list[dict]) -> None:
    markets: dict[tuple[str, str, str], list[str]] = {}
    for row in rows:
        markets.setdefault(room_type_market_key(row), []).append(str(row.get("id")))
    if len(markets) <= 1:
        return
    details = []
    for (city, state, zip_code), property_ids in sorted(markets.items()):
        label = ", ".join(part for part in (city or "unknown-city", state or "unknown-state", zip_code or "unknown-zip") if part)
        details.append(f"{label}: {', '.join(property_ids)}")
    raise ValueError(
        "Hotel all-room-types batch requires every room type to share one city/state/zip market. "
        f"Found multiple markets ({'; '.join(details)}). Re-run with --hotel-scope room-type --property-id <id>."
    )


def optional_non_negative_int(value: object | None) -> int | None:
    if value in (None, ""):
        return None
    parsed = int(value)
    if parsed < 0:
        raise ValueError("property profile integer fields cannot be negative")
    return parsed


def sql_value(value: object | None) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, int):
        return str(value)
    return sql_literal(value)


def property_profile_values(existing: dict | None, data: dict) -> dict[str, object | None]:
    existing = existing or {}
    profile: dict[str, object | None] = {}
    for column, keys in PROFILE_FIELD_KEYS.items():
        value = first_non_empty(existing.get(column), value_from_data(data, keys))
        if column in ("room_count", "capacity"):
            profile[column] = optional_non_negative_int(value)
        else:
            profile[column] = normalize_optional_text(value)
    return profile


def build_property_json(args: argparse.Namespace, existing: dict | None) -> dict:
    existing_data = dict((existing or {}).get("data") or {})
    profile = property_profile_values(existing, existing_data)
    payload = {
        **existing_data,
        "id": args.property_id,
        "propertyType": args.property_type,
        "minPrice": args.min_price,
        "maxPrice": args.max_price,
        "pricingHorizon": args.pricing_horizon,
        "planDuration": existing_data.get("planDuration") or f"{args.pricing_horizon} days",
        "priceRange": f"${format_money(args.min_price)}-${format_money(args.max_price)}",
        "source": existing_data.get("source") or "run_pricing_agent.py",
    }
    for column, json_key in PROFILE_JSON_KEYS.items():
        if profile[column] is not None:
            payload[json_key] = profile[column]
    if profile["bed"] and not payload.get("beds"):
        payload["beds"] = profile["bed"]
    if profile["bath"] and not payload.get("bathroom"):
        payload["bathroom"] = profile["bath"]
    if args.my_place:
        payload["myPlace"] = args.my_place
        payload.setdefault("airbnbUrl", args.my_place)
    if args.property_type == "airbnb":
        payload["name"] = human_readable_airbnb_property_name(
            args.property_id,
            args.my_place,
            payload,
            payload.get("name"),
        )
        payload.setdefault("displayNameSource", "airbnb_human_readable")
    return payload


def upsert_resolved_property(args: argparse.Namespace, env: dict[str, str], existing: dict | None) -> None:
    payload = build_property_json(args, existing)
    profile = property_profile_values(existing, payload)
    my_place_value = sql_literal(args.my_place) if args.my_place else "NULL"
    sql = f"""
INSERT INTO property (
  id, account_id, min_price_cents, max_price_cents, pricing_horizon, my_place,
  room_count, capacity, zip_code, county, state, city, bed, bath, other_info, data
)
VALUES (
  {sql_literal(args.property_id)},
  {sql_literal(args.account_id)}::uuid,
  {money_to_cents(args.min_price, 'min_price')},
  {money_to_cents(args.max_price, 'max_price')},
  {int(args.pricing_horizon)},
  {my_place_value},
  {sql_value(profile['room_count'])},
  {sql_value(profile['capacity'])},
  {sql_value(profile['zip_code'])},
  {sql_value(profile['county'])},
  {sql_value(profile['state'])},
  {sql_value(profile['city'])},
  {sql_value(profile['bed'])},
  {sql_value(profile['bath'])},
  {sql_value(profile['other_info'])},
  {sql_literal(json.dumps(payload, ensure_ascii=False, sort_keys=True))}::jsonb
)
ON CONFLICT (id)
DO UPDATE SET
  min_price_cents = EXCLUDED.min_price_cents,
  max_price_cents = EXCLUDED.max_price_cents,
  pricing_horizon = EXCLUDED.pricing_horizon,
  my_place = COALESCE(EXCLUDED.my_place, property.my_place),
  room_count = COALESCE(EXCLUDED.room_count, property.room_count),
  capacity = COALESCE(EXCLUDED.capacity, property.capacity),
  zip_code = COALESCE(EXCLUDED.zip_code, property.zip_code),
  county = COALESCE(EXCLUDED.county, property.county),
  state = COALESCE(EXCLUDED.state, property.state),
  city = COALESCE(EXCLUDED.city, property.city),
  bed = COALESCE(EXCLUDED.bed, property.bed),
  bath = COALESCE(EXCLUDED.bath, property.bath),
  other_info = COALESCE(EXCLUDED.other_info, property.other_info),
  data = property.data || EXCLUDED.data,
  updated_at = now()
WHERE property.account_id = EXCLUDED.account_id;
"""
    run_psql_sql(sql, env)


def resolve_runtime_inputs(args: argparse.Namespace, env: dict[str, str]) -> argparse.Namespace:
    resolved = argparse.Namespace(**vars(args))
    resolved.hotel_scope = getattr(resolved, "hotel_scope", "room-type")

    if resolved.hotel_scope == "all-room-types":
        if resolved.property_type != "hotel":
            raise ValueError("--hotel-scope all-room-types is only valid with --property-type hotel")
        rows = read_hotel_room_type_rows(env, resolved.account_id)
        if not rows:
            raise ValueError(
                "No hotel room type properties found for this account. "
                "Batch mode requires property.data.propertyType = 'Hotel Room Type'."
            )
        validate_single_hotel_market(rows)

        requested_property_id = normalize_optional_text(resolved.property_id)
        horizon_override = resolved.pricing_horizon
        room_type_properties = [build_room_type_property(row, horizon_override) for row in rows]
        room_type_ids = [item["property_id"] for item in room_type_properties]
        if requested_property_id and requested_property_id not in room_type_ids:
            raise ValueError(
                f"Requested --property-id {requested_property_id} is not one of the account's hotel room type properties: "
                f"{', '.join(room_type_ids)}"
            )

        anchor_property_id = requested_property_id or room_type_ids[0]
        anchor_row = next((row for row in rows if str(row.get("id")) == anchor_property_id), rows[0])
        resolved.property_id = anchor_property_id
        resolved.market_anchor_property_id = anchor_property_id
        resolved.summary_property_ids = room_type_ids
        resolved.room_type_properties = room_type_properties
        resolved.room_type_property_count = len(room_type_properties)
        resolved.pricing_horizon = int(horizon_override or max(item["pricing_horizon"] for item in room_type_properties))
        resolved.min_price = min(item["min_price"] for item in room_type_properties)
        resolved.max_price = max(item["max_price"] for item in room_type_properties)
        resolved.my_place = normalize_optional_text(resolved.my_place)
        (
            resolved.pricing_start_date,
            resolved.pricing_timezone,
            resolved.pricing_timezone_source,
        ) = local_pricing_start_date(anchor_row)
        return resolved

    initial_place = normalize_optional_text(resolved.my_place)
    resolved.property_id = normalize_optional_text(resolved.property_id) or generated_property_id(resolved.property_type, initial_place)

    existing = read_property_row(env, resolved.account_id, resolved.property_id)
    data = dict((existing or {}).get("data") or {})

    resolved.my_place = (
        initial_place
        or normalize_optional_text((existing or {}).get("my_place"))
        or normalize_optional_text(value_from_data(data, ("myPlace", "my_place", "airbnbUrl")))
    )

    if resolved.property_type == "airbnb" and not resolved.my_place:
        raise ValueError(
            "my_place is required for Airbnb pricing runs. Provide --my-place or save property.my_place, "
            "property.data.myPlace, or property.data.airbnbUrl before starting pricing-context."
        )

    range_min, range_max = parse_price_range(data.get("priceRange"))
    min_value = resolved.min_price or cents_to_dollars((existing or {}).get("min_price_cents")) or value_from_data(data, ("minPrice", "min_price")) or range_min
    max_value = resolved.max_price or cents_to_dollars((existing or {}).get("max_price_cents")) or value_from_data(data, ("maxPrice", "max_price")) or range_max
    horizon_value = (
        resolved.pricing_horizon
        or (existing or {}).get("pricing_horizon")
        or value_from_data(data, ("pricingHorizon", "pricing_horizon"))
        or parse_plan_duration(data.get("planDuration"))
    )

    missing = []
    if min_value in (None, ""):
        missing.append("min_price")
    if max_value in (None, ""):
        missing.append("max_price")
    if horizon_value in (None, ""):
        missing.append("pricing_horizon")
    if missing:
        raise ValueError(f"Missing required pricing workflow inputs after DB lookup: {', '.join(missing)}")

    min_cents = money_to_cents(min_value, "min_price")
    max_cents = money_to_cents(max_value, "max_price")
    horizon = int(horizon_value)
    if min_cents < 0:
        raise ValueError("min_price cannot be negative")
    if max_cents < min_cents:
        raise ValueError("max_price cannot be lower than min_price")
    if horizon < 1 or horizon > 730:
        raise ValueError("pricing_horizon must be between 1 and 730")

    resolved.min_price = cents_to_dollars(min_cents)
    resolved.max_price = cents_to_dollars(max_cents)
    resolved.pricing_horizon = horizon
    (
        resolved.pricing_start_date,
        resolved.pricing_timezone,
        resolved.pricing_timezone_source,
    ) = local_pricing_start_date(existing)
    upsert_resolved_property(resolved, env, existing)
    return resolved


def log_event(
    *,
    run_id: str,
    stage: str,
    status: str,
    message: str,
    workflow: str | None = WORKFLOW_NAME,
    skill: str | None = None,
    called_skill: str | None = None,
    caller_skill: str | None = None,
    tool: str | None = None,
    error: str | None = None,
    log_path: Path = DEFAULT_LOG_PATH,
) -> None:
    progress_logger.append_event(
        log_path,
        run_id=run_id,
        stage=stage,
        status=status,
        message=message,
        workflow=workflow,
        skill=skill,
        called_skill=called_skill,
        caller_skill=caller_skill,
        tool=tool,
        error=error[:1000] if error else None,
    )


def compact_output_tail(value: str, limit: int = 900) -> str:
    return " ".join(str(value or "").strip().split())[-limit:]


def progress_events_for_run(log_path: Path, run_id: str) -> list[dict]:
    if not log_path.exists():
        return []
    events = []
    for line in log_path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("run_id") == run_id:
            events.append(event)
    return events


def has_business_progress(log_path: Path, run_id: str) -> bool:
    return any(event.get("stage") not in LIFECYCLE_STAGES for event in progress_events_for_run(log_path, run_id))


class RuntimeSetupError(RuntimeError):
    pass


def find_executable(name: str, env: dict[str, str]) -> str | None:
    found = shutil.which(name, path=env.get("PATH"))
    if found:
        return found
    local_bin = Path.home() / ".local" / "bin" / name
    if local_bin.exists() and os.access(local_bin, os.X_OK):
        return str(local_bin)
    return None


def run_setup_command(cmd: list[str], env: dict[str, str]) -> str:
    result = subprocess.run(
        cmd,
        cwd=ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )
    if result.stdout:
        print(result.stdout, end="", flush=True)
    if result.returncode != 0:
        rendered = " ".join(cmd[:4])
        raise RuntimeSetupError(f"setup command failed ({rendered}): exit code {result.returncode}")
    return result.stdout or ""


def verify_nemoclaw_sandbox(
    *,
    openshell_bin: str,
    sandbox: str,
    env: dict[str, str],
) -> None:
    result = subprocess.run(
        [
            openshell_bin,
            "sandbox",
            "exec",
            "-n",
            sandbox,
            "--timeout",
            "10",
            "--no-tty",
            "--",
            "true",
        ],
        cwd=ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )
    if result.returncode == 0:
        return
    detail = (result.stdout or "").strip()
    hint = (
        f"NemoClaw sandbox '{sandbox}' is not reachable. "
        "Set REVNEST_NEMOCLAW_SANDBOX or pass --nemoclaw-sandbox with the active sandbox name "
        "(current local default is 'my-assistant')."
    )
    raise RuntimeSetupError(f"{hint}\n{detail}" if detail else hint)


def sync_workspace_to_sandbox(
    *,
    openshell_bin: str,
    sandbox: str,
    workdir: str,
    env: dict[str, str],
) -> None:
    remote_workdir = PurePosixPath(workdir)
    remote_parent = str(remote_workdir.parent)
    print(f"[wrapper] Syncing {ROOT} -> {remote_parent} in NemoClaw sandbox '{sandbox}'...", flush=True)
    run_setup_command(
        [openshell_bin, "sandbox", "exec", "-n", sandbox, "--", "mkdir", "-p", remote_parent],
        env,
    )
    run_setup_command([openshell_bin, "sandbox", "upload", sandbox, str(ROOT), remote_parent], env)

    dotenv_path = ROOT / ".env"
    if dotenv_path.exists():
        run_setup_command(
            [
                openshell_bin,
                "sandbox",
                "upload",
                "--no-git-ignore",
                sandbox,
                str(dotenv_path),
                str(remote_workdir / ".env"),
            ],
            env,
        )


def upload_message_to_sandbox(
    *,
    openshell_bin: str,
    sandbox: str,
    session_id: str,
    message: str,
    env: dict[str, str],
) -> str:
    safe_session = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in session_id)[:80]
    remote_path = f"/tmp/revnest-openclaw-message-{safe_session}.txt"
    local_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            prefix="revnest-openclaw-message-",
            suffix=".txt",
            delete=False,
        ) as handle:
            handle.write(message)
            local_path = Path(handle.name)
        run_setup_command([openshell_bin, "sandbox", "upload", sandbox, str(local_path), remote_path], env)
    finally:
        if local_path:
            local_path.unlink(missing_ok=True)
    return remote_path


def safe_path_slug(value: str, limit: int = 80) -> str:
    return "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in value)[:limit] or "run"


def build_agent_options(args: argparse.Namespace) -> list[str]:
    options = [
        "--local",
        "--agent",
        args.agent,
        "--session-id",
        args.session_id,
        "--thinking",
        args.thinking,
        "--timeout",
        str(args.timeout_seconds),
    ]
    if getattr(args, "model", None):
        options.extend(["--model", args.model])
    if args.verbose:
        options.extend(["--verbose", args.verbose])
    return options


def message_log_path(log_path: str) -> str:
    path = Path(log_path)
    resolved = (ROOT / path).resolve() if not path.is_absolute() else path.resolve()
    try:
        return str(resolved.relative_to(ROOT))
    except ValueError:
        return str(path)


def message_args_for_runtime(args: argparse.Namespace) -> argparse.Namespace:
    message_args = argparse.Namespace(**vars(args))
    message_args.log_path = message_log_path(args.log_path)
    return message_args


def prepare_openclaw_command(
    *,
    args: argparse.Namespace,
    message: str,
    env: dict[str, str],
    wrapper_timeout: int,
) -> tuple[list[str], dict[str, str]]:
    agent_options = build_agent_options(args)
    openclaw_bin = find_executable("openclaw", env)
    if getattr(args, "force_host_openclaw", False):
        if not openclaw_bin:
            raise RuntimeSetupError(
                "Host OpenClaw is required for this runtime mode, but no host openclaw executable was found. "
                "Use --runtime-mode nemoclaw or install/run OpenClaw on the host."
            )
        print("[wrapper] Running OpenClaw on the host runtime.", flush=True)
        return [openclaw_bin, "agent", *agent_options, "--message", message], env

    if openclaw_bin and not args.force_nemoclaw:
        return [openclaw_bin, "agent", *agent_options, "--message", message], env

    openshell_bin = find_executable("openshell", env)
    if not openshell_bin:
        return ["openclaw", "agent", *agent_options, "--message", message], env

    sandbox = args.nemoclaw_sandbox
    workdir = args.nemoclaw_workdir
    sandbox_env = dict(env)
    sandbox_env.setdefault("OPENSHELL_GATEWAY", "nemoclaw")
    print(
        f"[wrapper] Running OpenClaw inside NemoClaw sandbox '{sandbox}'.",
        flush=True,
    )
    verify_nemoclaw_sandbox(openshell_bin=openshell_bin, sandbox=sandbox, env=sandbox_env)
    if not args.no_sandbox_sync:
        sync_workspace_to_sandbox(openshell_bin=openshell_bin, sandbox=sandbox, workdir=workdir, env=sandbox_env)
    remote_message_path = upload_message_to_sandbox(
        openshell_bin=openshell_bin,
        sandbox=sandbox,
        session_id=args.session_id,
        message=message,
        env=sandbox_env,
    )
    runtime_dir = f"/tmp/revnest-openclaw-runtime-{safe_path_slug(args.session_id)}"
    runtime_config_code = (
        "import json,os,pathlib,sys;"
        "runtime=pathlib.Path(sys.argv[1]);"
        "workdir=sys.argv[2];"
        "agent_id=sys.argv[3];"
        "src=pathlib.Path('/sandbox/.openclaw/openclaw.json');"
        "data=json.loads(src.read_text());"
        "agents=data.setdefault('agents',{});"
        "defaults=agents.setdefault('defaults',{});"
        "defaults['workspace']=workdir;"
        "tools=data.setdefault('tools',{});"
        "tools['exec']={'host':'auto','security':'full','ask':'off','askFallback':'full'};"
        "approval_dir=runtime/'home'/'.openclaw';"
        "approval_dir.mkdir(parents=True,exist_ok=True);"
        "(approval_dir/'exec-approvals.json').write_text(json.dumps({'version':1,'defaults':{'security':'full','ask':'off','askFallback':'full'},'agents':{}}));"
        "(runtime/'agents'/agent_id/'agent').mkdir(parents=True,exist_ok=True);"
        "entry={'id':agent_id,'default':True,'workspace':workdir,'agentDir':str(runtime/'agents'/agent_id/'agent')};"
        "agents['list']=[entry]+[item for item in agents.get('list',[]) if item.get('id')!=agent_id];"
        "strategy=data.get('mcp',{}).get('servers',{}).get('strategy-memory');"
        "env=strategy.setdefault('env',{}) if strategy else None;"
        "strategy and strategy.update({'command':workdir+'/skills/strategy-memory/scripts/run_mcp.sh'});"
        "env is not None and env.update({'STRATEGY_MEMORY_VENV':str(runtime/'venvs'/'strategy-memory'),'STRATEGY_MEMORY_MODEL':str(runtime/'cache'/'strategy-memory'/'models'/'all-MiniLM-L6-v2')});"
        "plugins=data.get('plugins',{}).get('entries',{});"
        "plugins.get('openclaw-weixin',{}).update({'enabled':False});"
        "data.get('plugins',{}).get('installs',{}).pop('openclaw-weixin',None);"
        "discord=data.get('channels',{}).get('discord');"
        "discord and not os.environ.get('DISCORD_BOT_TOKEN') and discord.update({'enabled':False});"
        "(runtime/'openclaw.json').write_text(json.dumps(data))"
    )
    remote_script = (
        'set -eu; '
        f'runtime_dir={shlex.quote(runtime_dir)}; '
        'mkdir -p "$runtime_dir/agents"; '
        'if [ ! -e "$runtime_dir/plugin-runtime-deps" ]; then ln -s /sandbox/.openclaw/plugin-runtime-deps "$runtime_dir/plugin-runtime-deps"; fi; '
        f'python3 -c {shlex.quote(runtime_config_code)} "$runtime_dir" "$PWD" {shlex.quote(args.agent)}; '
        'export OPENCLAW_STATE_DIR="$runtime_dir"; '
        'export OPENCLAW_CONFIG_PATH="$runtime_dir/openclaw.json"; '
        'export HOME="$runtime_dir/home"; '
        'export PATH="/tmp/npm-global/bin:${PATH:-}"; '
        'export NODE_PATH="/sandbox/RevNest/Claw/node_modules:/tmp/npm-global/lib/node_modules:${NODE_PATH:-}"; '
        'msg_file=$1; shift; exec openclaw agent "$@" --message "$(cat "$msg_file")"'
    )
    return (
        [
            openshell_bin,
            "sandbox",
            "exec",
            "-n",
            sandbox,
            "--workdir",
            workdir,
            "--timeout",
            str(wrapper_timeout or 0),
            "--no-tty",
            "--",
            "/bin/bash",
            "-lc",
            remote_script,
            "openclaw-agent",
            remote_message_path,
            *agent_options,
        ],
        sandbox_env,
    )


def build_context_instructions(args: argparse.Namespace) -> str:
    if args.property_type == "hotel" and getattr(args, "hotel_scope", "room-type") == "all-room-types":
        property_ids_json = json.dumps(getattr(args, "summary_property_ids", []), ensure_ascii=False)
        return f"""Hotel all-room-types property-memory mode:
- Do not invoke the pricing-context skill and do not run agent-browser.
- Use the supplied room_type_properties_json as the canonical property memory for all room types in this batch.
- market_anchor_property_id is "{args.market_anchor_property_id}" only for shared market-data persistence and location anchoring; final writes must target each room type's own property_id.
- Before downstream tools, append progress. Prefer the `revnest-revenue-tools` MCP `log_progress` tool with run_id "{args.run_id}", workflow "{WORKFLOW_NAME}", skill "{WORKFLOW_NAME}", stage `context`, status `started`, message "Starting hotel all-room-types property memory collection", tool "postgres/property-memory", and metadata containing hotel_scope and property_ids. CLI fallback:
  python3 tools/progress_logger.py log --run-id "{args.run_id}" --workflow "{WORKFLOW_NAME}" --skill "{WORKFLOW_NAME}" --stage context --status started --message "Starting hotel all-room-types property memory collection" --tool "postgres/property-memory" --metadata-json '{{"hotel_scope":"all-room-types","property_ids":{property_ids_json}}}'
- Extract shared hotel market/location once, then preserve each room type's room_count, capacity, bed/view/amenity tier, min/max guardrails, and pricing_horizon.
- Log context completed with metadata containing hotel_scope, account_id, market_anchor_property_id, and every room type property_id.
"""

    if args.property_type == "hotel":
        return f"""Hotel property-memory mode:
- Do not invoke the pricing-context skill and do not run agent-browser.
- Load property memory for property_id "{args.property_id}" from PostgreSQL property.data and recent pricing_record rows when useful.
- Before downstream tools, append progress. Prefer the `revnest-revenue-tools` MCP `log_progress` tool with run_id "{args.run_id}", workflow "{WORKFLOW_NAME}", skill "{WORKFLOW_NAME}", stage `context`, status `started`, message "Starting hotel property memory collection", and tool "postgres/property-memory". CLI fallback:
  python3 tools/progress_logger.py log --run-id "{args.run_id}" --workflow "{WORKFLOW_NAME}" --skill "{WORKFLOW_NAME}" --stage context --status started --message "Starting hotel property memory collection" --tool "postgres/property-memory"
- Extract location/market, room type, room count, capacity, ADR/RevPAR baseline, amenities, occupancy, and guardrail notes from property memory.
- Log a context info event with substage "property_memory" and compact metadata including property_id, property_type, account_id, and location.
- Log context completed after extracting usable hotel facts.
"""

    if not args.my_place:
        raise ValueError(
            "my_place is required for Airbnb pricing-context after input resolution. "
            "Provide --my-place or save the Airbnb URL on the property before running."
        )

    return f"""Airbnb pricing-context mode with redundant browser verification:
- Invoke the pricing-context skill because property_type is airbnb.
- Use input exactly as my_place "{args.my_place}", property_id "{args.property_id}", and account_id "{args.account_id}".
- Before doing browser work, append progress. Prefer the `revnest-revenue-tools` MCP `log_progress` tool with run_id "{args.run_id}", workflow "{WORKFLOW_NAME}", skill "{WORKFLOW_NAME}", called_skill "pricing-context", stage `context`, status `started`, message "Starting Airbnb pricing browser context collection", and tool "agent-browser". CLI fallback:
  python3 tools/progress_logger.py log --run-id "{args.run_id}" --workflow "{WORKFLOW_NAME}" --skill "{WORKFLOW_NAME}" --called-skill "pricing-context" --stage context --status started --message "Starting Airbnb pricing browser context collection" --tool "agent-browser"
- Primary read: use the isolated agent-browser session "{args.run_id}":
  agent-browser --session "{args.run_id}" open "{args.my_place}"
  agent-browser --session "{args.run_id}" wait --load networkidle
  agent-browser --session "{args.run_id}" get url --json
  agent-browser --session "{args.run_id}" get title --json
  agent-browser --session "{args.run_id}" snapshot --json
- Secondary read: use OpenClaw built-in Browser with the managed openclaw profile:
  openclaw browser --browser-profile openclaw status --json
  openclaw browser --browser-profile openclaw start --json
  openclaw browser --browser-profile openclaw open "{args.my_place}" --json
  openclaw browser --browser-profile openclaw wait --load networkidle --json
  openclaw browser --browser-profile openclaw snapshot --interactive --json
- If one browser method fails or is unavailable, repeat the successful method after reload/wait and compare the two successful reads. Continue only when two reads agree on listing identity and do not conflict on capacity, city/state, bed, or bath.
- Prefer the OpenClaw managed openclaw profile. Use an existing user/Chrome browser profile only when signed-in browser state is explicitly needed.
- If my_place contains /rooms/<room_id>, every successful final URL must still contain that room id. If not, log context as failed and stop before location-based tools.
- Extract capacity, zip_code, county, state, city, bed, bath, and other_info. other_info must summarize review signals, amenities/facilities, image/photo count, listing quality, and caveats outside the structured fields.
- Write extracted fields to property columns and merge JSON keys capacity, zipCode, county, state, city, bed, bath, otherInfo, plus beds/bathroom aliases when known.
- If listing read, URL verification, extraction, or DB write fails, log context as failed and return a user-facing explanation of the failed step without continuing to market data or pricing.
- Log context completed only after redundant verification and property profile write succeed.
"""


def build_pricing_decision_loop_instructions(property_type: str, pricing_start_date: str, final_reasoning_model: str) -> str:
    normalized_type = "hotel" if property_type == "hotel" else "airbnb"
    strategy_query = (
        "hotel Dream Inn revenue management pricing strategy RMS occupancy BAR room type compression"
        if normalized_type == "hotel"
        else "Airbnb short-term rental pricing strategy seasonality booking window event pricing comp set"
    )
    return f"""Pricing decision RAG/calculator loop:
- Handle one pricing-decision substage at a time. For every substage, write one compact user-facing summary with `log_progress`, then persist the same summary with `upsert_reasoning_step` using account_id, run_id, property_id when available, stage `pricing_decision`, substage, facts, metrics, tool, sources, and confidence. Do not persist hidden chain-of-thought.
- Before strategy memory or pricing calculation, complete the supply-demand sub-loop in order:
  1. `supply_snapshot`: summarize comp count, substitute inventory, availability/sellout/compression language, and subject inventory scarcity.
  2. `demand_snapshot`: summarize events, holidays, tourism/seasonality, weather, booking window, guest segment, and demand strength.
  3. `supply_demand_synthesis`: reconcile supply vs demand into low, normal, elevated, or compressed demand.
  4. `occupancy_input`: build compact JSON for the occupancy estimator from property profile, dates, supply signals, demand signals, competitor_stats, events, holidays, weather/tourism, booking window, and historical/RMS occupancy when available.
  5. `occupancy_python_run`: run `python3 skills/pricing-decision-reasoning/scripts/occupancy_rate_estimator.py --input-json '<occupancy_input_json>'`.
  6. `occupancy_result`: persist per-date estimated_occupancy, supply_index, demand_index, compression_level, confidence, top_factors, and formula_code summary.
- Use the collected market-data bundle first. If a material supply or demand question remains unresolved, run one focused follow-up search for the current substage, summarize and persist it, then continue. Do not start another follow-up until the current substage is persisted.
- The occupancy estimator output is the required source for estimated_occupancy in the pricing calculator input. Include the full estimator JSON as `occupancy_estimator` and its date-keyed map as `estimated_occupancy`; the bundled pricing calculator rejects inputs without this provenance.
- During `pricing_decision`, first call `strategy-memory__search_strategy_memory` with query "{strategy_query}" and top_k 8. Log this as substage `strategy_memory_initial` with concise source/section citations.
- Confirm the retrieved chunks match property_type `{normalized_type}`. If no relevant strategy chunks are returned, stop before publishing and state that strategy context is unavailable.
- Build a JSON calculator input with calculation_phase `draft`, property_type, property_profile, guardrails, dates starting at {pricing_start_date}, market_signals, competitor_stats, occupancy_estimator, estimated_occupancy from occupancy_rate_estimator.py, and strategy_context.initial from the RAG chunks. Log compact facts as substage `calculator_input`.
- Run the bundled deterministic calculator from the Claw directory in draft mode:
  python3 skills/pricing-decision-reasoning/scripts/pricing_decision_calculator.py --calculation-phase draft --input-json '<calculator_input_json>'
- Use the draft calculator JSON as the source of raw_suggested_price, suggested_price_range_low/high, final_price_after_guardrails, estimated_occupancy, confidence, and guardrail warnings. Log calculator version and numeric outputs as substage `calculator_run`.
- You may run temporary ad-hoc Python only as a JSON-in/JSON-out sanity check for outliers; it must not write files or databases, call the network, or replace the bundled calculator schema.
- After the draft calendar, call `strategy-memory__search_strategy_memory` again with the same query plus the strongest draft drivers. Log this as `strategy_memory_review`.
- If the second retrieval supports the draft, set strategy_context.validation.status to `supported`, keep corrections_applied empty, and rerun the bundled calculator with calculation_phase `final`.
- If the second retrieval contradicts or does not support the draft and no correction has been used, record exactly one concise correction in corrections_applied (280 characters or fewer), update the calculator input, set strategy_context.validation.status to `corrected` only if the corrected reasoning is supported, rerun the bundled calculator with calculation_phase `final`, and log `strategy_correction`.
- If the review is still unsupported after one correction, stop before publishing and answer exactly: `I don't know. Strategy context is unavailable or insufficient.`
- Before publishing, run the stronger-model final reasoning verifier with model `{final_reasoning_model}`:
  python3 skills/pricing-decision-reasoning/scripts/final_reasoning_verifier.py --model "{final_reasoning_model}" --input-json '<compact_verification_payload_json>'
- The verifier payload must include final calculator output, strategy citations, occupancy estimator output, guardrails, and compact supply-demand summaries. Log and persist the verdict as substage `final_reasoning_verification`. If the verifier does not return status `approved`, stop before publishing and answer exactly: `I don't know. Strategy context is unavailable or insufficient.`
- Publish only final calculator output with strategy_validation_status `supported` or `corrected` and final_reasoning_verification status `approved`. Never publish `draft_unreviewed`, `unsupported`, missing strategy_memory_initial, or missing strategy_memory_review.
"""


def build_hotel_batch_message(
    args: argparse.Namespace,
    pricing_start_date: str,
    pricing_timezone: str,
    pricing_timezone_source: str,
) -> str:
    room_type_properties = getattr(args, "room_type_properties", [])
    summary_property_ids = getattr(args, "summary_property_ids", [])
    room_type_properties_json = json.dumps(room_type_properties, indent=2, ensure_ascii=False, sort_keys=True)
    summary_property_ids_json = json.dumps(summary_property_ids, ensure_ascii=False)
    market_anchor_property_id = getattr(args, "market_anchor_property_id", args.property_id)
    anchor_property = next(
        (item for item in room_type_properties if item.get("property_id") == market_anchor_property_id),
        room_type_properties[0] if room_type_properties else {},
    )
    market_address = room_type_market_address(anchor_property) or "<verified_hotel_market>"
    anchor_capacity = anchor_property.get("capacity") or "<guest capacity if known>"
    room_type_count = len(room_type_properties)

    return f"""Use the `{WORKFLOW_NAME}` skill as the primary workflow. Run the hotel all-room-types batch branch: context, per-room-type pricing-guardrails, one shared pricing-market-data fan-out, pricing-decision-reasoning, then pricing-output-publisher for each room type.

property_type: hotel
hotel_scope: all-room-types
account_id: {args.account_id}
market_anchor_property_id: {market_anchor_property_id}
summary_property_ids_json: {summary_property_ids_json}
room_type_count: {room_type_count}
pricing_horizon_shared_market: {args.pricing_horizon}
pricing_start_date: {pricing_start_date}
pricing_timezone: {pricing_timezone}
pricing_timezone_source: {pricing_timezone_source}
log_path: {args.log_path}
run_id: {args.run_id}

room_type_properties_json:
{room_type_properties_json}

{build_context_instructions(args)}

Then report `started`, `completed`, `skipped`, or `failed` before and after every major stage. Prefer the `revnest-revenue-tools` MCP `log_progress` tool with run_id "{args.run_id}", workflow "{WORKFLOW_NAME}", skill "{WORKFLOW_NAME}", optional called_skill, stage, status, message, and exact tool. CLI fallback:
python3 tools/progress_logger.py log --run-id "{args.run_id}" --workflow "{WORKFLOW_NAME}" --skill "{WORKFLOW_NAME}" --called-skill "<called skill if any>" --stage "<stage>" --status "<status>" --message "<short message>" --tool "<exact tool>"

During pricing_decision, stream compact observable decision-trace events with status "info" and --substage values: supply_snapshot, demand_snapshot, supply_demand_synthesis, occupancy_input, occupancy_python_run, occupancy_result, strategy_memory_initial, signal_table, comp_relevance, demand_assessment, property_fit, guardrail_check, calculator_input, calculator_run, strategy_memory_review, strategy_correction, final_reasoning_verification, raw_price, guardrail_application, confidence, final_calendar. Do not log hidden chain-of-thought or long deliberation.

Money unit rule: all visible prices, ADR, RevPAR, and revenue are USD dollars. If a DB or tool field ends in _cents, divide by 100 before using it in logs or explanations.

Use exact tool names, not the workflow name. For hotels do not call pricing-context. For guardrail_review use --called-skill "pricing-guardrails". For market_data_parallel use --called-skill "pricing-market-data". For pricing_decision use --called-skill "pricing-decision-reasoning". For revpar_publish use --called-skill "pricing-output-publisher".

Guardrails: run `tools/guardrail_review.py` separately for every object in room_type_properties_json. Use that room type's own property_id, min_price, max_price, capacity, room_count, bed/bath/view/amenity metadata, and market. If a room type is constrained by its guardrails, carry that caveat into the final summary for that specific property_id.

Market data: run the local shared fan-out exactly once for the hotel market. Start it with:
python3 tools/run_parallel_market_data.py --run-id "{args.run_id}" --account-id "{args.account_id}" --property-id "{market_anchor_property_id}" --summary-property-ids-json '{summary_property_ids_json}' --log-path "{args.log_path}" --property-type "hotel" --address "{market_address}" --start-date "{pricing_start_date}" --pricing-horizon "{args.pricing_horizon}" --capacity "{anchor_capacity}"

This helper owns weather, holidays, Ticketmaster events, SerpApi events, SerpApi hotel/vacation-rental comps, Tavily tourism-demand fan-out, shared `market_data_summary` writes for all room type property_ids, one `hotel_home_dashboard` update, and the combined JSON under `runs/{args.run_id}-market-data.json`. Do not run those local market tools per room type unless retrying one failed/skipped shared source.

MoodTrip hotel comps are MCP-hosted and separate from `tools/run_parallel_market_data.py`. Use the `pricing-competitors` / `moodtrip-hotel-search` skill as a separate shared hotel-market fan-out path when tools are available, and log it as `hotel_comps_moodtrip`.

Decision: produce an internal `price_calendars_by_property_id` object keyed by each room type property_id. Each value must be a guarded price calendar starting at {pricing_start_date}; its length must equal that room type's own pricing_horizon. Shared market signals can be reused, but room-type-specific current/fixed/agent prices, RMS history, room_count/scarcity, capacity, bed/suite/view/amenity tier, comp relevance weighting, and guardrails must be evaluated per room type.

{build_pricing_decision_loop_instructions("hotel", pricing_start_date, args.final_reasoning_model)}

Output: after all guarded calendars are ready, publish forecast data first by calling `tools/revpar_estimate.py write-prices` once per room type. Each call must use that room type's property_id, min_price, max_price, pricing_horizon, room_count/rooms, occupancy when available, `--price-calendar-json` for only that room type, `--run-id "{args.run_id}"`, `--trace-log-path "{args.log_path}"`, and `--conversation-id "revy-heartbeat-<property_id>"`. These hotel `property_price` rows are Revy forecast/recommendation data for the WebApp chart, not live MockHotel/PMS writes. After every room type forecast publish succeeds or fails clearly, call the `revnest-revenue-tools` MCP `review_hotel_price_adjustments` tool with account_id "{args.account_id}", run_id "{args.run_id}", the complete `price_calendars_by_property_id`, `room_type_properties_json`, start_date "{pricing_start_date}", and the final calendar end date. This approval gate compares against MockHotel current rates once and classifies pending tasks as `price_adjustment_required` when the current PMS rate is outside Revy's strategy range, or `price_review_recommended` when the current rate is inside range but the final recommendation is materially different, confidence is low, or guardrail review is needed. It sends one best-effort Discord summary through `DISCORD_WEBHOOK_URL` when configured. If Discord fails, keep the pending tasks. If the user asks to write directly to MockHotel PMS, explain that human WebApp approval is required and stage pending tasks only. If the MCP tool is unavailable, log `revpar_publish` failed/skipped with substage `mockhotel_review` and state that hotel pending approval tasks were not created. Do not call WebApp accept APIs, MockHotel write APIs, direct MockHotel database writes, create a hotel aggregate property, or write live MockHotel prices from Claw.

Use these stage ids when applicable:
context, guardrail_review, market_data_parallel, weather, holidays, events_ticketmaster, events_serpapi, hotel_comps_serpapi, hotel_comps_moodtrip, tourism_tavily, pricing_decision, revpar_publish.

Tell me which skills/tools ran, which were skipped, which room type property_ids were published, and whether the all-room-types pricing-workflow completed.
{args.message_extra or ""}"""

def build_message(args: argparse.Namespace) -> str:
    place_line = f"my_place: {args.my_place}\n" if args.my_place else ""
    pricing_start_date = getattr(args, "pricing_start_date", dt.datetime.now(dt.UTC).date().isoformat())
    pricing_timezone = getattr(args, "pricing_timezone", "UTC")
    pricing_timezone_source = getattr(args, "pricing_timezone_source", "fallback_utc")
    conversation_user_message = f"Run Revy pricing workflow for property_id {args.property_id} ({args.property_type})."
    if args.message_extra:
        conversation_user_message = f"{conversation_user_message} {args.message_extra}"
    conversation_user_message_json = json.dumps(conversation_user_message, ensure_ascii=False)
    if args.property_type == "hotel" and getattr(args, "hotel_scope", "room-type") == "all-room-types":
        return build_hotel_batch_message(args, pricing_start_date, pricing_timezone, pricing_timezone_source)
    return f"""Use the `{WORKFLOW_NAME}` skill as the primary workflow. Follow the installed skill structure exactly: context, pricing-guardrails, pricing-market-data, pricing-decision-reasoning, then pricing-output-publisher.

property_type: {args.property_type}
account_id: {args.account_id}
property_id: {args.property_id}
conversation_id: {args.conversation_id}
min_price: {args.min_price}
max_price: {args.max_price}
pricing_horizon: {args.pricing_horizon}
pricing_start_date: {pricing_start_date}
pricing_timezone: {pricing_timezone}
pricing_timezone_source: {pricing_timezone_source}
{place_line}
{build_context_instructions(args)}

Then report `started`, `completed`, `skipped`, or `failed` before and after every major stage. Prefer the `revnest-revenue-tools` MCP `log_progress` tool with run_id "{args.run_id}", workflow "{WORKFLOW_NAME}", skill "{WORKFLOW_NAME}", optional called_skill, stage, status, message, and exact tool. CLI fallback:
python3 tools/progress_logger.py log --run-id "{args.run_id}" --workflow "{WORKFLOW_NAME}" --skill "{WORKFLOW_NAME}" --called-skill "<called skill if any>" --stage "<stage>" --status "<status>" --message "<short message>" --tool "<exact tool>"

During pricing_decision, also stream observable decision-trace events with status "info" and --substage values: supply_snapshot, demand_snapshot, supply_demand_synthesis, occupancy_input, occupancy_python_run, occupancy_result, strategy_memory_initial, signal_table, comp_relevance, demand_assessment, property_fit, guardrail_check, calculator_input, calculator_run, strategy_memory_review, strategy_correction, final_reasoning_verification, raw_price, guardrail_application, confidence, final_calendar. Log compact facts/classifications/metrics only; do not log hidden chain-of-thought or long deliberation.

Money unit rule: all user-visible prices, ADR, RevPAR, and revenue must be in USD dollars. Do not report cents in progress logs or final summaries. If a tool or SQL field ends in _cents, divide by 100 before describing it. In CLI fallback progress-log --message strings, prefer "USD 800/night" instead of "$800/night" to avoid shell variable expansion.

Use exact tool names, not the workflow name. Examples: agent-browser, openclaw browser, postgres/property-memory, tools/guardrail_review.py, tools/run_parallel_market_data.py, tools/weather_tool.py, tools/get_holiday.py, tools/ticketmaster.py, tools/serpapi.py, tools/tavily.py, search_hotels, moodtrip__searchHotelsWithRates, pricing-decision-reasoning, pricing-output-publisher, tools/revpar_estimate.py. Because OpenClaw runs from the Claw directory, use `tools/...` paths, not `Claw/tools/...`.

When pricing-workflow invokes another skill, set --skill "{WORKFLOW_NAME}" and --called-skill to the invoked skill. For Airbnb context use --called-skill "pricing-context"; for hotels do not call pricing-context. For guardrail_review use --called-skill "pricing-guardrails". For market_data_parallel use --called-skill "pricing-market-data". For pricing_decision use --called-skill "pricing-decision-reasoning". For revpar_publish use --called-skill "pricing-output-publisher".

Use the `pricing-guardrails` skill immediately after context. Run tools/guardrail_review.py with min_price, max_price, capacity, bedrooms, beds, bathrooms, property type, and market when those facts are available. If property size is unavailable, log guardrail_review as skipped and continue with lower confidence. If the listing or room type appears capped too low, warn that the returned price is constrained by host guardrails and recommend reviewing a higher min/max range. Do not silently present a capped price as market-optimal.

Use the `pricing-market-data` skill after context and guardrail_review. Start local fan-out/fan-in by running:
python3 tools/run_parallel_market_data.py --run-id "{args.run_id}" --account-id "{args.account_id}" --property-id "{args.property_id}" --log-path "{args.log_path}" --property-type "{args.property_type}" --address "<verified_location_or_hotel_market>" --start-date "{pricing_start_date}" --pricing-horizon "{args.pricing_horizon}" --capacity "<guest capacity>" --bedrooms "<bedroom count>" --bathrooms "<bathroom count>"

Omit optional capacity/bedrooms/bathrooms flags only if that fact is genuinely unknown. This helper owns the local pricing-weather, pricing-holidays, pricing-events, pricing-competitors, and pricing-tourism-demand fan-out, writes child stage progress events, writes one `market_data_summary` row after each source finishes, upserts `hotel_home_dashboard` for hotel runs, and saves a combined JSON file under `runs/{args.run_id}-market-data.json`. Use that JSON, the persisted source summaries, and for hotel runs the persisted dashboard payload as the main market-data input for `pricing-decision-reasoning`. Do not call those local Python tools one-by-one unless the helper itself fails or you are explicitly retrying one failed/skipped stage.

MoodTrip hotel comps are MCP-hosted and are not launched by `tools/run_parallel_market_data.py`. Use the `pricing-competitors` / `moodtrip-hotel-search` skill as the separate MoodTrip fan-out path when tools are available. Prefer `search_hotels` when the unprefixed wrapper exists; otherwise use `moodtrip__searchHotelsWithRates` when that is what OpenClaw exposes. Log this as stage `hotel_comps_moodtrip` and keep MoodTrip separate from SerpApi hotel/vacation-rental results.

Paid Airbnb-specific scraping is disabled for cost control. Do not run, skip, or report any paid Airbnb scraping stage.

SerpApi hotel/vacation-rental comps and MoodTrip hotel comps are complementary. Run hotel_comps_serpapi and hotel_comps_moodtrip when both are available; do not skip one simply because the other succeeded.

Tavily tourism demand must be tied to the verified destination market. Ignore unrelated country-level or source-market travel reports unless they explicitly affect lodging demand in that destination.

Use `pricing-decision-reasoning` only after context, guardrails, and market-data fan-in. Its internal price_calendar must use date values starting at pricing_start_date ({pricing_start_date}) for pricing_horizon ({args.pricing_horizon}) night(s), with prices in USD dollars.

{build_pricing_decision_loop_instructions(args.property_type, pricing_start_date, args.final_reasoning_model)}

Use `pricing-output-publisher` after the guarded price_calendar is ready. For Airbnb, draft the final concise user-facing explanation before publishing, then call tools/revpar_estimate.py with account_id, property_id, min_price, max_price, pricing_horizon, inline --price-calendar-json, rooms/room_count, occupancy when available, property context JSON when useful, --run-id "{args.run_id}", --conversation-id "{args.conversation_id}", --trace-log-path "{args.log_path}", --user-message {conversation_user_message_json}, --conversation-title, --conversation-summary, and --final-message containing that exact final explanation. This saves Airbnb suggested prices directly to PostgreSQL `property_price` and the explanation/progress trace to `revy_conversation`; return the same explanation to the user after the write finishes. For hotel single-room-type runs, publish the forecast row to `property_price` and `revy_conversation` first, include user_message {conversation_user_message_json} in the saved conversation when using the MCP publisher or `--user-message` when using tools/revpar_estimate.py, then call the `revnest-revenue-tools` MCP `review_hotel_price_adjustments` tool with `price_calendars_by_property_id` shaped as `{{property_id: price_calendar}}`, room type metadata, and the calendar date range. The hotel approval gate classifies pending tasks as `price_adjustment_required` when the current PMS rate is outside Revy's strategy range, or `price_review_recommended` when the current rate is inside range but the final recommendation is materially different, confidence is low, or guardrail review is needed. It sends one best-effort Discord summary when configured and never writes live MockHotel prices directly from Claw. If a prompt asks to write to MockHotel PMS, do not call WebApp accept APIs, MockHotel write APIs, or direct MockHotel database writes; create pending tasks and tell the user WebApp human approval is required.

min_price and max_price are guardrails, not current price. If no current price is explicitly supplied, visible on the verified listing page, or read from the database, keep current_price and change_pct unknown/null and do not report current RevPAR.

Use these stage ids when applicable:
context, guardrail_review, market_data_parallel, weather, holidays, events_ticketmaster, events_serpapi, hotel_comps_serpapi, hotel_comps_moodtrip, tourism_tavily, pricing_decision, revpar_publish.

Tell me which skills/tools ran, which were skipped, and whether the pricing-workflow completed.
{args.message_extra or ""}"""

def reader_thread(pipe, output_queue: queue.Queue[str]) -> None:
    try:
        for line in iter(pipe.readline, ""):
            output_queue.put(line)
    finally:
        pipe.close()


def run_openclaw(
    cmd: list[str],
    env: dict[str, str],
    timeout_seconds: int,
    idle_timeout_seconds: int,
    log_path: Path,
) -> tuple[int, str, str | None]:
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=ROOT,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
    except FileNotFoundError as exc:
        return 127, str(exc), None

    output_queue: queue.Queue[str] = queue.Queue()
    thread = threading.Thread(target=reader_thread, args=(proc.stdout, output_queue), daemon=True)
    thread.start()

    started = time.monotonic()
    last_progress_at = started
    last_progress_size = log_path.stat().st_size if log_path.exists() else 0
    chunks: list[str] = []
    stop_reason = None

    while True:
        try:
            line = output_queue.get(timeout=0.2)
        except queue.Empty:
            line = None

        if line is not None:
            print(line, end="", flush=True)
            chunks.append(line)

        if proc.poll() is not None:
            break

        current_progress_size = log_path.stat().st_size if log_path.exists() else 0
        if current_progress_size != last_progress_size:
            last_progress_size = current_progress_size
            last_progress_at = time.monotonic()

        if timeout_seconds and time.monotonic() - started > timeout_seconds:
            stop_reason = "wrapper timeout"
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=10)
            break

        if idle_timeout_seconds and time.monotonic() - last_progress_at > idle_timeout_seconds:
            stop_reason = f"no Revy progress events for {idle_timeout_seconds} seconds"
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=10)
            break

    while True:
        try:
            line = output_queue.get_nowait()
        except queue.Empty:
            break
        print(line, end="", flush=True)
        chunks.append(line)

    thread.join(timeout=1)
    return proc.returncode if proc.returncode is not None else 124, "".join(chunks[-400:]), stop_reason


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run OpenClaw pricing workflow with progress JSONL events")
    parser.add_argument("--account-id", required=True, help="RevNest account id")
    parser.add_argument("--property-type", required=True, choices=["airbnb", "hotel"], help="Pricing subject type: airbnb or hotel")
    parser.add_argument(
        "--hotel-scope",
        choices=["room-type", "all-room-types"],
        default="room-type",
        help="Hotel pricing scope. room-type preserves the legacy single-property path; all-room-types batches every Hotel Room Type property for the account.",
    )
    parser.add_argument("--property-id", help="Existing or generated RevNest property id for write-back")
    parser.add_argument("--min-price", help="Minimum nightly price")
    parser.add_argument("--max-price", help="Maximum nightly price")
    parser.add_argument("--pricing-horizon", type=int, help="Number of future nights to price")
    parser.add_argument("--my-place", help="Optional Airbnb listing URL or place reference")
    parser.add_argument("--agent", default=DEFAULT_OPENCLAW_AGENT, help="OpenClaw agent id")
    parser.add_argument("--model", help="Optional OpenClaw model override for the main pricing workflow run")
    parser.add_argument("--session-id", default=None, help="OpenClaw session id")
    parser.add_argument("--run-id", default=None, help="Progress run id; defaults to session id")
    parser.add_argument("--conversation-id", default=None, help="Stable revy_conversation id for this pricing conversation")
    parser.add_argument("--thinking", default="medium", help="OpenClaw thinking level")
    parser.add_argument("--verbose", choices=["on", "off"], help="Pass through OpenClaw verbose setting")
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=900,
        help="OpenClaw agent timeout in seconds; the wrapper allows a short grace period",
    )
    parser.add_argument(
        "--idle-retry-seconds",
        type=int,
        default=DEFAULT_OPENCLAW_IDLE_RETRY_SECONDS,
        help="Retry the OpenClaw attempt when it writes no Revy progress events for this many seconds",
    )
    parser.add_argument(
        "--max-attempts",
        type=int,
        default=DEFAULT_OPENCLAW_MAX_ATTEMPTS,
        help="Maximum OpenClaw attempts before reporting failure",
    )
    parser.add_argument("--clear-log", action="store_true", help="Clear the progress log before starting")
    parser.add_argument("--preserve-log", action="store_true", help="Deprecated alias for the default behavior")
    parser.add_argument("--log-path", default=str(DEFAULT_LOG_PATH), help="Progress JSONL file path")
    parser.add_argument("--message-extra", default="", help="Extra text appended to the OpenClaw message")
    parser.add_argument(
        "--final-reasoning-model",
        default=os.environ.get("REVNEST_FINAL_REASONING_MODEL", "nemotron-3-super:latest"),
        help="Local model used by the final compact reasoning verifier before publish",
    )
    parser.add_argument(
        "--runtime-mode",
        choices=["split-demo", "auto", "host-openclaw", "nemoclaw"],
        default=os.environ.get("REVNEST_RUNTIME_MODE", DEFAULT_RUNTIME_MODE),
        help=(
            "Execution runtime. split-demo runs hotel through NemoClaw and Airbnb through host OpenClaw; "
            "auto keeps legacy host-first fallback behavior."
        ),
    )
    parser.add_argument(
        "--nemoclaw-sandbox",
        default=os.environ.get("REVNEST_NEMOCLAW_SANDBOX", DEFAULT_NEMOCLAW_SANDBOX),
        help=f"NemoClaw sandbox used when host OpenClaw is unavailable (default: {DEFAULT_NEMOCLAW_SANDBOX})",
    )
    parser.add_argument(
        "--nemoclaw-workdir",
        default=os.environ.get("REVNEST_NEMOCLAW_WORKDIR", DEFAULT_NEMOCLAW_WORKDIR),
        help="Workspace path inside the NemoClaw sandbox",
    )
    parser.add_argument(
        "--no-sandbox-sync",
        action="store_true",
        help="Skip syncing the local RevNest/Claw workspace into NemoClaw before fallback execution",
    )
    parser.add_argument(
        "--force-nemoclaw",
        action="store_true",
        help="Run through NemoClaw even if a host openclaw executable exists",
    )
    parser.add_argument(
        "--force-host-openclaw",
        action="store_true",
        help="Run through host OpenClaw and fail if host OpenClaw is unavailable",
    )
    return parser


def apply_runtime_mode(args: argparse.Namespace) -> argparse.Namespace:
    if args.runtime_mode == "nemoclaw":
        args.force_nemoclaw = True
        args.force_host_openclaw = False
    elif args.runtime_mode == "host-openclaw":
        args.force_nemoclaw = False
        args.force_host_openclaw = True
    elif args.runtime_mode == "split-demo":
        if args.property_type == "hotel":
            args.force_nemoclaw = True
            args.force_host_openclaw = False
        elif args.property_type == "airbnb":
            args.force_nemoclaw = False
            args.force_host_openclaw = True
    if args.force_nemoclaw and args.force_host_openclaw:
        raise ValueError("--force-nemoclaw and --force-host-openclaw cannot both be set")
    return args


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        args = apply_runtime_mode(args)
    except ValueError as exc:
        print(f"[wrapper] {exc}", flush=True)
        return 2

    if not args.session_id:
        args.session_id = f"pricing-workflow-{timestamp_slug()}"
    if not args.run_id:
        args.run_id = args.session_id
    if not args.conversation_id:
        args.conversation_id = f"pricing-final-{args.run_id}"

    log_path = Path(args.log_path)
    if args.clear_log and not args.preserve_log:
        progress_logger.clear_log(log_path)

    log_event(
        run_id=args.run_id,
        stage="agent_start",
        status="started",
        message="OpenClaw pricing workflow agent started",
        skill=WORKFLOW_NAME,
        tool="openclaw agent",
        log_path=log_path,
    )

    env = load_dotenv(os.environ)
    env["REVNEST_PROGRESS_WRAPPER"] = "1"
    wrapper_timeout = args.timeout_seconds + 30 if args.timeout_seconds else 0
    max_attempts = max(1, int(args.max_attempts or 1))
    idle_retry_seconds = max(0, int(args.idle_retry_seconds or 0))
    returncode = 127
    output_tail = ""
    stop_reason = None
    empty_success = False
    try:
        args = resolve_runtime_inputs(args, env)
        message = build_message(message_args_for_runtime(args))
        cmd, cmd_env = prepare_openclaw_command(
            args=args,
            message=message,
            env=env,
            wrapper_timeout=wrapper_timeout,
        )
    except (RuntimeSetupError, RuntimeError, ValueError) as exc:
        print(f"[wrapper] {exc}", flush=True)
        returncode, output_tail = 127, str(exc)
        stop_reason = None
    else:
        for attempt in range(1, max_attempts + 1):
            if attempt > 1:
                log_event(
                    run_id=args.run_id,
                    stage="wrapper_retry",
                    status="started",
                    message=f"Retrying OpenClaw pricing workflow attempt {attempt}/{max_attempts}.",
                    skill=WORKFLOW_NAME,
                    tool="run_pricing_agent.py",
                    log_path=log_path,
                )
            returncode, output_tail, stop_reason = run_openclaw(
                cmd,
                cmd_env,
                wrapper_timeout,
                idle_retry_seconds,
                log_path,
            )
            lower_tail = output_tail.lower()
            model_idle_timeout = "model idle timeout" in lower_tail
            request_timeout = "request timed out before a response was generated" in lower_tail
            request_timeout = request_timeout or "increase `agents.defaults.timeoutseconds`" in lower_tail
            empty_success = returncode == 0 and not has_business_progress(log_path, args.run_id)
            should_retry = bool(stop_reason) or model_idle_timeout or request_timeout or empty_success
            if not should_retry or attempt >= max_attempts:
                break
            reason = stop_reason or ("empty successful run: no workflow progress was written" if empty_success else "OpenClaw timeout")
            log_event(
                run_id=args.run_id,
                stage="wrapper_retry",
                status="info",
                message=f"OpenClaw attempt {attempt}/{max_attempts} did not produce usable progress; retrying.",
                skill=WORKFLOW_NAME,
                tool="run_pricing_agent.py",
                error=reason,
                log_path=log_path,
            )

    lower_tail = output_tail.lower()
    model_idle_timeout = "model idle timeout" in lower_tail
    request_timeout = "request timed out before a response was generated" in lower_tail
    request_timeout = request_timeout or "increase `agents.defaults.timeoutseconds`" in lower_tail
    if stop_reason:
        log_event(
            run_id=args.run_id,
            stage="agent_finish",
            status="failed",
            message="OpenClaw pricing workflow agent did not complete",
            skill=WORKFLOW_NAME,
            tool="openclaw agent",
            error=stop_reason,
            log_path=log_path,
        )
        return 124

    empty_success = returncode == 0 and not has_business_progress(log_path, args.run_id)
    if returncode == 0 and not model_idle_timeout and not request_timeout and not empty_success:
        log_event(
            run_id=args.run_id,
            stage="agent_finish",
            status="completed",
            message="OpenClaw pricing workflow agent finished",
            skill=WORKFLOW_NAME,
            tool="openclaw agent",
            log_path=log_path,
        )
        return 0

    if model_idle_timeout:
        error = "model idle timeout"
    elif request_timeout:
        error = "openclaw request timeout"
    elif empty_success:
        error = "OpenClaw returned success but wrote no workflow progress, pending tasks, or conversation updates"
    else:
        error = f"exit code {returncode}"
    compact_tail = compact_output_tail(output_tail)
    if compact_tail:
        error = f"{error}: {compact_tail}"
    log_event(
        run_id=args.run_id,
        stage="agent_finish",
        status="failed",
        message="OpenClaw pricing workflow agent did not complete",
        skill=WORKFLOW_NAME,
        tool="openclaw agent",
        error=error,
        log_path=log_path,
    )
    return returncode or 1


if __name__ == "__main__":
    raise SystemExit(main())
