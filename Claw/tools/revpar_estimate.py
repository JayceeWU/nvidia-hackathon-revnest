#!/usr/bin/env python3
"""
RevNest RevPAR estimate and price write-back tool.

Provides:
- RevPAR estimate from a JSON price calendar
- PostgreSQL upsert into property_price for predicted agent prices

The database URL is read from CLAW_DATABASE_URL, DATABASE_URL, or --database-url.
Writing uses local psql when available, otherwise it can fall back to the
project's Docker Compose PostgreSQL service.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import urllib.parse
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / ".env"
DATA_DIR = ROOT / "data"
COMPOSE_FILE = DATA_DIR / "docker-compose.yml"
DEFAULT_DATABASE_URL = "postgres://postgres:postgres@localhost:55434/dev"
DEFAULT_ACCOUNT_ID = "00000000-0000-0000-0000-000000000102"
DEFAULT_ACCOUNT_EMAIL = "airbnb@revnest.ai"
DEFAULT_ACCOUNT_NAME = "Airbnb Host"
MONEY_CURRENCY = "USD"
MONEY_UNIT = "dollars"
PUBLISHABLE_STRATEGY_STATUSES = {"supported", "corrected"}


def emit(payload: dict, exit_code: int = 0) -> None:
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


def parse_iso_date(value: str, field_name: str = "date") -> str:
    try:
        return dt.date.fromisoformat(str(value)).isoformat()
    except ValueError as exc:
        raise ValueError(f"{field_name} must use YYYY-MM-DD format") from exc


def parse_rate(value: object, default: float) -> float:
    if value is None or value == "":
        return default
    if isinstance(value, str):
        value = value.strip().rstrip("%")
    rate = float(value)
    if rate > 1:
        rate = rate / 100
    return max(0.0, min(rate, 1.0))


def is_cents_field(field_name: str) -> bool:
    normalized = field_name.lower()
    return normalized.endswith("_cents") or normalized.endswith("cents")


def money_to_cents(value: object, field_name: str) -> int:
    if value is None or value == "":
        raise ValueError(f"{field_name} is required")
    if isinstance(value, int):
        if is_cents_field(field_name):
            return value
        return int(round(value * 100))
    if isinstance(value, float):
        multiplier = 1 if is_cents_field(field_name) else 100
        return int(round(value * multiplier))
    text = str(value).strip()
    text = re.sub(r"[$,\s]", "", text)
    if not text:
        raise ValueError(f"{field_name} is empty")
    multiplier = 1 if is_cents_field(field_name) else 100
    return int(round(float(text) * multiplier))


def cents_to_dollars(value: int | float | None) -> float | None:
    if value is None:
        return None
    return round(float(value) / 100, 2)


def load_price_calendar(args: argparse.Namespace) -> list[dict]:
    if args.price_calendar_json:
        payload = json.loads(args.price_calendar_json)
    else:
        raise ValueError("Pass --price-calendar-json")

    if isinstance(payload, dict):
        for key in ("price_calendar", "calendar", "prices", "daily"):
            if isinstance(payload.get(key), list):
                payload = payload[key]
                break

    if not isinstance(payload, list):
        raise ValueError("Price calendar must be a JSON list or an object with price_calendar/calendar/prices/daily")
    if not payload:
        raise ValueError("Price calendar is empty")
    if not all(isinstance(item, dict) for item in payload):
        raise ValueError("Each price calendar item must be an object")
    return payload


def value_from_keys(row: dict, keys: tuple[str, ...]) -> object | None:
    for key in keys:
        if key in row and row[key] not in (None, ""):
            return row[key]
    return None


def has_strategy_evidence(value: object) -> bool:
    if isinstance(value, list):
        return any(isinstance(item, dict) and item for item in value)
    if isinstance(value, dict):
        chunks = value.get("chunks")
        if isinstance(chunks, list):
            return has_strategy_evidence(chunks)
        return bool(value)
    return False


def normalized_corrections(value: object) -> list[str]:
    if value in (None, ""):
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value).strip()] if str(value).strip() else []


def validate_strategy_guarded_calendar(calendar: list[dict]) -> None:
    errors: list[str] = []
    for index, row in enumerate(calendar):
        row_label = row.get("date") or row.get("price_date") or f"index {index}"
        status = str(row.get("strategy_validation_status") or "").strip().lower()
        corrections = normalized_corrections(row.get("corrections_applied"))

        if not has_strategy_evidence(row.get("strategy_memory_initial")):
            errors.append(f"{row_label}: missing strategy_memory_initial")
        if not has_strategy_evidence(row.get("strategy_memory_review")):
            errors.append(f"{row_label}: missing strategy_memory_review")
        if status not in PUBLISHABLE_STRATEGY_STATUSES:
            errors.append(f"{row_label}: strategy_validation_status must be supported or corrected")
        if len(corrections) > 1:
            errors.append(f"{row_label}: at most one strategy correction is allowed")
        if any(len(item) > 280 for item in corrections):
            errors.append(f"{row_label}: strategy correction must be 280 characters or fewer")
        if status == "corrected" and len(corrections) != 1:
            errors.append(f"{row_label}: corrected status requires exactly one correction")
        if status == "supported" and corrections:
            errors.append(f"{row_label}: supported status must not include corrections_applied")

    if errors:
        detail = "; ".join(errors[:8])
        if len(errors) > 8:
            detail += f"; plus {len(errors) - 8} more"
        raise ValueError(f"Strategy validation publish gate failed: {detail}")


def final_price_cents(row: dict) -> int:
    value = value_from_keys(
        row,
        (
            "final_price_after_guardrails",
            "final_price",
            "suggested_price",
            "agent_price",
            "price",
            "agent_price_cents",
        ),
    )
    field = "agent_price_cents" if "agent_price_cents" in row and value == row.get("agent_price_cents") else "final_price"
    return money_to_cents(value, field)


def current_price_value(row: dict) -> object | None:
    return value_from_keys(row, ("current_price", "fixed_price", "base_price", "fixed_price_cents"))


def current_price_cents(row: dict, fallback_cents: int) -> int:
    value = current_price_value(row)
    if value is None:
        return fallback_cents
    field = "fixed_price_cents" if "fixed_price_cents" in row and value == row.get("fixed_price_cents") else "current_price"
    return money_to_cents(value, field)


def normalize_price_calendar(calendar: list[dict], occupancy_rate: float) -> list[dict]:
    rows = []
    for item in calendar:
        date_value = parse_iso_date(value_from_keys(item, ("date", "price_date")), "date")
        agent_cents = final_price_cents(item)
        current_available = current_price_value(item) is not None
        fixed_cents = current_price_cents(item, agent_cents)
        row_occupancy = parse_rate(
            value_from_keys(item, ("occupancy_rate", "expected_occupancy", "occupancy")),
            occupancy_rate,
        )
        rows.append(
            {
                "date": date_value,
                "fixed_price_cents": fixed_cents,
                "agent_price_cents": agent_cents,
                "current_price_available": current_available,
                "occupancy_rate": row_occupancy,
            }
        )
    return rows


def estimate_revpar(rows: list[dict], rooms: int) -> dict:
    available_room_nights = rooms * len(rows)
    occupied_room_nights = sum(rooms * row["occupancy_rate"] for row in rows)
    agent_revenue_cents = sum(row["agent_price_cents"] * rooms * row["occupancy_rate"] for row in rows)
    current_price_known_count = sum(1 for row in rows if row.get("current_price_available"))
    has_complete_current_baseline = current_price_known_count == len(rows)
    fixed_revenue_cents = (
        sum(row["fixed_price_cents"] * rooms * row["occupancy_rate"] for row in rows)
        if has_complete_current_baseline
        else None
    )

    agent_adr_cents = agent_revenue_cents / occupied_room_nights if occupied_room_nights else 0
    fixed_adr_cents = (
        fixed_revenue_cents / occupied_room_nights
        if fixed_revenue_cents is not None and occupied_room_nights
        else None
    )
    agent_revpar_cents = agent_revenue_cents / available_room_nights if available_room_nights else 0
    fixed_revpar_cents = (
        fixed_revenue_cents / available_room_nights
        if fixed_revenue_cents is not None and available_room_nights
        else None
    )
    lift_cents = agent_revpar_cents - fixed_revpar_cents if fixed_revpar_cents is not None else None
    lift_pct = (lift_cents / fixed_revpar_cents * 100) if lift_cents is not None and fixed_revpar_cents else None

    agent_adr = cents_to_dollars(agent_adr_cents)
    fixed_adr = cents_to_dollars(fixed_adr_cents)
    agent_revpar = cents_to_dollars(agent_revpar_cents)
    fixed_revpar = cents_to_dollars(fixed_revpar_cents)
    revpar_lift = cents_to_dollars(lift_cents)
    expected_agent_revenue = cents_to_dollars(agent_revenue_cents)
    expected_current_revenue = cents_to_dollars(fixed_revenue_cents)

    return {
        "currency": MONEY_CURRENCY,
        "money_unit": MONEY_UNIT,
        "day_count": len(rows),
        "rooms": rooms,
        "available_room_nights": available_room_nights,
        "expected_occupied_room_nights": round(occupied_room_nights, 2),
        "average_occupancy_rate": round(occupied_room_nights / available_room_nights, 4) if available_room_nights else 0,
        "current_price_available": has_complete_current_baseline,
        "current_price_known_rows": current_price_known_count,
        "current_price_note": (
            "Current-price baseline was provided for all dates."
            if has_complete_current_baseline
            else "Current-price baseline unavailable for at least one date; current ADR/RevPAR/lift are not reported."
        ),
        "agent_adr": agent_adr,
        "agent_adr_usd": agent_adr,
        "current_adr": fixed_adr,
        "current_adr_usd": fixed_adr,
        "agent_revpar": agent_revpar,
        "agent_revpar_usd": agent_revpar,
        "current_revpar": fixed_revpar,
        "current_revpar_usd": fixed_revpar,
        "revpar_lift": revpar_lift,
        "revpar_lift_usd": revpar_lift,
        "revpar_lift_pct": round(lift_pct, 2) if lift_pct is not None else None,
        "expected_agent_revenue": expected_agent_revenue,
        "expected_agent_revenue_usd": expected_agent_revenue,
        "expected_current_revenue": expected_current_revenue,
        "expected_current_revenue_usd": expected_current_revenue,
    }


def sql_literal(value: object) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def sql_value(value: object | None) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, int):
        return str(value)
    return sql_literal(value)


def load_property_data_payload(args: argparse.Namespace) -> dict[str, Any]:
    if not args.property_data_json:
        return {}
    payload = json.loads(args.property_data_json)
    if not isinstance(payload, dict):
        raise ValueError("--property-data-json must be a JSON object")
    return payload


def property_value_from_keys(payload: dict[str, Any], keys: tuple[str, ...]) -> tuple[object | None, str | None]:
    for key in keys:
        if key in payload and payload[key] not in (None, ""):
            return payload[key], key
    return None, None


PROFILE_FIELD_KEYS = {
    "room_count": ("roomCount", "room_count"),
    "capacity": ("capacity",),
    "zip_code": ("zipCode", "zip_code"),
    "county": ("county",),
    "state": ("state",),
    "city": ("city",),
    "bed": ("bed", "beds"),
    "bath": ("bath", "bathroom"),
    "other_info": ("otherInfo", "other_info", "additionalInfo"),
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


def normalize_optional_text(value: object | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


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


def human_readable_airbnb_property_name(args: argparse.Namespace, payload: dict[str, Any], current_name: object | None = None) -> str:
    property_id = args.property_id
    my_place = normalize_optional_text(first_non_empty(payload.get("myPlace"), payload.get("my_place"), payload.get("airbnbUrl")))
    room_id = airbnb_room_id(my_place) or (property_id.removeprefix("airbnb-") if property_id.startswith("airbnb-") else None)
    current = normalize_optional_text(current_name or payload.get("name"))
    if current and not looks_like_placeholder_airbnb_name(current, property_id, room_id):
        return current

    title = clean_airbnb_title(first_non_empty(payload.get("listingTitle"), payload.get("listing_title"), payload.get("title")))
    fallback_city, fallback_state = city_state_from_location(args.location)
    city = normalize_optional_text(first_non_empty(payload.get("city"), fallback_city))
    state = normalize_optional_text(first_non_empty(payload.get("state"), fallback_state))
    location = normalize_optional_text(
        first_non_empty(
            payload.get("neighborhood"),
            f"{city}, {state}" if city and state else None,
            city,
            payload.get("location"),
            args.location,
        )
    )
    listing_type = normalize_optional_text(
        first_non_empty(
            payload.get("listingType"),
            payload.get("listing_type"),
            payload.get("roomType"),
            payload.get("room_type"),
            payload.get("spaceType"),
            payload.get("space_type"),
            payload.get("propertyCategory"),
            payload.get("property_category"),
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


def optional_non_negative_int(value: object | None) -> int | None:
    if value in (None, ""):
        return None
    parsed = int(value)
    if parsed < 0:
        raise ValueError("property profile integer fields cannot be negative")
    return parsed


def city_state_from_location(location: str | None) -> tuple[str | None, str | None]:
    text = normalize_optional_text(location)
    if not text or "," not in text:
        return None, None
    city, state = [part.strip() for part in text.split(",", 1)]
    return city or None, state or None


def property_profile_values(args: argparse.Namespace, payload: dict[str, Any]) -> dict[str, object | None]:
    profile: dict[str, object | None] = {}
    fallback_city, fallback_state = city_state_from_location(args.location)
    for column, keys in PROFILE_FIELD_KEYS.items():
        value, _ = property_value_from_keys(payload, keys)
        if column == "room_count" and value in (None, ""):
            value = args.rooms
        if column == "city" and value in (None, ""):
            value = fallback_city
        if column == "state" and value in (None, ""):
            value = fallback_state
        if column in ("room_count", "capacity"):
            profile[column] = optional_non_negative_int(value)
        else:
            profile[column] = normalize_optional_text(value)
    return profile


def display_price_from_cents(cents: int) -> int | float:
    dollars = cents_to_dollars(cents)
    if dollars is None:
        return 0
    return int(dollars) if float(dollars).is_integer() else dollars


def format_display_price(value: int | float) -> str:
    return str(value) if isinstance(value, int) or float(value).is_integer() else f"{value:.2f}"


def resolve_property_pricing(
    args: argparse.Namespace,
    payload: dict[str, Any],
    rows: list[dict],
) -> dict[str, int]:
    min_value, min_key = property_value_from_keys(
        payload,
        ("minPrice", "min_price", "minPriceUsd", "min_price_usd", "minPriceCents", "min_price_cents"),
    )
    max_value, max_key = property_value_from_keys(
        payload,
        ("maxPrice", "max_price", "maxPriceUsd", "max_price_usd", "maxPriceCents", "max_price_cents"),
    )

    min_price_cents = (
        money_to_cents(args.min_price, "min_price")
        if args.min_price is not None
        else money_to_cents(min_value, min_key or "min_price")
        if min_value is not None
        else None
    )
    max_price_cents = (
        money_to_cents(args.max_price, "max_price")
        if args.max_price is not None
        else money_to_cents(max_value, max_key or "max_price")
        if max_value is not None
        else None
    )

    calendar_prices = [int(row["agent_price_cents"]) for row in rows] + [int(row["fixed_price_cents"]) for row in rows]
    if min_price_cents is None:
        min_price_cents = min(calendar_prices)
    if max_price_cents is None:
        max_price_cents = max(calendar_prices)

    horizon_value, _ = property_value_from_keys(payload, ("pricingHorizon", "pricing_horizon"))
    pricing_horizon = args.pricing_horizon if args.pricing_horizon is not None else horizon_value
    if pricing_horizon in (None, ""):
        pricing_horizon = len({row["date"] for row in rows})
    pricing_horizon = int(pricing_horizon)

    if min_price_cents < 0:
        raise ValueError("min_price cannot be negative")
    if max_price_cents < min_price_cents:
        raise ValueError("max_price cannot be lower than min_price")
    if pricing_horizon < 1 or pricing_horizon > 730:
        raise ValueError("pricing_horizon must be between 1 and 730")

    return {
        "min_price_cents": min_price_cents,
        "max_price_cents": max_price_cents,
        "pricing_horizon": pricing_horizon,
    }


def build_property_data(
    args: argparse.Namespace,
    rows: list[dict],
    summary: dict[str, Any],
    payload: dict[str, Any],
    pricing: dict[str, int],
) -> dict[str, Any]:
    payload = dict(payload)
    first_row = rows[0] if rows else {}
    min_price = display_price_from_cents(pricing["min_price_cents"])
    max_price = display_price_from_cents(pricing["max_price_cents"])
    payload.setdefault("id", args.property_id)
    payload.setdefault("propertyType", args.property_type)
    payload.setdefault("roomCount", args.rooms)
    if args.location:
        payload.setdefault("location", args.location)
    if args.property_type == "airbnb":
        payload["name"] = human_readable_airbnb_property_name(args, payload, args.property_name)
        payload.setdefault("displayNameSource", "airbnb_human_readable")
    else:
        payload.setdefault("name", args.property_name or args.property_id)
    profile = property_profile_values(args, payload)
    for column, json_key in PROFILE_JSON_KEYS.items():
        if profile[column] is not None:
            payload.setdefault(json_key, profile[column])
    if profile["bed"] and not payload.get("beds"):
        payload["beds"] = profile["bed"]
    if profile["bath"] and not payload.get("bathroom"):
        payload["bathroom"] = profile["bath"]
    if first_row and first_row.get("current_price_available"):
        payload.setdefault("fixedPrice", cents_to_dollars(first_row.get("fixed_price_cents")))
    payload.setdefault("agentAdr", summary.get("agent_adr"))
    payload.setdefault("occupancy", f"{round(summary.get('average_occupancy_rate', 0) * 100)}%")
    payload["minPrice"] = min_price
    payload["maxPrice"] = max_price
    payload["pricingHorizon"] = pricing["pricing_horizon"]
    payload.setdefault("planDuration", f"{pricing['pricing_horizon']} days")
    payload.setdefault("priceRange", f"${format_display_price(min_price)}-${format_display_price(max_price)}")
    payload.setdefault("pricingConnection", "openclaw-agent")
    payload.setdefault("source", "revpar_estimate.write-prices")
    return payload


def build_ensure_property_sql(args: argparse.Namespace, rows: list[dict], summary: dict[str, Any]) -> str:
    account_id = args.account_id or DEFAULT_ACCOUNT_ID
    account_email = args.account_email or DEFAULT_ACCOUNT_EMAIL
    account_name = args.account_name or DEFAULT_ACCOUNT_NAME
    account_type = args.account_type or "airbnb"
    payload = load_property_data_payload(args)
    pricing = resolve_property_pricing(args, payload, rows)
    property_data = build_property_data(args, rows, summary, payload, pricing)
    profile = property_profile_values(args, property_data)
    property_json = json.dumps(property_data, ensure_ascii=False, sort_keys=True)
    return (
        "INSERT INTO account (id, email, password_hash, name, role, account_type)\n"
        "VALUES (\n"
        f"  {sql_literal(account_id)}::uuid,\n"
        f"  {sql_literal(account_email)},\n"
        "  'agent-managed-disabled',\n"
        f"  {sql_literal(account_name)},\n"
        "  'host',\n"
        f"  {sql_literal(account_type)}\n"
        ")\n"
        "ON CONFLICT (id) DO NOTHING;\n\n"
        "INSERT INTO property (\n"
        "  id, account_id, min_price_cents, max_price_cents, pricing_horizon,\n"
        "  room_count, capacity, zip_code, county, state, city, bed, bath, other_info, data\n"
        ")\n"
        "VALUES (\n"
        f"  {sql_literal(args.property_id)},\n"
        f"  {sql_literal(account_id)}::uuid,\n"
        f"  {pricing['min_price_cents']},\n"
        f"  {pricing['max_price_cents']},\n"
        f"  {pricing['pricing_horizon']},\n"
        f"  {sql_value(profile['room_count'])},\n"
        f"  {sql_value(profile['capacity'])},\n"
        f"  {sql_value(profile['zip_code'])},\n"
        f"  {sql_value(profile['county'])},\n"
        f"  {sql_value(profile['state'])},\n"
        f"  {sql_value(profile['city'])},\n"
        f"  {sql_value(profile['bed'])},\n"
        f"  {sql_value(profile['bath'])},\n"
        f"  {sql_value(profile['other_info'])},\n"
        f"  {sql_literal(property_json)}::jsonb\n"
        ")\n"
        "ON CONFLICT (id)\n"
        "DO UPDATE SET\n"
        "  min_price_cents = EXCLUDED.min_price_cents,\n"
        "  max_price_cents = EXCLUDED.max_price_cents,\n"
        "  pricing_horizon = EXCLUDED.pricing_horizon,\n"
        "  room_count = COALESCE(EXCLUDED.room_count, property.room_count),\n"
        "  capacity = COALESCE(EXCLUDED.capacity, property.capacity),\n"
        "  zip_code = COALESCE(EXCLUDED.zip_code, property.zip_code),\n"
        "  county = COALESCE(EXCLUDED.county, property.county),\n"
        "  state = COALESCE(EXCLUDED.state, property.state),\n"
        "  city = COALESCE(EXCLUDED.city, property.city),\n"
        "  bed = COALESCE(EXCLUDED.bed, property.bed),\n"
        "  bath = COALESCE(EXCLUDED.bath, property.bath),\n"
        "  other_info = COALESCE(EXCLUDED.other_info, property.other_info),\n"
        "  data = property.data || EXCLUDED.data,\n"
        "  updated_at = now();"
    )


def build_upsert_sql(property_id: str, rows: list[dict]) -> str:
    values = []
    for row in rows:
        values.append(
            "("
            + ", ".join(
                [
                    sql_literal(property_id),
                    f"{sql_literal(row['date'])}::date",
                    str(int(row["fixed_price_cents"])),
                    str(int(row["agent_price_cents"])),
                ]
            )
            + ")"
        )
    joined_values = ",\n  ".join(values)
    return (
        "INSERT INTO property_price (property_id, price_date, fixed_price_cents, agent_price_cents)\n"
        f"VALUES\n  {joined_values}\n"
        "ON CONFLICT (property_id, price_date)\n"
        "DO UPDATE SET\n"
        "  fixed_price_cents = EXCLUDED.fixed_price_cents,\n"
        "  agent_price_cents = EXCLUDED.agent_price_cents,\n"
        "  updated_at = now();"
    )


def compact_summary(text: str, limit: int = 220) -> str:
    normalized = re.sub(r"\s+", " ", text).strip()
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 1].rstrip() + "..."


def summary_from_final_message(message: str) -> str:
    for line in message.splitlines():
        cleaned = line.strip().lstrip("-*# ").strip()
        if cleaned:
            return compact_summary(cleaned)
    return "Revy completed a pricing workflow and saved the final explanation."


def conversation_safe_part(value: object | None, fallback: str) -> str:
    text = str(value or fallback).lower()
    text = re.sub(r"[^a-z0-9._-]+", "-", text).strip("-")
    return text[:120] or fallback


def conversation_id_from(args: argparse.Namespace, rows: list[dict]) -> str:
    if args.conversation_id:
        return args.conversation_id
    if args.run_id:
        return f"pricing-final-{conversation_safe_part(args.run_id, 'run')}"
    start = rows[0]["date"] if rows else dt.datetime.now(dt.UTC).date().isoformat()
    end = rows[-1]["date"] if rows else start
    property_part = conversation_safe_part(args.property_id, "property")
    return f"pricing-final-{property_part}-{start}-{end}"


def timestamp_sql(value: str | None) -> str:
    if not value:
        return "now()"
    text = value.strip()
    try:
        dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("--final-message-at must be an ISO timestamp") from exc
    return f"{sql_literal(text)}::timestamptz"


def load_conversation_data_payload(args: argparse.Namespace) -> dict[str, Any]:
    if not args.conversation_data_json:
        return {}
    payload = json.loads(args.conversation_data_json)
    if not isinstance(payload, dict):
        raise ValueError("--conversation-data-json must be a JSON object")
    return payload


def progress_log_candidates(args: argparse.Namespace) -> list[Path]:
    candidates: list[Path] = []
    if args.trace_log_path:
        candidates.append(Path(args.trace_log_path))
    if args.run_id:
        candidates.append(ROOT / "runs" / f"{args.run_id}.log")
        candidates.append(ROOT / "runs" / f"{args.run_id}-progress.log")
    return candidates


def compact_trace_event(event: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "timestamp",
        "stage",
        "substage",
        "workflow",
        "skill",
        "called_skill",
        "tool",
        "status",
        "message",
        "error",
        "metadata",
    )
    compact = {key: event.get(key) for key in keys if event.get(key) not in (None, "", [], {})}
    message = compact.get("message")
    if isinstance(message, str):
        compact["message"] = compact_summary(message, limit=260)
    error = compact.get("error")
    if isinstance(error, str):
        compact["error"] = compact_summary(error, limit=260)
    return compact


def load_trace_events(args: argparse.Namespace) -> list[dict[str, Any]]:
    if args.trace_events_json:
        payload = json.loads(args.trace_events_json)
        if isinstance(payload, dict):
            payload = payload.get("traceEvents") or payload.get("events") or []
        if not isinstance(payload, list):
            raise ValueError("--trace-events-json must be a JSON list or object with traceEvents/events")
        return [compact_trace_event(item) for item in payload if isinstance(item, dict)][-160:]

    for candidate in progress_log_candidates(args):
        if not candidate.exists():
            continue
        events: list[dict[str, Any]] = []
        for line in candidate.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(event, dict):
                events.append(compact_trace_event(event))
        if events:
            return events[-160:]
    return []


def daily_conversation_prices(rows: list[dict]) -> list[dict[str, Any]]:
    daily: list[dict[str, Any]] = []
    for row in rows:
        daily.append(
            {
                "date": row["date"],
                "current_price": (
                    cents_to_dollars(row["fixed_price_cents"])
                    if row.get("current_price_available")
                    else None
                ),
                "current_price_available": row.get("current_price_available", False),
                "agent_price": cents_to_dollars(row["agent_price_cents"]),
                "occupancy_rate": row["occupancy_rate"],
            }
        )
    return daily


def build_conversation_data(args: argparse.Namespace, rows: list[dict], summary: dict[str, Any]) -> dict[str, Any]:
    if not args.final_message:
        raise ValueError("--final-message is required when writing revy_conversation")

    payload = load_conversation_data_payload(args)
    conversation_id = conversation_id_from(args, rows)
    final_message_at = args.final_message_at or dt.datetime.now(dt.UTC).isoformat().replace("+00:00", "Z")
    conversation_summary = args.conversation_summary or summary_from_final_message(args.final_message)
    trace_events = load_trace_events(args)
    messages: list[dict[str, str]] = []
    if args.user_message:
        messages.append({"role": "user", "text": args.user_message, "at": final_message_at})
    messages.append({"role": "agent", "text": args.final_message, "at": final_message_at})

    payload.update(
        {
            "conversationId": conversation_id,
            "summary": conversation_summary,
            "messages": messages,
            "source": "pricing-workflow",
            "tool": "revpar_estimate.write-prices",
            "runId": args.run_id,
            "propertyId": args.property_id,
            "updatedAt": final_message_at,
            "priceDateRange": {
                "start": rows[0]["date"] if rows else None,
                "end": rows[-1]["date"] if rows else None,
                "nightCount": len(rows),
            },
            "revparSummary": summary,
            "priceCalendar": daily_conversation_prices(rows),
            "traceEvents": trace_events or payload.get("traceEvents") or payload.get("events"),
        }
    )
    return {key: value for key, value in payload.items() if value not in (None, [], "")}


def build_revy_conversation_sql(args: argparse.Namespace, rows: list[dict], summary: dict[str, Any]) -> str:
    account_id = args.account_id or DEFAULT_ACCOUNT_ID
    conversation_id = conversation_id_from(args, rows)
    title = args.conversation_title or f"Pricing workflow for {args.property_name or args.property_id}"
    data_json = json.dumps(build_conversation_data(args, rows, summary), ensure_ascii=False, sort_keys=True)
    return (
        "INSERT INTO revy_conversation (id, account_id, property_id, title, final_message_at, data)\n"
        "VALUES (\n"
        f"  {sql_literal(conversation_id)},\n"
        f"  {sql_literal(account_id)}::uuid,\n"
        f"  {sql_value(args.property_id)},\n"
        f"  {sql_literal(title)},\n"
        f"  {timestamp_sql(args.final_message_at)},\n"
        f"  {sql_literal(data_json)}::jsonb\n"
        ")\n"
        "ON CONFLICT (id)\n"
        "DO UPDATE SET\n"
        "  property_id = EXCLUDED.property_id,\n"
        "  title = EXCLUDED.title,\n"
        "  final_message_at = EXCLUDED.final_message_at,\n"
        "  data = EXCLUDED.data,\n"
        "  updated_at = now();"
    )


def run_local_psql(database_url: str, sql: str, psql_command: str) -> dict:
    if shutil.which(psql_command) is None:
        return {
            "ok": False,
            "method": "local_psql",
            "missing_client": True,
            "error": f"{psql_command} was not found.",
        }
    try:
        result = subprocess.run(
            [psql_command, database_url, "-v", "ON_ERROR_STOP=1", "-c", sql],
            text=True,
            capture_output=True,
            check=False,
        )
    except FileNotFoundError:
        return {
            "ok": False,
            "method": "local_psql",
            "missing_client": True,
            "error": f"{psql_command} was not found.",
        }
    return {
        "ok": result.returncode == 0,
        "method": "local_psql",
        "returncode": result.returncode,
        "stdout": result.stdout.strip(),
        "stderr": result.stderr.strip(),
    }


def database_parts(database_url: str) -> dict:
    parsed = urllib.parse.urlparse(database_url)
    return {
        "database": (parsed.path or "/dev").lstrip("/") or "dev",
        "user": urllib.parse.unquote(parsed.username or "postgres"),
        "password": urllib.parse.unquote(parsed.password or "postgres"),
    }


def run_docker_compose_psql(database_url: str, sql: str, service: str) -> dict:
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
    cmd = [
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
        "-U",
        parts["user"],
        "-d",
        parts["database"],
        "-c",
        sql,
    ]
    result = subprocess.run(
        cmd,
        cwd=str(DATA_DIR),
        text=True,
        capture_output=True,
        check=False,
    )
    error = None
    stderr = result.stderr.strip()
    if result.returncode != 0:
        error = stderr or "docker compose psql failed"
        if "is not running" in stderr or "No such container" in stderr or "service" in stderr:
            error += " Start the local database with: cd data && docker compose up -d"
    return {
        "ok": result.returncode == 0,
        "method": "docker_compose_psql",
        "returncode": result.returncode,
        "stdout": result.stdout.strip(),
        "stderr": stderr,
        "error": error,
    }


def run_write(database_url: str, sql: str, args: argparse.Namespace) -> dict:
    methods = [args.write_method]
    if args.write_method == "auto":
        methods = ["local-psql", "docker-compose"]

    attempts = []
    for method in methods:
        if method == "local-psql":
            result = run_local_psql(database_url, sql, args.psql_command)
        elif method == "docker-compose":
            result = run_docker_compose_psql(database_url, sql, args.docker_service)
        else:
            result = {"ok": False, "method": method, "error": f"Unknown write method: {method}"}
        attempts.append(result)
        if result.get("ok"):
            result = dict(result)
            result["attempts"] = [{key: value for key, value in item.items() if key != "attempts"} for item in attempts]
            return result
        if method == "local-psql" and args.write_method == "auto" and result.get("missing_client"):
            continue
        if args.write_method != "auto":
            result = dict(result)
            result["attempts"] = [{key: value for key, value in item.items() if key != "attempts"} for item in attempts]
            return result

    final = dict(attempts[-1]) if attempts else {"ok": False, "error": "No write methods attempted"}
    final["attempts"] = [{key: value for key, value in item.items() if key != "attempts"} for item in attempts]
    return final


def prepared_rows(args: argparse.Namespace, require_strategy_validation: bool = False) -> list[dict]:
    calendar = load_price_calendar(args)
    if require_strategy_validation:
        validate_strategy_guarded_calendar(calendar)
    occupancy_rate = parse_rate(args.occupancy_rate, 1.0)
    return normalize_price_calendar(calendar, occupancy_rate)


def cmd_estimate(args: argparse.Namespace) -> None:
    try:
        rows = prepared_rows(args)
        summary = estimate_revpar(rows, args.rooms)
        emit(
            {
                "source": "revpar_estimate",
                "tool": "estimate",
                "property_id": args.property_id,
                "currency": MONEY_CURRENCY,
                "money_unit": MONEY_UNIT,
                "database_storage_unit": "cents",
                "summary": summary,
                "daily": [
                    {
                        "date": row["date"],
                        "currency": MONEY_CURRENCY,
                        "money_unit": MONEY_UNIT,
                        "current_price": (
                            cents_to_dollars(row["fixed_price_cents"])
                            if row.get("current_price_available")
                            else None
                        ),
                        "current_price_usd": (
                            cents_to_dollars(row["fixed_price_cents"])
                            if row.get("current_price_available")
                            else None
                        ),
                        "current_price_available": row.get("current_price_available", False),
                        "agent_price": cents_to_dollars(row["agent_price_cents"]),
                        "agent_price_usd": cents_to_dollars(row["agent_price_cents"]),
                        "occupancy_rate": row["occupancy_rate"],
                        "agent_revpar": cents_to_dollars(row["agent_price_cents"] * row["occupancy_rate"]),
                        "agent_revpar_usd": cents_to_dollars(row["agent_price_cents"] * row["occupancy_rate"]),
                    }
                    for row in rows
                ],
            }
        )
    except Exception as exc:
        emit({"source": "revpar_estimate", "tool": "estimate", "error": str(exc)}, exit_code=1)


def cmd_write_prices(args: argparse.Namespace) -> None:
    try:
        rows = prepared_rows(args, require_strategy_validation=True)
        summary = estimate_revpar(rows, args.rooms)
        conversation_id = conversation_id_from(args, rows) if args.final_message else None
        statements = []
        if not args.no_create_property:
            statements.append(build_ensure_property_sql(args, rows, summary))
        statements.append(build_upsert_sql(args.property_id, rows))
        if args.final_message:
            statements.append(build_revy_conversation_sql(args, rows, summary))
        sql = "\n\n".join(statements)
        conversation_write = (
            {"status": "pending", "table": "revy_conversation", "conversation_id": conversation_id}
            if args.final_message
            else {"status": "skipped", "reason": "--final-message was not provided"}
        )
        if args.dry_run:
            payload = {
                "source": "revpar_estimate",
                "tool": "write-prices",
                "dry_run": True,
                "property_id": args.property_id,
                "property_registration": not args.no_create_property,
                "currency": MONEY_CURRENCY,
                "money_unit": MONEY_UNIT,
                "database_storage_unit": "cents",
                "sql_note": "SQL uses *_cents columns for storage only. All summary fields are USD dollars.",
                "rows_to_write": len(rows),
                "summary": summary,
                "conversation_write": conversation_write,
            }
            if args.include_sql:
                payload["sql"] = sql
            emit(payload)

        database_url = database_url_from(args)
        write_result = run_write(database_url, sql, args)
        if args.final_message:
            conversation_write = {
                "status": "completed" if write_result.get("ok") else "failed",
                "table": "revy_conversation",
                "conversation_id": conversation_id,
            }
        emit(
            {
                "source": "revpar_estimate",
                "tool": "write-prices",
                "property_id": args.property_id,
                "property_registration": not args.no_create_property,
                "currency": MONEY_CURRENCY,
                "money_unit": MONEY_UNIT,
                "database_storage_unit": "cents",
                "rows_written": len(rows) if write_result.get("ok") else 0,
                "summary": summary,
                "conversation_write": conversation_write,
                "database_url_source": "argument/env/default",
                "write_result": write_result,
            },
            exit_code=0 if write_result.get("ok") else 1,
        )
    except Exception as exc:
        emit({"source": "revpar_estimate", "tool": "write-prices", "error": str(exc)}, exit_code=1)


def add_calendar_args(parser: argparse.ArgumentParser, property_required: bool = False) -> None:
    parser.add_argument("--price-calendar-json", help="Inline JSON list or object containing the price calendar")
    parser.add_argument("--property-id", required=property_required)
    parser.add_argument("--rooms", type=int, default=1, help="Available rooms for RevPAR calculation")
    parser.add_argument("--occupancy-rate", default="1.0", help="Expected occupancy rate, e.g. 0.84 or 84")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="RevNest RevPAR estimate and PostgreSQL price write-back tool")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("estimate", help="Estimate ADR, occupancy, RevPAR, and revenue from a price calendar")
    add_calendar_args(p)
    p.set_defaults(func=cmd_estimate)

    p = sub.add_parser("write-prices", help="Upsert predicted prices into PostgreSQL property_price")
    add_calendar_args(p, property_required=True)
    p.add_argument("--database-url")
    p.add_argument("--psql-command", default="psql")
    p.add_argument("--write-method", choices=("auto", "local-psql", "docker-compose"), default="auto")
    p.add_argument("--docker-service", default="postgres", help="Docker Compose database service name")
    p.add_argument("--no-create-property", action="store_true", help="Do not auto-create a missing property row")
    p.add_argument("--account-id", default=DEFAULT_ACCOUNT_ID, help="Account id used when auto-creating a property")
    p.add_argument("--account-email", default=DEFAULT_ACCOUNT_EMAIL, help="Account email used if the account must be created")
    p.add_argument("--account-name", default=DEFAULT_ACCOUNT_NAME, help="Account name used if the account must be created")
    p.add_argument("--account-type", choices=("airbnb", "hotel"), default="airbnb", help="Account type used if the account must be created")
    p.add_argument("--min-price", help="Minimum nightly guardrail in USD when auto-creating a property")
    p.add_argument("--max-price", help="Maximum nightly guardrail in USD when auto-creating a property")
    p.add_argument("--pricing-horizon", type=int, help="Pricing horizon in days when auto-creating a property")
    p.add_argument("--property-name", help="Display name stored when auto-creating a property")
    p.add_argument("--property-type", default="Airbnb", help="Property type stored when auto-creating a property")
    p.add_argument("--location", help="Location stored when auto-creating a property")
    p.add_argument("--property-data-json", help="Optional JSON object merged into the auto-created property data")
    p.add_argument("--run-id", help="Pricing workflow run id stored with the saved Revy conversation")
    p.add_argument("--conversation-id", help="Explicit revy_conversation id; defaults to run id or property/date range")
    p.add_argument("--conversation-title", help="Title for the saved Revy conversation")
    p.add_argument("--conversation-summary", help="Short summary stored in revy_conversation.data.summary")
    p.add_argument("--conversation-data-json", help="Optional JSON object merged into revy_conversation.data")
    p.add_argument("--trace-events-json", help="Optional JSON list of compact progress events stored as traceEvents")
    p.add_argument("--trace-log-path", help="Optional progress JSONL path used to persist compact traceEvents")
    p.add_argument("--user-message", help="Optional user prompt stored before the final agent message")
    p.add_argument("--final-message", help="Final user-facing pricing explanation stored in revy_conversation")
    p.add_argument("--final-message-at", help="ISO timestamp for revy_conversation.final_message_at; defaults to database now()")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--include-sql", action="store_true", help="Include raw SQL in dry-run output")
    p.set_defaults(func=cmd_write_prices)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
