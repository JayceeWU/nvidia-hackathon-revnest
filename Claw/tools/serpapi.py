#!/usr/bin/env python3
"""
RevNest SerpApi tool.

Provides:
- Google Events search via SerpApi google_events
- Google Hotels / Vacation Rentals search via SerpApi google_hotels

The API key is read from SERPAPI_API_KEY, SerpApi_API_KEY, or --api-key.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import ssl
import urllib.parse
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path


SERPAPI_SEARCH_URL = "https://serpapi.com/search.json"
ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / ".env"


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
    return (
        args.api_key
        or os.getenv("SERPAPI_API_KEY")
        or os.getenv("SerpApi_API_KEY")
        or os.getenv("SERP_API_KEY")
    )


def parse_iso_date(value: str, field_name: str) -> dt.date:
    try:
        return dt.date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} must use YYYY-MM-DD format") from exc


def http_get_json(params: dict, timeout: int = 30) -> dict:
    url = SERPAPI_SEARCH_URL + "?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(url, headers={"User-Agent": "RevNest-SerpApi-Agent/0.1"})
    context = ssl.create_default_context()
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            data = {"error": body or str(exc)}
        if "error" not in data:
            data["error"] = str(exc)
        data["http_status"] = exc.code
        return data


def city_query(address: str) -> str:
    parts = [part.strip() for part in address.split(",") if part.strip()]
    if not parts:
        return address.strip()
    city = re.sub(r"^\d+\s+", "", parts[0]).strip()
    if len(parts) >= 2:
        return f"{city}, {parts[1].strip()}"
    return city


def infer_country(address: str) -> str:
    text = address.lower()
    if any(token in text for token in ("united kingdom", " uk", "great britain", "england")):
        return "uk"
    if "canada" in text:
        return "ca"
    if "australia" in text:
        return "au"
    if "new zealand" in text:
        return "nz"
    if "japan" in text:
        return "jp"
    if "mexico" in text:
        return "mx"
    return "us"


def event_query(address: str, start: dt.date, end: dt.date, keyword: str | None) -> str:
    base = keyword or "events"
    return f"{base} in {city_query(address)}"


def parse_event_date(value: str | None, default_year: int) -> dt.date | None:
    if not value:
        return None
    text = re.sub(r"\s+", " ", value.strip())
    for fmt in ("%Y-%m-%d", "%b %d, %Y", "%B %d, %Y"):
        try:
            return dt.datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    for fmt in ("%a, %b %d %Y", "%b %d %Y", "%B %d %Y"):
        try:
            parsed = dt.datetime.strptime(f"{text} {default_year}", fmt)
            return dt.date(parsed.year, parsed.month, parsed.day)
        except ValueError:
            pass
    match = re.search(r"([A-Z][a-z]{2,8})\s+(\d{1,2})", text)
    if match:
        month_day = " ".join(match.groups())
        for fmt in ("%b %d %Y", "%B %d %Y"):
            try:
                parsed = dt.datetime.strptime(f"{month_day} {default_year}", fmt)
                return dt.date(default_year, parsed.month, parsed.day)
            except ValueError:
                pass
    return None


def event_date_text(event: dict) -> str | None:
    date = event.get("date")
    if isinstance(date, dict):
        return date.get("start_date") or date.get("when")
    if isinstance(date, str):
        return date
    return event.get("when") if isinstance(event.get("when"), str) else None


def normalize_event(event: dict, start: dt.date, end: dt.date) -> dict:
    date_text = event_date_text(event)
    parsed_date = parse_event_date(date_text, start.year)
    venue = event.get("venue") or {}
    if not isinstance(venue, dict):
        venue = {"name": str(venue)}

    return {
        "title": event.get("title"),
        "date_text": date_text,
        "date": parsed_date.isoformat() if parsed_date else None,
        "in_requested_range": start <= parsed_date <= end if parsed_date else None,
        "address": event.get("address"),
        "venue": {
            "name": venue.get("name"),
            "rating": venue.get("rating"),
            "reviews": venue.get("reviews"),
            "link": venue.get("link"),
        },
        "link": event.get("link"),
        "description": event.get("description"),
        "ticket_info": event.get("ticket_info"),
        "thumbnail": event.get("thumbnail"),
        "demand_signal": event_demand_signal(event, parsed_date),
    }


def event_demand_signal(event: dict, date_value: dt.date | None) -> dict:
    text = " ".join(
        str(value)
        for value in [event.get("title"), event.get("description"), event.get("address")]
        if value
    ).lower()
    score = 1
    reasons = []
    if any(token in text for token in ("festival", "conference", "convention", "tournament")):
        score += 2
        reasons.append("large-format event keyword")
    if any(token in text for token in ("concert", "music", "sports", "game", "show")):
        score += 1
        reasons.append("leisure event keyword")
    if date_value and date_value.weekday() >= 4:
        score += 1
        reasons.append("weekend timing")

    impact = "high" if score >= 4 else "medium" if score >= 2 else "low"
    return {"impact": impact, "score": score, "reasons": reasons}


def summarize_events(events: list[dict]) -> dict:
    impact_counts = Counter((event.get("demand_signal") or {}).get("impact", "unknown") for event in events)
    demand_dates = sorted({
        event["date"]
        for event in events
        if event.get("date") and (event.get("demand_signal") or {}).get("impact") in {"medium", "high"}
    })
    return {
        "event_count": len(events),
        "demand_impact_counts": dict(impact_counts),
        "demand_pressure_dates": demand_dates,
        "pricing_note": (
            "Google Events are useful for broad local demand discovery. Treat high-impact and weekend "
            "events as ADR uplift candidates when competitor rates and pickup pace agree."
        ),
    }


def cmd_events(args: argparse.Namespace) -> None:
    try:
        api_key = api_key_from(args)
        if not api_key:
            emit({"source": "serpapi", "tool": "google-events", "error": "Missing SERPAPI_API_KEY."}, exit_code=2)

        start = parse_iso_date(args.start_date, "start_date")
        end = parse_iso_date(args.end_date, "end_date")
        if end < start:
            emit({"error": "end_date must be on or after start_date"}, exit_code=2)

        params = {
            "engine": "google_events",
            "api_key": api_key,
            "q": event_query(args.address, start, end, args.keyword),
            "gl": args.gl or infer_country(args.address),
            "hl": args.hl,
        }
        if args.location:
            params["location"] = args.location
        if args.htichips:
            params["htichips"] = args.htichips

        data = http_get_json(params)
        if data.get("error"):
            emit({"source": "serpapi", "tool": "google-events", "error": data["error"]}, exit_code=1)

        raw_events = data.get("events_results") or []
        events = [normalize_event(event, start, end) for event in raw_events]
        if args.filter_date_range:
            events = [event for event in events if event["in_requested_range"] is not False]
        events = events[: max(1, args.limit)]

        emit(
            {
                "source": "serpapi",
                "tool": "google-events",
                "query": {
                    "address": args.address,
                    "start_date": start.isoformat(),
                    "end_date": end.isoformat(),
                    "q": params["q"],
                    "location": params.get("location"),
                    "gl": params["gl"],
                    "htichips": args.htichips,
                },
                "summary": summarize_events(events),
                "events": events,
                "search_metadata": data.get("search_metadata", {}),
            }
        )
    except Exception as exc:
        emit({"source": "serpapi", "tool": "google-events", "error": str(exc)}, exit_code=1)


def normalize_rate(rate: dict | None) -> dict | None:
    if not isinstance(rate, dict):
        return None
    return {
        "lowest": rate.get("lowest"),
        "extracted_lowest": rate.get("extracted_lowest"),
        "before_taxes_fees": rate.get("before_taxes_fees"),
        "extracted_before_taxes_fees": rate.get("extracted_before_taxes_fees"),
    }


def normalize_property(item: dict) -> dict:
    return {
        "type": item.get("type"),
        "name": item.get("name"),
        "description": item.get("description"),
        "link": item.get("link"),
        "sponsored": item.get("sponsored"),
        "hotel_class": item.get("hotel_class"),
        "extracted_hotel_class": item.get("extracted_hotel_class"),
        "overall_rating": item.get("overall_rating"),
        "reviews": item.get("reviews"),
        "gps_coordinates": item.get("gps_coordinates"),
        "rate_per_night": normalize_rate(item.get("rate_per_night")),
        "total_rate": normalize_rate(item.get("total_rate")),
        "amenities": item.get("amenities"),
        "nearby_places": item.get("nearby_places"),
    }


def numeric_rates(properties: list[dict]) -> list[float]:
    rates = []
    for item in properties:
        rate = item.get("rate_per_night") or {}
        value = rate.get("extracted_lowest") or rate.get("extracted_before_taxes_fees")
        if isinstance(value, (int, float)):
            rates.append(float(value))
    return sorted(rates)


def summarize_hotels(properties: list[dict]) -> dict:
    rates = numeric_rates(properties)
    median = rates[len(rates) // 2] if rates else None
    return {
        "property_count": len(properties),
        "median_rate_per_night": median,
        "min_rate_per_night": rates[0] if rates else None,
        "max_rate_per_night": rates[-1] if rates else None,
        "pricing_note": (
            "Use Google Hotels as a competitor-rate snapshot. Compare only similar property types, "
            "locations, quality, cancellation policy, and fees before changing ADR."
        ),
    }


def build_hotels_params(
    args: argparse.Namespace,
    api_key: str,
    check_in: dt.date,
    check_out: dt.date,
    search_mode: str | None = None,
) -> dict:
    search_mode = search_mode or hotels_search_modes(args)[0]
    default_property_type = "vacation rentals" if search_mode == "vacation-rentals" else args.property_type
    params = {
        "engine": "google_hotels",
        "api_key": api_key,
        "q": args.query or f"{default_property_type} in {city_query(args.address)}",
        "check_in_date": check_in.isoformat(),
        "check_out_date": check_out.isoformat(),
        "adults": str(args.adults),
        "children": str(args.children),
        "currency": args.currency,
        "gl": args.gl or infer_country(args.address),
        "hl": args.hl,
    }
    if args.children_ages:
        params["children_ages"] = args.children_ages
    if args.sort_by:
        params["sort_by"] = str(args.sort_by)
    if args.min_price is not None:
        params["min_price"] = str(args.min_price)
    if args.max_price is not None:
        params["max_price"] = str(args.max_price)
    if args.property_types:
        params["property_types"] = args.property_types
    if search_mode == "vacation-rentals":
        params["vacation_rentals"] = "true"
    if args.bedrooms is not None:
        params["bedrooms"] = str(args.bedrooms)
    if args.bathrooms is not None:
        params["bathrooms"] = str(args.bathrooms)

    return params


def hotels_search_modes(args: argparse.Namespace) -> list[str]:
    if args.vacation_rentals:
        return ["vacation-rentals"]
    if args.search_mode == "both":
        return ["hotels", "vacation-rentals"]
    return [args.search_mode]


def comp_source_for(search_mode: str) -> str:
    return "google-vacation-rentals" if search_mode == "vacation-rentals" else "google-hotels"


def fetch_hotels_for_stay(
    args: argparse.Namespace,
    api_key: str,
    check_in: dt.date,
    check_out: dt.date,
    search_mode: str,
) -> dict:
    params = build_hotels_params(args, api_key, check_in, check_out, search_mode)
    data = http_get_json(params)
    if data.get("error"):
        return {
            "date": check_in.isoformat(),
            "check_in_date": check_in.isoformat(),
            "check_out_date": check_out.isoformat(),
            "search_mode": search_mode,
            "comp_source": comp_source_for(search_mode),
            "error": data["error"],
            "properties": [],
            "summary": summarize_hotels([]),
            "search_metadata": data.get("search_metadata", {}),
        }

    properties = [normalize_property(item) for item in (data.get("properties") or [])]
    properties = properties[: max(1, args.limit)]
    for item in properties:
        item["search_mode"] = search_mode
        item["comp_source"] = comp_source_for(search_mode)
    return {
        "date": check_in.isoformat(),
        "check_in_date": check_in.isoformat(),
        "check_out_date": check_out.isoformat(),
        "search_mode": search_mode,
        "comp_source": comp_source_for(search_mode),
        "summary": summarize_hotels(properties),
        "properties": properties,
        "brands": data.get("brands", []),
        "search_metadata": data.get("search_metadata", {}),
    }


def fetch_hotels_for_modes(
    args: argparse.Namespace,
    api_key: str,
    check_in: dt.date,
    check_out: dt.date,
) -> dict:
    search_modes = hotels_search_modes(args)
    if len(search_modes) == 1:
        return fetch_hotels_for_stay(args, api_key, check_in, check_out, search_modes[0])

    mode_results = [
        fetch_hotels_for_stay(args, api_key, check_in, check_out, search_mode)
        for search_mode in search_modes
    ]
    properties = []
    for result in mode_results:
        properties.extend(result.get("properties") or [])

    return {
        "date": check_in.isoformat(),
        "check_in_date": check_in.isoformat(),
        "check_out_date": check_out.isoformat(),
        "search_mode": "both",
        "search_modes": search_modes,
        "summary": {
            **summarize_hotels(properties),
            "by_search_mode": {
                result["search_mode"]: result.get("summary", summarize_hotels([]))
                for result in mode_results
            },
            "partial_error_count": sum(1 for result in mode_results if result.get("error")),
        },
        "properties": properties,
        "mode_results": mode_results,
    }


def summarize_hotel_calendar(days: list[dict]) -> dict:
    medians = [
        day["summary"]["median_rate_per_night"]
        for day in days
        if isinstance(day.get("summary"), dict)
        and isinstance(day["summary"].get("median_rate_per_night"), (int, float))
    ]
    all_rates = []
    for day in days:
        all_rates.extend(numeric_rates(day.get("properties") or []))
    all_rates.sort()
    medians.sort()

    return {
        "day_count": len(days),
        "error_count": sum(1 for day in days if day.get("error")),
        "median_of_daily_medians": medians[len(medians) // 2] if medians else None,
        "min_daily_median": medians[0] if medians else None,
        "max_daily_median": medians[-1] if medians else None,
        "overall_min_rate_per_night": all_rates[0] if all_rates else None,
        "overall_max_rate_per_night": all_rates[-1] if all_rates else None,
        "pricing_note": (
            "Daily Google Hotels snapshots should be compared date by date. Use higher daily medians "
            "as possible compression signals, but account for property similarity and fees."
        ),
    }


def cmd_hotels(args: argparse.Namespace) -> None:
    try:
        api_key = api_key_from(args)
        if not api_key:
            emit({"source": "serpapi", "tool": "google-hotels", "error": "Missing SERPAPI_API_KEY."}, exit_code=2)

        search_modes = hotels_search_modes(args)
        search_mode_label = "both" if len(search_modes) > 1 else search_modes[0]
        check_in = parse_iso_date(args.check_in_date, "check_in_date")
        if args.pricing_horizon is not None:
            if args.pricing_horizon < 1 or args.pricing_horizon > 31:
                emit({"error": "pricing_horizon must be between 1 and 31"}, exit_code=2)

            days = []
            for offset in range(args.pricing_horizon):
                day_check_in = check_in + dt.timedelta(days=offset)
                day_check_out = day_check_in + dt.timedelta(days=1)
                days.append(fetch_hotels_for_modes(args, api_key, day_check_in, day_check_out))

            emit(
                {
                    "source": "serpapi",
                    "tool": "google-hotels",
                    "mode": "daily-pricing-horizon",
                    "query": {
                        "address": args.address,
                        "q": args.query or f"{args.property_type} in {city_query(args.address)}",
                        "start_check_in_date": check_in.isoformat(),
                        "pricing_horizon": args.pricing_horizon,
                        "adults": args.adults,
                        "children": args.children,
                        "currency": args.currency,
                        "search_mode": search_mode_label,
                        "search_modes": search_modes,
                        "includes_vacation_rentals": "vacation-rentals" in search_modes,
                    },
                    "summary": summarize_hotel_calendar(days),
                    "daily": days,
                }
            )

        if not args.check_out_date:
            emit({"error": "check_out_date is required unless pricing_horizon is provided"}, exit_code=2)

        check_out = parse_iso_date(args.check_out_date, "check_out_date")
        if check_out <= check_in:
            emit({"error": "check_out_date must be after check_in_date"}, exit_code=2)

        stay = fetch_hotels_for_modes(args, api_key, check_in, check_out)
        if stay.get("error"):
            emit({"source": "serpapi", "tool": "google-hotels", "error": stay["error"]}, exit_code=1)

        emit(
            {
                "source": "serpapi",
                "tool": "google-hotels",
                "mode": "single-stay",
                "query": {
                    "address": args.address,
                    "q": args.query or f"{args.property_type} in {city_query(args.address)}",
                    "check_in_date": check_in.isoformat(),
                    "check_out_date": check_out.isoformat(),
                    "adults": args.adults,
                    "children": args.children,
                    "currency": args.currency,
                    "search_mode": search_mode_label,
                    "search_modes": search_modes,
                    "includes_vacation_rentals": "vacation-rentals" in search_modes,
                },
                "summary": stay["summary"],
                "properties": stay["properties"],
                "brands": stay.get("brands", []),
                "mode_results": stay.get("mode_results"),
                "search_metadata": stay.get("search_metadata", {}),
            }
        )
    except Exception as exc:
        emit({"source": "serpapi", "tool": "google-hotels", "error": str(exc)}, exit_code=1)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="RevNest SerpApi Google Events and Google Hotels tool")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("events", help="Search Google Events through SerpApi")
    p.add_argument("--address", required=True)
    p.add_argument("--start-date", required=True)
    p.add_argument("--end-date", required=True)
    p.add_argument("--api-key")
    p.add_argument("--keyword")
    p.add_argument("--location")
    p.add_argument("--gl")
    p.add_argument("--hl", default="en")
    p.add_argument("--htichips", help="Optional Google Events filter, e.g. date:week or date:month")
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--filter-date-range", action="store_true")
    p.set_defaults(func=cmd_events)

    p = sub.add_parser("hotels", help="Search Google Hotels through SerpApi")
    p.add_argument("--address", required=True)
    p.add_argument("--check-in-date", required=True)
    p.add_argument("--check-out-date")
    p.add_argument("--pricing-horizon", type=int, help="Run one-night Google Hotels searches for N consecutive days")
    p.add_argument("--api-key")
    p.add_argument("--query")
    p.add_argument("--property-type", default="hotels")
    p.add_argument(
        "--search-mode",
        choices=["hotels", "vacation-rentals", "both"],
        default="hotels",
        help="Use hotels for hotel comps, vacation-rentals for rental-style results, or both to query both sources",
    )
    p.add_argument("--adults", type=int, default=2)
    p.add_argument("--children", type=int, default=0)
    p.add_argument("--children-ages")
    p.add_argument("--currency", default="USD")
    p.add_argument("--gl")
    p.add_argument("--hl", default="en")
    p.add_argument("--sort-by", type=int, help="3 lowest price, 8 highest rating, 13 most reviewed")
    p.add_argument("--min-price", type=int)
    p.add_argument("--max-price", type=int)
    p.add_argument("--property-types")
    p.add_argument("--vacation-rentals", action="store_true", help="Backward-compatible alias for --search-mode vacation-rentals")
    p.add_argument("--bedrooms", type=int)
    p.add_argument("--bathrooms", type=int)
    p.add_argument("--limit", type=int, default=20)
    p.set_defaults(func=cmd_hotels)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
