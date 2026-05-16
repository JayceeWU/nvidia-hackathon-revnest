#!/usr/bin/env python3
"""Deterministic occupancy-rate estimator for RevNest pricing decisions.

The agent owns evidence collection. This script owns repeatable arithmetic that
turns supply, demand, comp, booking-window, and historical occupancy signals
into per-date occupancy estimates.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import sys
from typing import Any


ESTIMATOR_VERSION = "1.0.0"
FORMULA_CODE = """
base = historical_occupancy or profile_occupancy or default_base
supply_index = clamp(0.50 + tight_supply_adjustments - oversupply_adjustments, 0, 1)
demand_index = clamp(0.50 + event + holiday + tourism + weather + booking_window + weekend + compression, 0, 1)
estimated_occupancy = clamp(base + (demand_index - 0.50) * 0.35 + (supply_index - 0.50) * 0.25 + property_fit, 0.05, 0.98)
""".strip()


def lower_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False).lower()
    return str(value).lower()


def as_float(value: Any, default: float | None = None) -> float | None:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value) if math.isfinite(float(value)) else default
    text = str(value).strip().replace("$", "").replace(",", "")
    if not text:
        return default
    is_percent = text.endswith("%")
    if is_percent:
        text = text[:-1].strip()
    try:
        parsed = float(text)
    except ValueError:
        return default
    if is_percent or parsed > 1.5:
        parsed /= 100.0
    return parsed if math.isfinite(parsed) else default


def as_int(value: Any, default: int | None = None) -> int | None:
    parsed = as_float(value)
    if parsed is None:
        return default
    return int(round(parsed))


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def first_value(*values: Any) -> Any:
    for value in values:
        if value not in (None, ""):
            return value
    return None


def value_for_date(source: Any, date_key: str) -> Any:
    if source is None:
        return {}
    if isinstance(source, dict):
        if source.get(date_key) is not None:
            return source[date_key]
        for key in ("by_date", "per_date", "daily", "dates"):
            nested = source.get(key)
            if isinstance(nested, dict) and nested.get(date_key) is not None:
                return nested[date_key]
            if isinstance(nested, list):
                for item in nested:
                    if isinstance(item, dict) and item.get("date") == date_key:
                        return item
        return source
    if isinstance(source, list):
        for item in source:
            if isinstance(item, dict) and item.get("date") == date_key:
                return item
    return {}


def parse_dates(payload: dict[str, Any]) -> list[str]:
    raw_dates = payload.get("dates") or payload.get("price_dates") or payload.get("calendar") or []
    dates: list[str] = []
    if isinstance(raw_dates, list):
        for item in raw_dates:
            if isinstance(item, str):
                dates.append(dt.date.fromisoformat(item).isoformat())
            elif isinstance(item, dict) and item.get("date"):
                dates.append(dt.date.fromisoformat(str(item["date"])).isoformat())
    if dates:
        return dates

    start = payload.get("start_date")
    horizon = as_int(payload.get("pricing_horizon"), 0) or 0
    if not start or horizon <= 0:
        raise ValueError("Expected dates or start_date plus pricing_horizon.")
    start_date = dt.date.fromisoformat(str(start))
    return [(start_date + dt.timedelta(days=index)).isoformat() for index in range(horizon)]


def normalize_rate(value: Any) -> float | None:
    parsed = as_float(value)
    if parsed is None:
        return None
    return clamp(parsed)


def historical_occupancy(payload: dict[str, Any], date_key: str) -> float | None:
    for source_key in ("historical_occupancy", "rms_occupancy", "estimated_occupancy"):
        source = payload.get(source_key)
        value = value_for_date(source, date_key)
        if isinstance(value, dict):
            parsed = normalize_rate(first_value(value.get("occupancy"), value.get("occupancy_rate"), value.get("rate")))
        else:
            parsed = normalize_rate(value)
        if parsed is not None:
            return parsed
    profile = payload.get("property_profile") if isinstance(payload.get("property_profile"), dict) else {}
    return normalize_rate(first_value(profile.get("historical_occupancy"), profile.get("occupancy"), profile.get("occupancy_rate")))


def supply_index(signals: dict[str, Any], stats: dict[str, Any], profile: dict[str, Any]) -> tuple[float, list[str]]:
    index = 0.50
    factors: list[str] = []
    text = " ".join(lower_text(value) for value in (signals, stats))
    comp_count = as_int(first_value(stats.get("comp_count"), stats.get("available_comp_count"), signals.get("available_comp_count")))
    available_units = as_int(first_value(signals.get("available_units"), signals.get("available_rooms"), stats.get("available_units")))
    room_count = as_int(first_value(profile.get("room_count"), profile.get("rooms")))

    if any(token in text for token in ("sold out", "limited supply", "low supply", "scarce", "compression")):
        index += 0.25
        factors.append("tight supply/compression language")
    if any(token in text for token in ("high supply", "many available", "oversupply", "ample supply")):
        index -= 0.25
        factors.append("ample competing supply")
    if comp_count is not None:
        if comp_count <= 3:
            index += 0.10
            factors.append("few comparable listings available")
        elif comp_count >= 15:
            index -= 0.10
            factors.append("many comparable listings available")
    if available_units is not None:
        if available_units <= 5:
            index += 0.12
            factors.append("low available-unit count")
        elif available_units >= 25:
            index -= 0.10
            factors.append("high available-unit count")
    if room_count is not None and room_count <= 5:
        index += 0.06
        factors.append("scarce subject inventory")
    return clamp(index), factors


def demand_index(date_key: str, signals: dict[str, Any], stats: dict[str, Any], profile: dict[str, Any]) -> tuple[float, list[str]]:
    index = 0.50
    factors: list[str] = []
    event_text = lower_text(first_value(signals.get("events"), signals.get("event_summary"), signals.get("event")))
    holiday_text = lower_text(first_value(signals.get("holidays"), signals.get("holiday"), signals.get("school_breaks")))
    tourism_text = lower_text(first_value(signals.get("tourism"), signals.get("tourism_demand"), signals.get("seasonality"), signals.get("weather_tourism")))
    weather_text = lower_text(first_value(signals.get("weather"), signals.get("weather_summary"), signals.get("weather_tourism")))
    compression_text = lower_text(first_value(signals.get("compression"), signals.get("pickup"), signals.get("market_demand"), stats.get("compression")))
    rate_text = lower_text(stats)
    combined_demand_text = " ".join([event_text, holiday_text, tourism_text, weather_text, compression_text, rate_text])

    if any(token in event_text + " " + compression_text for token in ("major event", "citywide", "graduation", "festival", "sold out", "surge")):
        index += 0.18
        factors.append("major event demand")
    elif any(token in event_text for token in ("event", "concert", "game", "conference")):
        index += 0.10
        factors.append("local event demand")
    if any(token in holiday_text for token in ("holiday", "long weekend", "school break", "public holiday")):
        index += 0.08
        factors.append("holiday or long-weekend demand")
    if any(token in tourism_text for token in ("peak", "summer", "busy season", "strong tourism", "high tourism")):
        index += 0.10
        factors.append("strong tourism/seasonality")
    if any(token in tourism_text + " " + compression_text for token in ("off season", "low tourism", "weak tourism", "soft demand")):
        index -= 0.12
        factors.append("soft tourism/demand")
    if any(token in weather_text for token in ("storm", "heavy rain", "travel disruption", "high wind")):
        index -= 0.10
        factors.append("weather disruption risk")
    elif any(token in weather_text for token in ("sunny", "clear", "warm", "beach weather")):
        index += 0.04
        factors.append("favorable weather")

    booking_window = as_int(first_value(signals.get("booking_window_days"), signals.get("days_to_arrival"), profile.get("booking_window_days")))
    if booking_window is not None:
        if booking_window <= 7 and any(token in compression_text for token in ("high occupancy", "pickup", "compression", "sold out")):
            index += 0.08
            factors.append("short booking window with pickup")
        elif booking_window <= 7:
            index -= 0.04
            factors.append("short booking window without pickup")
        elif booking_window >= 60:
            index += 0.03
            factors.append("long booking window")

    try:
        weekday = dt.date.fromisoformat(date_key).weekday()
    except ValueError:
        weekday = -1
    if weekday in (4, 5):
        index += 0.05
        factors.append("weekend leisure pattern")

    median = as_float(first_value(stats.get("median_rate"), stats.get("median"), stats.get("median_price")))
    p75 = as_float(first_value(stats.get("p75_rate"), stats.get("p75")))
    if median and p75 and p75 > median * 1.15:
        index += 0.05
        factors.append("upper-quartile comp-rate pressure")
    if any(token in combined_demand_text for token in ("compressed", "compression", "high demand")):
        index += 0.06
        factors.append("compression demand signal")
    return clamp(index), factors


def property_fit_adjustment(profile: dict[str, Any], property_type: str) -> tuple[float, list[str]]:
    text = lower_text(profile)
    factors: list[str] = []
    adjustment = 0.0
    if property_type == "hotel":
        room_count = as_int(first_value(profile.get("room_count"), profile.get("rooms")))
        if room_count is not None and room_count <= 10:
            adjustment += 0.03
            factors.append("limited hotel room-type inventory")
        if any(token in text for token in ("suite", "premium", "ocean", "view", "beachfront")):
            adjustment += 0.03
            factors.append("premium hotel room-type fit")
    else:
        capacity = as_int(first_value(profile.get("capacity"), profile.get("guests")))
        bedrooms = as_int(first_value(profile.get("bedrooms"), profile.get("bed")))
        if capacity is not None and capacity >= 6:
            adjustment += 0.03
            factors.append("large-group capacity")
        if bedrooms is not None and bedrooms >= 3:
            adjustment += 0.02
            factors.append("multi-bedroom fit")
        if any(token in text for token in ("parking", "kitchen", "washer", "laundry", "workspace", "view")):
            adjustment += 0.02
            factors.append("amenities match guest priorities")
    return adjustment, factors


def compression_level(occupancy: float, supply: float, demand: float) -> str:
    if occupancy >= 0.90 or (supply >= 0.75 and demand >= 0.72):
        return "compressed"
    if occupancy >= 0.76 or demand >= 0.68:
        return "elevated"
    if occupancy <= 0.45 or demand <= 0.35:
        return "low"
    return "normal"


def confidence_level(base_source: str, stats: dict[str, Any], signals: dict[str, Any]) -> str:
    score = 0
    if base_source == "historical":
        score += 2
    if as_int(stats.get("comp_count"), 0) and (as_int(stats.get("comp_count"), 0) or 0) >= 5:
        score += 1
    if signals:
        score += 1
    if score >= 3:
        return "high"
    if score >= 1:
        return "medium"
    return "low"


def calculate(payload: dict[str, Any]) -> dict[str, Any]:
    property_type = "hotel" if lower_text(payload.get("property_type")) == "hotel" else "airbnb"
    profile = payload.get("property_profile") if isinstance(payload.get("property_profile"), dict) else {}
    default_base = 0.65 if property_type == "hotel" else 0.58
    dates = parse_dates(payload)
    daily: list[dict[str, Any]] = []
    estimated: dict[str, float] = {}

    supply_signals = payload.get("supply_signals") or payload.get("market_signals") or {}
    demand_signals = payload.get("demand_signals") or payload.get("market_signals") or {}
    competitor_stats = payload.get("competitor_stats") or {}

    for date_key in dates:
        supply_for_date = value_for_date(supply_signals, date_key)
        if not isinstance(supply_for_date, dict):
            supply_for_date = {}
        demand_for_date = value_for_date(demand_signals, date_key)
        if not isinstance(demand_for_date, dict):
            demand_for_date = {}
        stats = value_for_date(competitor_stats, date_key)
        if not isinstance(stats, dict):
            stats = {}

        merged_demand = dict(demand_for_date)
        for target_key, source_key in (("events", "events"), ("holidays", "holidays"), ("weather_tourism", "weather_tourism")):
            value = value_for_date(payload.get(source_key), date_key)
            if value not in (None, "", {}, []):
                merged_demand[target_key] = value
        booking_value = first_value(merged_demand.get("booking_window_days"), value_for_date(payload.get("booking_window"), date_key))
        if booking_value not in (None, "", {}, []):
            merged_demand["booking_window_days"] = booking_value
        historical = historical_occupancy(payload, date_key)
        base = historical if historical is not None else default_base
        base_source = "historical" if historical is not None else "default"
        supply, supply_factors = supply_index(supply_for_date, stats, profile)
        demand, demand_factors = demand_index(date_key, merged_demand, stats, profile)
        fit_adjustment, fit_factors = property_fit_adjustment(profile, property_type)
        occupancy = clamp(base + (demand - 0.50) * 0.35 + (supply - 0.50) * 0.25 + fit_adjustment, 0.05, 0.98)
        confidence = confidence_level(base_source, stats, {**supply_for_date, **merged_demand})
        factors = (demand_factors + supply_factors + fit_factors)[:7]
        if historical is not None:
            factors.insert(0, "historical/RMS occupancy anchor")

        rounded = round(occupancy, 4)
        estimated[date_key] = rounded
        daily.append(
            {
                "date": date_key,
                "estimated_occupancy": rounded,
                "supply_index": round(supply, 4),
                "demand_index": round(demand, 4),
                "compression_level": compression_level(occupancy, supply, demand),
                "confidence": confidence,
                "top_factors": factors,
                "base_occupancy": round(base, 4),
                "base_source": base_source,
            }
        )

    return {
        "source": "occupancy_rate_estimator",
        "estimator_version": ESTIMATOR_VERSION,
        "property_type": property_type,
        "formula_code": FORMULA_CODE,
        "estimated_occupancy": estimated,
        "daily": daily,
        "summary": {
            "date_count": len(daily),
            "min_estimated_occupancy": min(estimated.values(), default=None),
            "max_estimated_occupancy": max(estimated.values(), default=None),
            "avg_estimated_occupancy": round(sum(estimated.values()) / len(estimated), 4) if estimated else None,
        },
    }


def read_payload(args: argparse.Namespace) -> dict[str, Any]:
    if args.input_json:
        return json.loads(args.input_json)
    raw = sys.stdin.read()
    if not raw.strip():
        raise SystemExit("Expected JSON on stdin or --input-json")
    return json.loads(raw)


def main() -> None:
    parser = argparse.ArgumentParser(description="Estimate RevNest pricing occupancy rates from supply-demand signals.")
    parser.add_argument("--input-json", help="Input JSON. If omitted, JSON is read from stdin.")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output.")
    args = parser.parse_args()
    try:
        result = calculate(read_payload(args))
        print(json.dumps(result, ensure_ascii=False, indent=2 if args.pretty else None, sort_keys=args.pretty))
    except Exception as exc:
        print(json.dumps({"source": "occupancy_rate_estimator", "error": str(exc)}, ensure_ascii=False))
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
