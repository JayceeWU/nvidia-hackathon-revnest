#!/usr/bin/env python3
"""
RevNest Ticketmaster local events tool.

Uses Ticketmaster Discovery API v2 to find local events for a location and date
range. The API key is read from TICKETMASTER_API_KEY or --api-key.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import ssl
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / ".env"
DISCOVERY_EVENTS_URL = "https://app.ticketmaster.com/discovery/v2/events.json"

US_STATES = {
    "alabama": "AL",
    "alaska": "AK",
    "arizona": "AZ",
    "arkansas": "AR",
    "california": "CA",
    "colorado": "CO",
    "connecticut": "CT",
    "delaware": "DE",
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
    "district of columbia": "DC",
}

COUNTRY_ALIASES = {
    "united states": "US",
    "united states of america": "US",
    "usa": "US",
    "u.s.a.": "US",
    "us": "US",
    "canada": "CA",
    "united kingdom": "GB",
    "uk": "GB",
    "great britain": "GB",
    "germany": "DE",
    "france": "FR",
    "spain": "ES",
    "italy": "IT",
    "mexico": "MX",
    "australia": "AU",
    "new zealand": "NZ",
    "japan": "JP",
}


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


def api_key_from(args: argparse.Namespace) -> str | None:
    load_local_env()
    return args.api_key or os.getenv("TICKETMASTER_API_KEY")


def parse_iso_date(value: str, field_name: str) -> dt.date:
    try:
        return dt.date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} must use YYYY-MM-DD format") from exc


def ticketmaster_datetime(value: dt.date, end_of_day: bool = False) -> str:
    time_value = dt.time(23, 59, 59) if end_of_day else dt.time(0, 0, 0)
    return dt.datetime.combine(value, time_value).isoformat(timespec="seconds") + "Z"


def http_get_json(url: str, timeout: int = 15) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": "RevNest-Ticketmaster-Agent/0.1"})
    context = ssl.create_default_context()
    with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
        return json.loads(response.read().decode("utf-8"))


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower())


def address_tokens(address: str) -> set[str]:
    return {token.upper() for token in re.findall(r"[A-Za-z]{2,}", address)}


def infer_location(address: str, country_code: str | None, state_code: str | None, city: str | None) -> dict:
    country = country_code.upper() if country_code else infer_country_code(address)
    state = state_code.upper() if state_code else infer_state_code(address)
    inferred_city = city or infer_city(address)

    if not country:
        raise ValueError("Could not infer country from address. Pass --country-code, for example --country-code US.")
    if not inferred_city:
        raise ValueError("Could not infer city from address. Pass --city, for example --city \"Santa Cruz\".")

    return {
        "address": address,
        "city": inferred_city,
        "state_code": state,
        "country_code": country,
    }


def infer_country_code(address: str) -> str | None:
    text = normalize_text(address)
    tokens = address_tokens(address)

    for name, code in sorted(COUNTRY_ALIASES.items(), key=lambda item: len(item[0]), reverse=True):
        if re.search(rf"\b{re.escape(name)}\b", text):
            return code

    if any(token in US_STATES.values() for token in tokens):
        return "US"
    for state_name in US_STATES:
        if re.search(rf"\b{re.escape(state_name)}\b", text):
            return "US"

    return None


def infer_state_code(address: str) -> str | None:
    text = normalize_text(address)
    tokens = address_tokens(address)

    for token in tokens:
        if token in US_STATES.values():
            return token
    for state_name, state_code in US_STATES.items():
        if re.search(rf"\b{re.escape(state_name)}\b", text):
            return state_code

    return None


def infer_city(address: str) -> str | None:
    parts = [part.strip() for part in address.split(",") if part.strip()]
    if not parts:
        return None

    first = re.sub(r"^\d+\s+", "", parts[0]).strip()
    return first or None


def event_segment(event: dict) -> str | None:
    classifications = event.get("classifications") or []
    if not classifications:
        return None
    segment = classifications[0].get("segment") or {}
    name = segment.get("name")
    return name if isinstance(name, str) else None


def event_genre(event: dict) -> str | None:
    classifications = event.get("classifications") or []
    if not classifications:
        return None
    genre = classifications[0].get("genre") or {}
    name = genre.get("name")
    return name if isinstance(name, str) else None


def primary_venue(event: dict) -> dict:
    venues = (event.get("_embedded") or {}).get("venues") or []
    return venues[0] if venues else {}


def price_range(event: dict) -> dict | None:
    ranges = event.get("priceRanges") or []
    if not ranges:
        return None
    first = ranges[0]
    return {
        "currency": first.get("currency"),
        "min": first.get("min"),
        "max": first.get("max"),
    }


def normalize_event(event: dict) -> dict:
    dates = event.get("dates") or {}
    start = dates.get("start") or {}
    status = dates.get("status") or {}
    venue = primary_venue(event)
    segment = event_segment(event)
    genre = event_genre(event)

    return {
        "id": event.get("id"),
        "name": event.get("name"),
        "url": event.get("url"),
        "date": start.get("localDate"),
        "time": start.get("localTime"),
        "date_time_utc": start.get("dateTime"),
        "timezone": dates.get("timezone"),
        "status": status.get("code"),
        "segment": segment,
        "genre": genre,
        "venue": {
            "name": venue.get("name"),
            "city": ((venue.get("city") or {}).get("name")),
            "state_code": ((venue.get("state") or {}).get("stateCode")),
            "country_code": ((venue.get("country") or {}).get("countryCode")),
            "address": ((venue.get("address") or {}).get("line1")),
        },
        "price_range": price_range(event),
        "demand_signal": event_demand_signal(segment, genre, start.get("localDate")),
    }


def event_demand_signal(segment: str | None, genre: str | None, date_text: str | None) -> dict:
    score = 1
    reasons = []
    segment_key = (segment or "").lower()
    genre_key = (genre or "").lower()

    if segment_key in {"sports", "music"}:
        score += 2
        reasons.append(f"{segment_key} event can draw regional overnight demand")
    elif segment_key in {"arts & theatre", "miscellaneous"}:
        score += 1
        reasons.append(f"{segment_key} event may support local leisure demand")

    if any(token in genre_key for token in ("festival", "family", "conference", "comedy")):
        score += 1
        reasons.append(f"{genre_key} genre can affect short-stay demand")

    if date_text:
        try:
            date = dt.date.fromisoformat(date_text)
            if date.weekday() >= 4:
                score += 1
                reasons.append("weekend timing")
        except ValueError:
            pass

    if score >= 4:
        impact = "high"
    elif score >= 2:
        impact = "medium"
    else:
        impact = "low"

    return {
        "impact": impact,
        "score": score,
        "reasons": reasons,
    }


def summarize_events(events: list[dict]) -> dict:
    segment_counts = Counter(event.get("segment") or "unknown" for event in events)
    impact_counts = Counter((event.get("demand_signal") or {}).get("impact", "unknown") for event in events)
    demand_dates = sorted({
        event["date"]
        for event in events
        if event.get("date") and (event.get("demand_signal") or {}).get("impact") in {"medium", "high"}
    })
    return {
        "event_count": len(events),
        "segment_counts": dict(segment_counts),
        "demand_impact_counts": dict(impact_counts),
        "demand_pressure_dates": demand_dates,
        "pricing_note": (
            "Use Ticketmaster events as demand signals. Larger music, sports, festival, and weekend events "
            "can support ADR uplift when pickup pace and competitor rates agree."
        ),
    }


def build_ticketmaster_url(args: argparse.Namespace, location: dict, start: dt.date, end: dt.date, api_key: str) -> str:
    params = {
        "apikey": api_key,
        "city": location["city"],
        "countryCode": location["country_code"],
        "startDateTime": ticketmaster_datetime(start),
        "endDateTime": ticketmaster_datetime(end, end_of_day=True),
        "size": str(min(max(args.limit, 1), 200)),
        "page": "0",
        "sort": "date,asc",
        "includeTBA": "no",
        "includeTBD": "no",
        "includeTest": "no",
    }
    if location["state_code"]:
        params["stateCode"] = location["state_code"]
    if args.keyword:
        params["keyword"] = args.keyword
    if args.classification_name:
        params["classificationName"] = args.classification_name
    if args.source:
        params["source"] = args.source

    return DISCOVERY_EVENTS_URL + "?" + urllib.parse.urlencode(params)


def cmd_events(args: argparse.Namespace) -> None:
    try:
        api_key = api_key_from(args)
        if not api_key:
            emit(
                {
                    "source": "ticketmaster_discovery_api",
                    "tool": "ticketmaster",
                    "error": "Missing Ticketmaster API key. Set TICKETMASTER_API_KEY or pass --api-key.",
                },
                exit_code=2,
            )

        start = parse_iso_date(args.start_date, "start_date")
        end = parse_iso_date(args.end_date, "end_date")
        if end < start:
            emit({"error": "end_date must be on or after start_date"}, exit_code=2)
        if (end - start).days > 370:
            emit({"error": "date range is limited to 371 days"}, exit_code=2)

        location = infer_location(args.address, args.country_code, args.state_code, args.city)
        url = build_ticketmaster_url(args, location, start, end, api_key)
        data = http_get_json(url)
        raw_events = (data.get("_embedded") or {}).get("events") or []
        events = [normalize_event(event) for event in raw_events]
        events.sort(key=lambda item: (item.get("date") or "", item.get("time") or "", item.get("name") or ""))

        emit(
            {
                "source": "ticketmaster_discovery_api",
                "tool": "ticketmaster",
                "query": {
                    "address": args.address,
                    "city": location["city"],
                    "state_code": location["state_code"],
                    "country_code": location["country_code"],
                    "start_date": start.isoformat(),
                    "end_date": end.isoformat(),
                    "keyword": args.keyword,
                    "classification_name": args.classification_name,
                },
                "summary": summarize_events(events),
                "events": events,
                "page": data.get("page", {}),
            }
        )
    except Exception as exc:
        emit({"source": "ticketmaster_discovery_api", "tool": "ticketmaster", "error": str(exc)}, exit_code=1)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="RevNest Ticketmaster local events tool")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("events", help="Fetch local events for an address and date range")
    p.add_argument("--address", required=True, help='Address or location, e.g. "Santa Cruz, CA, US"')
    p.add_argument("--start-date", required=True, help="YYYY-MM-DD")
    p.add_argument("--end-date", required=True, help="YYYY-MM-DD")
    p.add_argument("--api-key", help="Ticketmaster Consumer Key. Prefer TICKETMASTER_API_KEY env var.")
    p.add_argument("--city", help="Optional city override")
    p.add_argument("--state-code", help="Optional state/province code override, e.g. CA")
    p.add_argument("--country-code", help="Optional ISO 3166-1 alpha-2 country code override, e.g. US")
    p.add_argument("--keyword", help="Optional event keyword")
    p.add_argument("--classification-name", help="Optional classification filter, e.g. music or sports")
    p.add_argument("--source", help="Optional Ticketmaster source filter")
    p.add_argument("--limit", type=int, default=25)
    p.set_defaults(func=cmd_events)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
