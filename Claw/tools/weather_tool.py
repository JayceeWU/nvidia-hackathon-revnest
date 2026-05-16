#!/usr/bin/env python3
"""
RevNest weather tool.

This tool keeps only weather-related lookup and demand-signal logic from the
former revenue tool bundle. It uses Python standard-library modules only and
returns JSON for agent/tool-calling workflows.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import random
import re
import ssl
import urllib.parse
import urllib.request
from collections import Counter

US_STATE_NAME_TO_CODE = {
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
US_STATE_CODE_TO_NAME = {code: name.title() for name, code in US_STATE_NAME_TO_CODE.items()}
COUNTRY_PARTS = {"us", "usa", "u.s.", "u.s.a.", "united states", "united states of america"}


def emit(payload: dict, exit_code: int = 0) -> None:
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    raise SystemExit(exit_code)


def today_iso() -> str:
    return dt.date.today().isoformat()


def stable_random(seed: str) -> random.Random:
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    return random.Random(int(digest[:16], 16))


def http_get_json(url: str, timeout: int = 12) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "RevNest-Weather-Agent/0.1"})
    context = ssl.create_default_context()
    with urllib.request.urlopen(req, timeout=timeout, context=context) as response:
        return json.loads(response.read().decode("utf-8"))


def parse_date(value: str | None) -> dt.date:
    if not value:
        return dt.date.today()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%b %d, %Y"):
        try:
            return dt.datetime.strptime(value.strip(), fmt).date()
        except ValueError:
            pass
    return dt.date.today()


def parse_iso_date(value: str, field_name: str) -> dt.date:
    try:
        return dt.date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} must use YYYY-MM-DD format") from exc


def dedupe(values: list[str]) -> list[str]:
    seen = set()
    output = []
    for value in values:
        normalized = re.sub(r"\s+", " ", value).strip()
        key = normalized.lower()
        if normalized and key not in seen:
            seen.add(key)
            output.append(normalized)
    return output


def normalize_state(value: str | None) -> tuple[str | None, str | None]:
    if not value:
        return None, None
    stripped = value.strip()
    lowered = stripped.lower().replace(".", "")
    if lowered in US_STATE_NAME_TO_CODE:
        code = US_STATE_NAME_TO_CODE[lowered]
        return US_STATE_CODE_TO_NAME[code], code
    upper = stripped.upper()
    if upper in US_STATE_CODE_TO_NAME:
        return US_STATE_CODE_TO_NAME[upper], upper
    return stripped, None


def parse_location_hint(location: str) -> dict:
    parts = [part.strip() for part in location.split(",") if part.strip()]
    if not parts:
        return {"city": location.strip(), "state_name": None, "state_code": None}

    working = list(parts)
    if working and working[-1].lower().replace(".", "") in COUNTRY_PARTS:
        working.pop()

    state_part = None
    city_part = None
    if len(working) >= 2:
        state_part = working[-1]
        city_part = working[-2]
    elif working:
        city_part = working[0]

    city = re.sub(r"^\d+\s+", "", city_part or "").strip()
    state_name, state_code = normalize_state(state_part)
    return {"city": city or location.strip(), "state_name": state_name, "state_code": state_code}


def state_matches(result: dict, state_name: str | None, state_code: str | None) -> bool:
    if not state_name and not state_code:
        return False
    admin1 = str(result.get("admin1") or "").strip().lower()
    admin1_code = str(result.get("admin1_code") or result.get("admin2_code") or "").strip().upper()
    if state_name and admin1 == state_name.lower():
        return True
    if state_code and admin1_code.endswith(state_code):
        return True
    return False


def geocode_query(query_text: str, state_name: str | None = None, state_code: str | None = None) -> dict | None:
    query = urllib.parse.quote(query_text)
    url = (
        "https://geocoding-api.open-meteo.com/v1/search"
        f"?name={query}&count=10&language=en&format=json&countryCode=US"
    )
    data = http_get_json(url)
    results = data.get("results") or []
    if not results:
        return None
    result = next((item for item in results if state_matches(item, state_name, state_code)), results[0])
    name_parts = [result.get("name"), result.get("admin1"), result.get("country")]
    return {
        "name": ", ".join(part for part in name_parts if part),
        "latitude": result["latitude"],
        "longitude": result["longitude"],
        "timezone": result.get("timezone", "auto"),
        "geocode_query": query_text,
    }


def geocode_location(location: str) -> dict:
    hint = parse_location_hint(location)
    city = hint["city"]
    state_name = hint["state_name"]
    state_code = hint["state_code"]
    candidates = [location]
    if city and state_name:
        candidates.append(f"{city}, {state_name}")
    if city and state_code:
        candidates.append(f"{city}, {state_code}")
    if city:
        candidates.append(city)

    attempted = []
    for candidate in dedupe(candidates):
        attempted.append(candidate)
        geo = geocode_query(candidate, state_name=state_name, state_code=state_code)
        if geo:
            geo["geocode_attempts"] = attempted
            return geo
    raise RuntimeError(f"No geocoding result for {location}; tried {', '.join(attempted)}")


def geocode_us_zip(zip_code: str) -> dict:
    normalized = str(zip_code).strip()
    if not re.fullmatch(r"\d{5}(?:-\d{4})?", normalized):
        raise ValueError("zip_code must be a 5-digit US ZIP code or ZIP+4")
    query = urllib.parse.quote(normalized[:5])
    url = (
        "https://geocoding-api.open-meteo.com/v1/search"
        f"?name={query}&count=10&language=en&format=json&countryCode=US"
    )
    data = http_get_json(url)
    results = data.get("results") or []
    if not results:
        raise RuntimeError(f"No Open-Meteo geocoding result for US ZIP {normalized}")

    result = next(
        (
            item
            for item in results
            if str(item.get("postcodes", "")).find(normalized[:5]) >= 0
            or str(item.get("name", "")).strip() == normalized[:5]
        ),
        results[0],
    )
    name_parts = [result.get("name"), result.get("admin1"), result.get("country_code")]
    return {
        "name": ", ".join(part for part in name_parts if part),
        "latitude": result["latitude"],
        "longitude": result["longitude"],
        "timezone": result.get("timezone", "auto"),
        "zip_code": normalized[:5],
    }


def weather_code_label(code: int | None) -> str:
    labels = {
        0: "clear",
        1: "mainly_clear",
        2: "partly_cloudy",
        3: "overcast",
        45: "fog",
        48: "depositing_rime_fog",
        51: "light_drizzle",
        53: "moderate_drizzle",
        55: "dense_drizzle",
        56: "freezing_drizzle",
        57: "freezing_drizzle",
        61: "slight_rain",
        63: "moderate_rain",
        65: "heavy_rain",
        66: "freezing_rain",
        67: "freezing_rain",
        71: "slight_snow",
        73: "moderate_snow",
        75: "heavy_snow",
        77: "snow_grains",
        80: "slight_rain_showers",
        81: "moderate_rain_showers",
        82: "violent_rain_showers",
        85: "snow_showers",
        86: "heavy_snow_showers",
        95: "thunderstorm",
        96: "thunderstorm_hail",
        99: "thunderstorm_hail",
    }
    return labels.get(code, "unknown")


def weather_demand_assessment(
    date_text: str,
    temp_max_f: float | None,
    apparent_max_f: float | None,
    precipitation_mm: float | None,
    precip_probability: float | None,
    snowfall_cm: float | None,
    wind_mph: float | None,
    wind_gust_mph: float | None,
    weather_code: int | None,
    sunshine_hours: float | None,
) -> dict:
    date = parse_date(date_text)
    weekend = date.weekday() >= 4
    temp = apparent_max_f if apparent_max_f is not None else temp_max_f
    score = 0
    reasons = []

    if temp is not None:
        if 68 <= temp <= 84:
            score += 2
            reasons.append("comfortable outdoor temperature")
        elif temp < 45 or temp >= 95:
            score -= 2
            reasons.append("uncomfortable temperature")
        elif temp < 55 or temp >= 90:
            score -= 1
            reasons.append("marginal outdoor temperature")

    rain = precipitation_mm or 0
    probability = precip_probability or 0
    snow = snowfall_cm or 0
    wind = wind_mph or 0
    gust = wind_gust_mph or 0
    sunshine = sunshine_hours or 0
    label = weather_code_label(weather_code)

    if rain >= 25 or probability >= 80 or label in {"heavy_rain", "violent_rain_showers", "thunderstorm", "thunderstorm_hail"}:
        score -= 3
        reasons.append("heavy rain or storm risk")
    elif rain >= 8 or probability >= 55:
        score -= 2
        reasons.append("meaningful rain risk")
    elif rain <= 2 and probability <= 35:
        score += 1
        reasons.append("low rain risk")

    if snow >= 5:
        score -= 2
        reasons.append("snow may disrupt travel")
    if wind >= 25 or gust >= 35:
        score -= 2
        reasons.append("high wind risk")
    elif wind <= 14 and gust <= 24:
        score += 1
        reasons.append("light wind")
    if sunshine >= 6:
        score += 1
        reasons.append("good sunshine")
    if weekend:
        score += 1
        reasons.append("weekend leisure timing")

    if score >= 4:
        demand_impact = "up"
        pricing_signal = "consider ADR uplift if market and event signals agree"
    elif score <= -3:
        demand_impact = "down"
        pricing_signal = "avoid aggressive increases; consider softer leisure demand"
    elif score < 0:
        demand_impact = "slightly_down"
        pricing_signal = "use conservative pricing unless events create compression"
    else:
        demand_impact = "neutral"
        pricing_signal = "weather does not require a major price adjustment"

    return {
        "demand_impact": demand_impact,
        "weather_score": score,
        "pricing_signal": pricing_signal,
        "reasons": reasons[:5],
    }


def cmd_weather_demand(args: argparse.Namespace) -> None:
    try:
        start = parse_iso_date(args.start_date, "start_date")
        end = parse_iso_date(args.end_date, "end_date")
        if end < start:
            emit({"error": "end_date must be on or after start_date"}, exit_code=2)
        if (end - start).days > 30:
            emit({"error": "date range is limited to 31 days for a pricing decision window"}, exit_code=2)

        geo = geocode_us_zip(args.zip_code)
        daily_vars = [
            "weather_code",
            "temperature_2m_max",
            "temperature_2m_min",
            "apparent_temperature_max",
            "precipitation_sum",
            "rain_sum",
            "snowfall_sum",
            "precipitation_probability_max",
            "wind_speed_10m_max",
            "wind_gusts_10m_max",
            "uv_index_max",
            "sunshine_duration",
        ]
        params = urllib.parse.urlencode(
            {
                "latitude": geo["latitude"],
                "longitude": geo["longitude"],
                "daily": ",".join(daily_vars),
                "temperature_unit": "fahrenheit",
                "wind_speed_unit": "mph",
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
                "timezone": "auto",
            }
        )
        data = http_get_json(f"https://api.open-meteo.com/v1/forecast?{params}")
        raw = data.get("daily", {})
        dates = raw.get("time", [])
        daily = []
        impact_counts = Counter()

        for index, date_text in enumerate(dates):
            def value(name: str):
                values = raw.get(name) or []
                return values[index] if index < len(values) else None

            sunshine_seconds = value("sunshine_duration")
            sunshine_hours = round(sunshine_seconds / 3600, 2) if sunshine_seconds is not None else None
            weather_code = value("weather_code")
            assessment = weather_demand_assessment(
                date_text=date_text,
                temp_max_f=value("temperature_2m_max"),
                apparent_max_f=value("apparent_temperature_max"),
                precipitation_mm=value("precipitation_sum"),
                precip_probability=value("precipitation_probability_max"),
                snowfall_cm=value("snowfall_sum"),
                wind_mph=value("wind_speed_10m_max"),
                wind_gust_mph=value("wind_gusts_10m_max"),
                weather_code=weather_code,
                sunshine_hours=sunshine_hours,
            )
            impact_counts[assessment["demand_impact"]] += 1
            daily.append(
                {
                    "date": date_text,
                    "is_weekend": parse_date(date_text).weekday() >= 4,
                    "weather_code": weather_code,
                    "weather_label": weather_code_label(weather_code),
                    "temperature_max_f": value("temperature_2m_max"),
                    "temperature_min_f": value("temperature_2m_min"),
                    "apparent_temperature_max_f": value("apparent_temperature_max"),
                    "precipitation_mm": value("precipitation_sum"),
                    "rain_mm": value("rain_sum"),
                    "snowfall_cm": value("snowfall_sum"),
                    "precipitation_probability_max_pct": value("precipitation_probability_max"),
                    "wind_speed_max_mph": value("wind_speed_10m_max"),
                    "wind_gust_max_mph": value("wind_gusts_10m_max"),
                    "uv_index_max": value("uv_index_max"),
                    "sunshine_hours": sunshine_hours,
                    **assessment,
                }
            )

        if not daily:
            emit({"error": "Open-Meteo returned no daily forecast rows", "zip_code": args.zip_code}, exit_code=1)

        up_days = impact_counts["up"]
        down_days = impact_counts["down"] + impact_counts["slightly_down"]
        if up_days > down_days:
            overall_signal = "weather_supports_higher_leisure_demand"
        elif down_days > up_days:
            overall_signal = "weather_may_dampen_leisure_demand"
        else:
            overall_signal = "mixed_or_neutral_weather_signal"

        emit(
            {
                "source": "open_meteo",
                "tool": "weather-demand",
                "zip_code": geo["zip_code"],
                "resolved_location": geo["name"],
                "latitude": geo["latitude"],
                "longitude": geo["longitude"],
                "date_range": {"start_date": start.isoformat(), "end_date": end.isoformat()},
                "summary": {
                    "overall_signal": overall_signal,
                    "days": len(daily),
                    "impact_counts": dict(impact_counts),
                    "revenue_management_note": (
                        "Use weather as a demand modifier, not the sole pricing driver. "
                        "Combine with events, pickup pace, occupancy, and competitor rates."
                    ),
                },
                "daily": daily,
            }
        )
    except Exception as exc:
        emit({"source": "open_meteo", "tool": "weather-demand", "error": str(exc)}, exit_code=1)


def simulated_weather(location: str, days: int, start: dt.date | None = None, fallback_reason: str | None = None) -> dict:
    start = start or dt.date.today()
    rng = stable_random(f"weather:{location}:{start.isoformat()}:{days}")
    daily = []
    for offset in range(days):
        date = start + dt.timedelta(days=offset)
        rain = round(max(0, rng.gauss(2.5, 4.0)), 1)
        high = round(rng.uniform(58, 76), 1)
        wind = round(rng.uniform(4, 22), 1)
        demand_impact = "neutral"
        if rain > 12 or wind > 20:
            demand_impact = "down"
        elif date.weekday() >= 4 and rain < 4:
            demand_impact = "up"
        daily.append(
            {
                "date": date.isoformat(),
                "temperature_max_f": high,
                "precipitation_mm": rain,
                "wind_speed_mph": wind,
                "demand_impact": demand_impact,
            }
        )
    return {
        "source": "simulated_weather_fallback",
        "fallback": True,
        "fallback_reason": fallback_reason,
        "location": location,
        "daily": daily,
        "note": "Weather API lookup failed, so deterministic fallback weather was generated for continuity.",
    }


def cmd_weather(args: argparse.Namespace) -> None:
    start = parse_iso_date(args.start_date, "start_date") if args.start_date else None
    end = parse_iso_date(args.end_date, "end_date") if args.end_date else None
    if start and end and end < start:
        emit({"source": "open_meteo", "tool": "weather", "error": "end_date must be on or after start_date"}, exit_code=2)
    if (start and not end) or (end and not start):
        emit({"source": "open_meteo", "tool": "weather", "error": "provide both --start-date and --end-date"}, exit_code=2)

    days = (end - start).days + 1 if start and end else max(1, min(args.days, 16))
    try:
        if args.latitude is not None and args.longitude is not None:
            geo = {
                "name": args.location or "provided coordinates",
                "latitude": args.latitude,
                "longitude": args.longitude,
                "timezone": "auto",
            }
        else:
            geo = geocode_location(args.location)
        request_params = {
            "latitude": geo["latitude"],
            "longitude": geo["longitude"],
            "daily": "temperature_2m_max,precipitation_sum,wind_speed_10m_max",
            "temperature_unit": "fahrenheit",
            "wind_speed_unit": "mph",
            "timezone": "auto",
        }
        if start and end:
            request_params["start_date"] = start.isoformat()
            request_params["end_date"] = end.isoformat()
        else:
            request_params["forecast_days"] = days
        params = urllib.parse.urlencode(request_params)
        data = http_get_json(f"https://api.open-meteo.com/v1/forecast?{params}")
        daily = []
        raw = data["daily"]
        for index, date in enumerate(raw["time"]):
            rain = raw["precipitation_sum"][index]
            wind = raw["wind_speed_10m_max"][index]
            demand_impact = "neutral"
            if rain >= 12 or wind >= 22:
                demand_impact = "down"
            elif parse_date(date).weekday() >= 4 and rain <= 3:
                demand_impact = "up"
            daily.append(
                {
                    "date": date,
                    "temperature_max_f": raw["temperature_2m_max"][index],
                    "precipitation_mm": rain,
                    "wind_speed_mph": wind,
                    "demand_impact": demand_impact,
                }
            )
        emit(
            {
                "source": "open_meteo",
                "tool": "weather",
                "location": geo["name"],
                "resolved_location": geo["name"],
                "latitude": geo["latitude"],
                "longitude": geo["longitude"],
                "date_range": {
                    "start_date": daily[0]["date"] if daily else None,
                    "end_date": daily[-1]["date"] if daily else None,
                },
                "geocode_query": geo.get("geocode_query"),
                "geocode_attempts": geo.get("geocode_attempts"),
                "daily": daily,
            }
        )
    except Exception as exc:
        fallback = simulated_weather(args.location or "unknown", days, start=start, fallback_reason=str(exc))
        fallback["tool"] = "weather"
        emit(fallback)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="RevNest weather lookup tool")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("weather", help="Fetch or simulate weather demand signals")
    p.add_argument("--location", default="Santa Cruz, CA")
    p.add_argument("--latitude", type=float)
    p.add_argument("--longitude", type=float)
    p.add_argument("--days", type=int, default=7)
    p.add_argument("--start-date", help="YYYY-MM-DD; when provided with --end-date, weather aligns to pricing dates")
    p.add_argument("--end-date", help="YYYY-MM-DD; when provided with --start-date, weather aligns to pricing dates")
    p.set_defaults(func=cmd_weather)

    p = sub.add_parser("weather-demand", help="Fetch Open-Meteo weather demand signals by US ZIP and date range")
    p.add_argument("--zip-code", required=True, help="US ZIP code, e.g. 95060")
    p.add_argument("--start-date", required=True, help="YYYY-MM-DD")
    p.add_argument("--end-date", required=True, help="YYYY-MM-DD")
    p.set_defaults(func=cmd_weather_demand)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
