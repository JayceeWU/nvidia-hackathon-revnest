#!/usr/bin/env python3
"""
RevNest holiday calendar tool.

Uses Nager.Date public holiday data and returns JSON grouped for pricing
workflows:
- local public holidays
- school vacation/holiday rows when Nager.Date marks them as School
- other non-public holiday/observance rows
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import ssl
import urllib.request


NAGER_BASE_URL = "https://date.nager.at/api/v3"

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

CANADA_PROVINCES = {
    "alberta": "AB",
    "british columbia": "BC",
    "manitoba": "MB",
    "new brunswick": "NB",
    "newfoundland and labrador": "NL",
    "nova scotia": "NS",
    "ontario": "ON",
    "prince edward island": "PE",
    "quebec": "QC",
    "saskatchewan": "SK",
    "northwest territories": "NT",
    "nunavut": "NU",
    "yukon": "YT",
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
    "england": "GB",
    "germany": "DE",
    "france": "FR",
    "spain": "ES",
    "italy": "IT",
    "mexico": "MX",
    "australia": "AU",
    "new zealand": "NZ",
    "japan": "JP",
    "china": "CN",
    "india": "IN",
}


def emit(payload: dict, exit_code: int = 0) -> None:
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    raise SystemExit(exit_code)


def parse_iso_date(value: str, field_name: str) -> dt.date:
    try:
        return dt.date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} must use YYYY-MM-DD format") from exc


def http_get_json(url: str, timeout: int = 12):
    request = urllib.request.Request(url, headers={"User-Agent": "RevNest-Holiday-Agent/0.1"})
    context = ssl.create_default_context()
    with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
        return json.loads(response.read().decode("utf-8"))


def infer_location(address: str, country_code: str | None, subdivision_code: str | None) -> dict:
    normalized_country = country_code.upper() if country_code else infer_country_code(address)
    if not normalized_country:
        raise ValueError(
            "Could not infer country from address. Pass --country-code, for example --country-code US."
        )

    normalized_subdivision = subdivision_code.upper() if subdivision_code else infer_subdivision_code(
        address,
        normalized_country,
    )
    return {
        "address": address,
        "country_code": normalized_country,
        "subdivision_code": normalized_subdivision,
    }


def infer_country_code(address: str) -> str | None:
    text = normalize_text(address)
    tokens = address_tokens(address)

    for name, code in sorted(COUNTRY_ALIASES.items(), key=lambda item: len(item[0]), reverse=True):
        if re.search(rf"\b{re.escape(name)}\b", text):
            return code

    if any(token in US_STATES.values() for token in tokens):
        return "US"
    if any(token in CANADA_PROVINCES.values() for token in tokens):
        return "CA"
    for state_name in US_STATES:
        if re.search(rf"\b{re.escape(state_name)}\b", text):
            return "US"
    for province_name in CANADA_PROVINCES:
        if re.search(rf"\b{re.escape(province_name)}\b", text):
            return "CA"

    return None


def infer_subdivision_code(address: str, country_code: str) -> str | None:
    text = normalize_text(address)
    tokens = address_tokens(address)

    if country_code == "US":
        for token in tokens:
            if token in US_STATES.values():
                return f"US-{token}"
        for state_name, state_code in US_STATES.items():
            if re.search(rf"\b{re.escape(state_name)}\b", text):
                return f"US-{state_code}"

    if country_code == "CA":
        for token in tokens:
            if token in CANADA_PROVINCES.values():
                return f"CA-{token}"
        for province_name, province_code in CANADA_PROVINCES.items():
            if re.search(rf"\b{re.escape(province_name)}\b", text):
                return f"CA-{province_code}"

    return None


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower())


def address_tokens(address: str) -> set[str]:
    return {token.upper() for token in re.findall(r"[A-Za-z]{2,}", address)}


def fetch_holidays(year: int, country_code: str) -> list[dict]:
    url = f"{NAGER_BASE_URL}/PublicHolidays/{year}/{country_code}"
    return http_get_json(url)


def is_relevant_to_subdivision(holiday: dict, subdivision_code: str | None) -> bool:
    counties = holiday.get("counties")
    if not counties:
        return True
    if not subdivision_code:
        return True
    return subdivision_code in counties


def normalize_holiday(holiday: dict) -> dict:
    return {
        "date": holiday.get("date"),
        "name": holiday.get("name"),
        "local_name": holiday.get("localName"),
        "country_code": holiday.get("countryCode"),
        "global": bool(holiday.get("global")),
        "counties": holiday.get("counties"),
        "types": holiday.get("types") or [],
    }


def date_in_range(holiday: dict, start: dt.date, end: dt.date) -> bool:
    value = holiday.get("date")
    if not isinstance(value, str):
        return False
    try:
        holiday_date = dt.date.fromisoformat(value)
    except ValueError:
        return False
    return start <= holiday_date <= end


def group_school_periods(school_holidays: list[dict]) -> list[dict]:
    if not school_holidays:
        return []

    ordered = sorted(school_holidays, key=lambda item: item["date"])
    periods = []
    current = {
        "start_date": ordered[0]["date"],
        "end_date": ordered[0]["date"],
        "days": [ordered[0]],
    }

    for holiday in ordered[1:]:
        previous = dt.date.fromisoformat(current["end_date"])
        current_date = dt.date.fromisoformat(holiday["date"])
        if current_date == previous + dt.timedelta(days=1):
            current["end_date"] = holiday["date"]
            current["days"].append(holiday)
        else:
            periods.append(format_school_period(current))
            current = {
                "start_date": holiday["date"],
                "end_date": holiday["date"],
                "days": [holiday],
            }

    periods.append(format_school_period(current))
    return periods


def format_school_period(period: dict) -> dict:
    names = sorted({item["name"] for item in period["days"] if item.get("name")})
    return {
        "start_date": period["start_date"],
        "end_date": period["end_date"],
        "day_count": len(period["days"]),
        "names": names,
        "days": period["days"],
    }


def build_summary(public_holidays: list[dict], school_holidays: list[dict], other_holidays: list[dict]) -> dict:
    demand_dates = {item["date"] for item in public_holidays + school_holidays if item.get("date")}
    return {
        "public_holiday_count": len(public_holidays),
        "school_holiday_count": len(school_holidays),
        "other_holiday_count": len(other_holidays),
        "demand_pressure_dates": sorted(demand_dates),
        "pricing_note": (
            "Public holidays and school holidays can lift leisure demand. "
            "Treat optional observances as weaker signals unless local events or pickup data agree."
        ),
    }


def cmd_calendar(args: argparse.Namespace) -> None:
    try:
        start = parse_iso_date(args.start_date, "start_date")
        end = parse_iso_date(args.end_date, "end_date")
        if end < start:
            emit({"error": "end_date must be on or after start_date"}, exit_code=2)
        if (end - start).days > 370:
            emit({"error": "date range is limited to 371 days"}, exit_code=2)

        location = infer_location(args.address, args.country_code, args.subdivision_code)
        years = range(start.year, end.year + 1)
        rows = []
        for year in years:
            rows.extend(fetch_holidays(year, location["country_code"]))

        holidays = [
            normalize_holiday(row)
            for row in rows
            if date_in_range(row, start, end)
            and is_relevant_to_subdivision(row, location["subdivision_code"])
        ]
        holidays.sort(key=lambda item: (item["date"] or "", item["name"] or ""))

        public_holidays = [item for item in holidays if "Public" in item["types"]]
        school_holidays = [item for item in holidays if "School" in item["types"]]
        other_holidays = [
            item
            for item in holidays
            if "Public" not in item["types"] and "School" not in item["types"]
        ]

        emit(
            {
                "source": "nager_date",
                "tool": "holiday-calendar",
                "query": {
                    "address": args.address,
                    "start_date": start.isoformat(),
                    "end_date": end.isoformat(),
                    "country_code": location["country_code"],
                    "subdivision_code": location["subdivision_code"],
                },
                "summary": build_summary(public_holidays, school_holidays, other_holidays),
                "local_public_holidays": public_holidays,
                "school_vacation_periods": group_school_periods(school_holidays),
                "school_holidays": school_holidays,
                "other_holidays": other_holidays,
                "coverage_note": (
                    "Nager.Date returns dated holiday rows and marks school-related rows with type School "
                    "when available. It does not provide full school district vacation calendars."
                ),
            }
        )
    except Exception as exc:
        emit({"source": "nager_date", "tool": "holiday-calendar", "error": str(exc)}, exit_code=1)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="RevNest holiday calendar tool")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("calendar", help="Fetch local holidays for an address and date range")
    p.add_argument("--address", required=True, help='Address or location, e.g. "Santa Cruz, CA, US"')
    p.add_argument("--start-date", required=True, help="YYYY-MM-DD")
    p.add_argument("--end-date", required=True, help="YYYY-MM-DD")
    p.add_argument("--country-code", help="Optional ISO 3166-1 alpha-2 override, e.g. US")
    p.add_argument("--subdivision-code", help="Optional Nager subdivision code, e.g. US-CA")
    p.set_defaults(func=cmd_calendar)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
