#!/usr/bin/env python3
"""Deterministic pricing-decision calculator for RevNest pricing runs.

The OpenClaw agent owns evidence gathering and strategy review. This script owns
repeatable arithmetic: turn structured strategy, market, occupancy, comp, and
guardrail inputs into a guarded price calendar.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import sys
from typing import Any


CALCULATOR_VERSION = "1.2.0"
DEFAULT_WEEKLY_CHANGE_LIMIT = 0.20
MAX_STRATEGY_CORRECTIONS = 1
FINAL_STRATEGY_STATUSES = {"supported", "corrected"}
OCCUPANCY_ESTIMATOR_SOURCE = "occupancy_rate_estimator"


class StrategyValidationError(ValueError):
    """Raised when strategy-RAG evidence is missing or not publishable."""


def as_float(value: Any, default: float | None = None) -> float | None:
    if value is None:
        return default
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        if math.isfinite(float(value)):
            return float(value)
        return default
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
    if is_percent:
        parsed /= 100.0
    return parsed if math.isfinite(parsed) else default


def as_int(value: Any, default: int | None = None) -> int | None:
    parsed = as_float(value)
    if parsed is None:
        return default
    return int(round(parsed))


def normalize_rate(value: Any, default: float | None = None) -> float | None:
    parsed = as_float(value)
    if parsed is None:
        return default
    if parsed > 1.5:
        parsed /= 100.0
    return max(0.0, min(parsed, 1.0))


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def money(value: float | int | None) -> int | None:
    if value is None:
        return None
    return int(round(float(value)))


def first_value(*values: Any) -> Any:
    for value in values:
        if value is not None and value != "":
            return value
    return None


def lower_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False).lower()
    return str(value).lower()


def normalize_phase(value: Any) -> str:
    phase = lower_text(value or "final").replace("-", "_").strip()
    if phase not in {"draft", "final"}:
        raise StrategyValidationError("calculation_phase must be 'draft' or 'final'.")
    return phase


def extract_chunks(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        for key in ("chunks", "results", "matches"):
            if isinstance(value.get(key), list):
                return [item for item in value[key] if isinstance(item, dict)]
        return []
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return []


def chunk_text(chunk: dict[str, Any]) -> str:
    parts = [
        chunk.get("source"),
        chunk.get("source_path"),
        chunk.get("section"),
        chunk.get("content"),
        chunk.get("text"),
        chunk.get("metadata"),
    ]
    return " ".join(lower_text(part) for part in parts if part is not None)


def strategy_context_part(strategy_context: dict[str, Any], part: str) -> Any:
    if part == "initial":
        return first_value(
            strategy_context.get("initial"),
            strategy_context.get("strategy_memory_initial"),
            strategy_context.get("chunks"),
            strategy_context,
        )
    return first_value(
        strategy_context.get("review"),
        strategy_context.get("strategy_memory_review"),
    )


def relevant_strategy_chunks(chunks: list[dict[str, Any]], property_type: str) -> list[dict[str, Any]]:
    if property_type == "hotel":
        keywords = (
            "dream inn",
            "rms",
            "hotel",
            "bar",
            "room type",
            "room-type",
            "occupancy",
            "compression",
            "revenue management",
            "revpar",
            "adr",
        )
    else:
        keywords = (
            "airbnb",
            "short-term rental",
            "short term rental",
            "vacation rental",
            "comp set",
            "comp-set",
            "booking window",
            "seasonality",
            "event pricing",
        )
    return [chunk for chunk in chunks if any(keyword in chunk_text(chunk) for keyword in keywords)]


def validation_status(strategy_context: dict[str, Any]) -> str:
    validation = strategy_context.get("validation")
    if not isinstance(validation, dict):
        raise StrategyValidationError("strategy_context.validation.status is required for final pricing.")
    status = lower_text(validation.get("status")).strip()
    if status not in FINAL_STRATEGY_STATUSES and status != "unsupported":
        raise StrategyValidationError("strategy_context.validation.status must be supported, corrected, or unsupported.")
    if status == "unsupported":
        raise StrategyValidationError("Strategy review is unsupported; stop before publishing.")
    return status


def normalize_corrections(payload: dict[str, Any], strategy_context: dict[str, Any]) -> list[str]:
    corrections = payload.get("corrections_applied") or strategy_context.get("corrections_applied") or []
    if not isinstance(corrections, list):
        corrections = [str(corrections)]
    normalized = [str(item).strip() for item in corrections if str(item).strip()]
    if len(normalized) > MAX_STRATEGY_CORRECTIONS:
        raise StrategyValidationError("At most one strategy correction is allowed.")
    if any(len(item) > 280 for item in normalized):
        raise StrategyValidationError("Strategy correction must be concise: 280 characters or fewer.")
    return normalized


def validate_strategy_gate(
    payload: dict[str, Any],
    property_type: str,
    strategy_context: dict[str, Any],
) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    phase = normalize_phase(payload.get("calculation_phase") or payload.get("phase"))
    initial_chunks = extract_chunks(strategy_context_part(strategy_context, "initial"))
    initial_relevant = relevant_strategy_chunks(initial_chunks, property_type)
    if not initial_relevant:
        raise StrategyValidationError(f"No relevant initial strategy chunks found for property_type={property_type}.")

    corrections = normalize_corrections(payload, strategy_context)
    if phase == "draft":
        return "draft_unreviewed", initial_relevant, [], corrections

    review_chunks = extract_chunks(strategy_context_part(strategy_context, "review"))
    review_relevant = relevant_strategy_chunks(review_chunks, property_type)
    if not review_relevant:
        raise StrategyValidationError(f"No relevant review strategy chunks found for property_type={property_type}.")

    status = validation_status(strategy_context)
    if status == "corrected" and len(corrections) != 1:
        raise StrategyValidationError("strategy_validation_status=corrected requires exactly one correction.")
    if status == "supported" and corrections:
        raise StrategyValidationError("strategy_validation_status=supported must not include corrections_applied.")
    return status, initial_relevant, review_relevant, corrections


def compact_citations(chunks: Any, limit: int = 5) -> list[dict[str, Any]]:
    if isinstance(chunks, dict):
        chunks = chunks.get("chunks") or chunks.get("results") or []
    if not isinstance(chunks, list):
        return []
    citations: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for chunk in chunks:
        if not isinstance(chunk, dict):
            continue
        source = str(chunk.get("source") or chunk.get("source_path") or "").strip()
        section = str(chunk.get("section") or "").strip()
        key = (source, section)
        if not source or key in seen:
            continue
        seen.add(key)
        citation: dict[str, Any] = {"source": source}
        if section:
            citation["section"] = section
        score = as_float(chunk.get("score"))
        if score is not None:
            citation["score"] = round(score, 4)
        citations.append(citation)
        if len(citations) >= limit:
            break
    return citations


def strategy_citations(strategy_context: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    initial = first_value(
        strategy_context.get("initial"),
        strategy_context.get("strategy_memory_initial"),
        strategy_context.get("chunks"),
        strategy_context,
    )
    review = first_value(
        strategy_context.get("review"),
        strategy_context.get("strategy_memory_review"),
        strategy_context.get("validation"),
    )
    return compact_citations(initial), compact_citations(review)


def value_for_date(source: Any, date_key: str) -> Any:
    if source is None:
        return {}
    if isinstance(source, dict):
        per_date = source.get(date_key)
        if per_date is not None:
            return per_date
        nested = source.get("by_date") or source.get("per_date") or source.get("daily")
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


def rate_from_date_value(value: Any) -> float | None:
    if isinstance(value, dict):
        return normalize_rate(
            first_value(
                value.get("estimated_occupancy"),
                value.get("occupancy_rate"),
                value.get("occupancy"),
                value.get("rate"),
            )
        )
    return normalize_rate(value)


def occupancy_estimator_payload(payload: dict[str, Any]) -> dict[str, Any]:
    candidates = [
        payload.get("occupancy_estimator"),
        payload.get("occupancy_rate_estimator"),
        payload.get("occupancy_python_run"),
        payload.get("estimated_occupancy"),
    ]
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        source = lower_text(first_value(candidate.get("source"), candidate.get("tool"), candidate.get("estimator")))
        if OCCUPANCY_ESTIMATOR_SOURCE in source:
            return candidate
        if candidate.get("estimator_version") and (candidate.get("estimated_occupancy") or candidate.get("daily")):
            return candidate

    source = lower_text(first_value(payload.get("estimated_occupancy_source"), payload.get("occupancy_source")))
    estimated = payload.get("estimated_occupancy")
    if OCCUPANCY_ESTIMATOR_SOURCE in source and isinstance(estimated, (dict, list)):
        return {"source": OCCUPANCY_ESTIMATOR_SOURCE, "estimated_occupancy": estimated}

    raise StrategyValidationError("estimated_occupancy must come from occupancy_rate_estimator.py output.")


def occupancy_rate_from_estimator(estimator: dict[str, Any], date_key: str) -> float | None:
    estimated = estimator.get("estimated_occupancy")
    if estimated is not None:
        rate = rate_from_date_value(value_for_date(estimated, date_key))
        if rate is not None:
            return rate
    return rate_from_date_value(value_for_date(estimator, date_key))


def validate_occupancy_estimator_gate(payload: dict[str, Any], dates: list[dict[str, Any]]) -> dict[str, Any]:
    estimator = occupancy_estimator_payload(payload)
    missing_dates: list[str] = []
    mismatched_dates: list[str] = []
    for date_row in dates:
        date_key = str(date_row["date"])
        estimator_rate = occupancy_rate_from_estimator(estimator, date_key)
        if estimator_rate is None:
            missing_dates.append(date_key)
            continue
        calculator_rate = estimate_occupancy(payload, date_key, {})
        if calculator_rate is None:
            missing_dates.append(date_key)
            continue
        if abs(calculator_rate - estimator_rate) > 0.005:
            mismatched_dates.append(date_key)
    if missing_dates:
        joined = ", ".join(missing_dates[:5])
        raise StrategyValidationError(f"occupancy_rate_estimator.py output is missing estimated_occupancy for: {joined}.")
    if mismatched_dates:
        joined = ", ".join(mismatched_dates[:5])
        raise StrategyValidationError(f"calculator estimated_occupancy does not match occupancy estimator output for: {joined}.")
    return estimator


def parse_dates(payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw_dates = payload.get("dates") or payload.get("price_dates") or payload.get("calendar") or []
    dates: list[dict[str, Any]] = []
    if isinstance(raw_dates, list):
        for item in raw_dates:
            if isinstance(item, str):
                dates.append({"date": item})
            elif isinstance(item, dict) and item.get("date"):
                dates.append(dict(item))
    if dates:
        return dates

    start = payload.get("start_date")
    horizon = as_int(payload.get("pricing_horizon"), 0) or 0
    if not start or horizon <= 0:
        return []
    start_date = dt.date.fromisoformat(str(start))
    return [{"date": (start_date + dt.timedelta(days=index)).isoformat()} for index in range(horizon)]


def trusted_current_price(date_row: dict[str, Any], profile: dict[str, Any]) -> tuple[float | None, bool]:
    current = as_float(first_value(date_row.get("current_price"), profile.get("current_price")))
    if current is None:
        return None, False
    trusted = first_value(
        date_row.get("current_price_trusted"),
        date_row.get("current_price_is_trusted"),
        profile.get("current_price_trusted"),
        profile.get("current_price_is_trusted"),
    )
    if trusted is not None:
        return current, bool(trusted)
    source = lower_text(first_value(date_row.get("current_price_source"), profile.get("current_price_source")))
    trusted_sources = ("verified", "database", "db", "user", "supplied", "trusted", "listing")
    return current, any(token in source for token in trusted_sources)


def comp_relevance(stats: dict[str, Any], signals: dict[str, Any]) -> str:
    raw = lower_text(first_value(stats.get("comp_set_relevance"), signals.get("comp_set_relevance")))
    if "strong" in raw:
        return "strong"
    if "weak" in raw:
        return "weak"
    if "usable" in raw or "medium" in raw:
        return "usable"
    count = as_int(stats.get("comp_count"), 0) or 0
    if count >= 8:
        return "strong"
    if count >= 3:
        return "usable"
    return "weak"


def competitor_anchor(stats: dict[str, Any], relevance: str) -> float | None:
    median = as_float(first_value(stats.get("median_rate"), stats.get("median"), stats.get("median_price")))
    p25 = as_float(first_value(stats.get("p25_rate"), stats.get("p25"), stats.get("q1_rate")))
    p75 = as_float(first_value(stats.get("p75_rate"), stats.get("p75"), stats.get("q3_rate")))
    avg = as_float(first_value(stats.get("avg_rate"), stats.get("average_rate"), stats.get("mean_rate")))
    if median is None:
        median = avg
    if median is None:
        return None
    if p25 is None:
        p25 = median
    if p75 is None:
        p75 = median
    weights = {
        "strong": (0.20, 0.55, 0.25),
        "usable": (0.25, 0.60, 0.15),
        "weak": (0.35, 0.65, 0.00),
    }.get(relevance, (0.25, 0.60, 0.15))
    return p25 * weights[0] + median * weights[1] + p75 * weights[2]


def estimate_occupancy(payload: dict[str, Any], date_key: str, signals: dict[str, Any]) -> float | None:
    source = payload.get("estimated_occupancy")
    if source is None and isinstance(payload.get("occupancy_estimator"), dict):
        source = payload["occupancy_estimator"]
    if source is None and isinstance(payload.get("occupancy_rate_estimator"), dict):
        source = payload["occupancy_rate_estimator"]
    if isinstance(source, dict) and lower_text(source.get("source")).find(OCCUPANCY_ESTIMATOR_SOURCE) >= 0:
        estimator_rate = occupancy_rate_from_estimator(source, date_key)
        if estimator_rate is not None:
            return estimator_rate
    if isinstance(source, dict):
        date_value = value_for_date(source, date_key)
        if isinstance(date_value, dict):
            return rate_from_date_value(date_value)
        return normalize_rate(date_value)
    if isinstance(source, list):
        date_value = value_for_date(source, date_key)
        if isinstance(date_value, dict):
            return normalize_rate(first_value(date_value.get("occupancy_rate"), date_value.get("occupancy")))
    direct = normalize_rate(first_value(signals.get("estimated_occupancy"), signals.get("occupancy_rate"), signals.get("occupancy")))
    if direct is not None:
        return direct
    return normalize_rate(source)


def infer_demand_level(signals: dict[str, Any], occupancy: float | None) -> str:
    raw = lower_text(first_value(signals.get("demand_level"), signals.get("demand"), signals.get("market_demand")))
    for level in ("compressed", "elevated", "normal", "low"):
        if level in raw:
            return level
    text = lower_text(signals)
    if any(token in text for token in ("sold out", "compression", "compressed", "major event", "high demand", "surge")):
        return "compressed"
    if any(token in text for token in ("elevated", "busy", "holiday", "event", "peak", "strong")):
        return "elevated"
    if any(token in text for token in ("low demand", "soft", "off season", "rain", "storm", "weak")):
        return "low"
    if occupancy is not None:
        if occupancy >= 0.90:
            return "compressed"
        if occupancy >= 0.76:
            return "elevated"
        if occupancy <= 0.45:
            return "low"
    return "normal"


def event_modifier(signals: dict[str, Any]) -> tuple[float, list[str]]:
    text = lower_text(first_value(signals.get("events"), signals.get("event_summary"), signals.get("event")))
    strength = lower_text(first_value(signals.get("event_strength"), signals.get("event_demand")))
    reasons: list[str] = []
    if any(token in strength + " " + text for token in ("major", "compression", "citywide", "sold out")):
        reasons.append("major event or compression signal")
        return 0.12, reasons
    if any(token in strength + " " + text for token in ("strong", "busy", "event", "concert", "festival", "game", "graduation")):
        reasons.append("local event demand")
        return 0.07, reasons
    return 0.0, reasons


def holiday_modifier(signals: dict[str, Any]) -> tuple[float, list[str]]:
    text = lower_text(first_value(signals.get("holidays"), signals.get("holiday"), signals.get("school_breaks")))
    if any(token in text for token in ("public", "holiday", "school", "break", "long weekend")):
        return 0.05, ["holiday or school-break demand"]
    return 0.0, []


def weather_modifier(signals: dict[str, Any]) -> tuple[float, list[str]]:
    text = lower_text(first_value(signals.get("weather"), signals.get("weather_summary"), signals.get("weather_demand")))
    if any(token in text for token in ("storm", "heavy rain", "high wind", "travel disruption", "danger")):
        return -0.07, ["weather disruption risk"]
    if any(token in text for token in ("rain", "cold", "poor weather")):
        return -0.04, ["soft outdoor weather"]
    if any(token in text for token in ("sunny", "clear", "warm", "good weather", "beach weather")):
        return 0.03, ["favorable weather"]
    return 0.0, []


def tourism_modifier(signals: dict[str, Any]) -> tuple[float, list[str]]:
    text = lower_text(first_value(signals.get("tourism"), signals.get("tourism_demand"), signals.get("seasonality")))
    if any(token in text for token in ("peak", "high", "strong", "summer", "busy")):
        return 0.07, ["strong tourism or seasonality"]
    if any(token in text for token in ("low", "off season", "soft", "weak")):
        return -0.06, ["soft tourism or off-season demand"]
    return 0.0, []


def booking_window_modifier(signals: dict[str, Any], occupancy: float | None) -> tuple[float, list[str]]:
    days = as_int(first_value(signals.get("booking_window_days"), signals.get("days_to_arrival"), signals.get("lead_time_days")))
    if days is None:
        return 0.0, []
    if days <= 7:
        if occupancy is not None and occupancy >= 0.82:
            return 0.05, ["short booking window with high occupancy"]
        if occupancy is not None and occupancy <= 0.55:
            return -0.05, ["short booking window with soft pickup"]
        return -0.02, ["short booking window"]
    if days >= 60 and occupancy is not None and occupancy >= 0.70:
        return 0.03, ["healthy long-window pickup"]
    return 0.0, []


def supply_modifier(signals: dict[str, Any], property_type: str) -> tuple[float, list[str]]:
    text = lower_text(first_value(signals.get("supply"), signals.get("compression"), signals.get("availability"), signals.get("inventory")))
    if any(token in text for token in ("low supply", "limited", "compression", "sold out", "scarce")):
        return (0.09 if property_type == "hotel" else 0.06), ["limited supply or compression"]
    if any(token in text for token in ("high supply", "many available", "oversupply")):
        return -0.05, ["ample competing supply"]
    return 0.0, []


def day_modifier(date_key: str, property_type: str, signals: dict[str, Any]) -> tuple[float, list[str]]:
    try:
        weekday = dt.date.fromisoformat(date_key).weekday()
    except ValueError:
        return 0.0, []
    intent = lower_text(first_value(signals.get("guest_intent"), signals.get("segment")))
    if weekday in (4, 5):
        return (0.05 if property_type == "airbnb" else 0.03), ["weekend leisure demand"]
    if property_type == "hotel" and weekday in (1, 2, 3) and any(token in intent for token in ("business", "corporate", "conference")):
        return 0.03, ["midweek business demand"]
    return 0.0, []


def branch_modifier(property_type: str, profile: dict[str, Any], signals: dict[str, Any], occupancy: float | None) -> tuple[float, list[str]]:
    reasons: list[str] = []
    modifier = 0.0
    profile_text = lower_text(profile)
    if property_type == "hotel":
        room_count = as_int(first_value(profile.get("room_count"), profile.get("rooms")))
        if room_count is not None:
            if room_count <= 5:
                modifier += 0.06
                reasons.append("very limited room-type inventory")
            elif room_count <= 15:
                modifier += 0.03
                reasons.append("limited room-type inventory")
        if any(token in profile_text for token in ("suite", "premium", "ocean", "beachfront", "view")):
            modifier += 0.06
            reasons.append("premium room-type attributes")
        if occupancy is not None and occupancy >= 0.88:
            modifier += 0.05
            reasons.append("high hotel occupancy")
    else:
        capacity = as_int(first_value(profile.get("capacity"), profile.get("guests"), profile.get("occupancy")))
        bedrooms = as_int(first_value(profile.get("bedrooms"), profile.get("bed")))
        if capacity is not None and capacity >= 6:
            modifier += 0.04
            reasons.append("large-group capacity")
        if bedrooms is not None and bedrooms >= 3:
            modifier += 0.03
            reasons.append("multi-bedroom vacation-rental fit")
        if any(token in profile_text for token in ("parking", "kitchen", "washer", "laundry", "workspace", "view", "pet")):
            modifier += 0.03
            reasons.append("amenities align with guest priorities")
        if any(token in lower_text(signals) for token in ("hotel substitute", "studio", "private room", "1br", "one bedroom")):
            modifier += 0.03
            reasons.append("hotel-substitute comp support")
    return modifier, reasons


def confidence_level(
    relevance: str,
    comp_anchor_value: float | None,
    strategy_initial: list[dict[str, Any]],
    guardrail_constrained: bool,
    occupancy: float | None,
) -> str:
    score = 0
    if relevance == "strong":
        score += 2
    elif relevance == "usable":
        score += 1
    if comp_anchor_value is not None:
        score += 1
    if strategy_initial:
        score += 1
    if occupancy is not None:
        score += 1
    if guardrail_constrained:
        score -= 2
    if score >= 4:
        return "high"
    if score >= 2:
        return "medium"
    return "low"


def pricing_strategy(raw_price: float, base_price: float) -> str:
    if raw_price <= base_price * 0.96:
        return "discount"
    if raw_price <= base_price * 1.04:
        return "hold"
    if raw_price <= base_price * 1.15:
        return "modest_uplift"
    return "strong_uplift"


def suggested_range(raw_price: float, relevance: str, confidence: str) -> tuple[int, int]:
    spread = 0.06
    if relevance == "weak" or confidence == "low":
        spread = 0.14
    elif relevance == "usable" or confidence == "medium":
        spread = 0.10
    return money(raw_price * (1 - spread)) or 0, money(raw_price * (1 + spread)) or 0


def guardrail_warning(profile: dict[str, Any], min_price: float, max_price: float, raw_price: float, final_price: float, property_type: str) -> tuple[bool, str | None]:
    capacity = as_float(first_value(profile.get("capacity"), profile.get("guests"), profile.get("occupancy")))
    bedrooms = as_float(first_value(profile.get("bedrooms"), profile.get("bed")))
    warnings: list[str] = []
    if final_price != raw_price:
        warnings.append("Recommendation is constrained by host guardrails.")
    if property_type == "airbnb":
        if capacity and capacity >= 6 and max_price / capacity < 45:
            warnings.append("Max price appears low for a large US leisure listing.")
        if bedrooms and bedrooms >= 3 and max_price / bedrooms < 100:
            warnings.append("Max price appears low per bedroom for a 3+ bedroom listing.")
    if raw_price > max_price:
        gap = money(raw_price - max_price)
        warnings.append(f"Raw suggested price exceeds max_price by USD {gap}.")
    if min_price > max_price:
        warnings.append("min_price is above max_price.")
    return bool(warnings), " ".join(warnings) if warnings else None


def calculate(payload: dict[str, Any]) -> dict[str, Any]:
    property_type = lower_text(payload.get("property_type") or "airbnb")
    property_type = "hotel" if property_type == "hotel" else "airbnb"
    profile = payload.get("property_profile") if isinstance(payload.get("property_profile"), dict) else {}
    guardrails = payload.get("guardrails") if isinstance(payload.get("guardrails"), dict) else {}
    min_price = as_float(first_value(guardrails.get("min_price"), payload.get("min_price")), 0.0) or 0.0
    max_price = as_float(first_value(guardrails.get("max_price"), payload.get("max_price")), min_price) or min_price
    if max_price < min_price:
        max_price = min_price
    weekly_limit = as_float(first_value(guardrails.get("max_weekly_change_pct"), payload.get("max_weekly_change_pct")))
    if weekly_limit is None:
        weekly_limit = DEFAULT_WEEKLY_CHANGE_LIMIT
    elif weekly_limit > 1.0:
        weekly_limit /= 100.0
    weekly_limit = max(0.0, weekly_limit)

    strategy_context = payload.get("strategy_context") if isinstance(payload.get("strategy_context"), dict) else {}
    strategy_status, initial_chunks, review_chunks, corrections = validate_strategy_gate(payload, property_type, strategy_context)
    initial_citations = compact_citations(initial_chunks)
    review_citations = compact_citations(review_chunks)
    if not initial_citations:
        raise StrategyValidationError("Initial strategy chunks must include source citations.")
    if strategy_status != "draft_unreviewed" and not review_citations:
        raise StrategyValidationError("Review strategy chunks must include source citations.")

    dates = parse_dates(payload)
    occupancy_estimator = validate_occupancy_estimator_gate(payload, dates)
    market_signals = payload.get("market_signals") or {}
    competitor_stats = payload.get("competitor_stats") or {}
    midpoint = (min_price + max_price) / 2 if max_price else min_price
    calendar: list[dict[str, Any]] = []

    for date_row in dates:
        date_key = str(date_row["date"])
        signals = value_for_date(market_signals, date_key)
        if not isinstance(signals, dict):
            signals = {}
        stats = value_for_date(competitor_stats, date_key)
        if not isinstance(stats, dict):
            stats = {}
        merged_signals = {**signals, **{key: value for key, value in date_row.items() if key != "date"}}

        current_price, current_trusted = trusted_current_price(date_row, profile)
        relevance = comp_relevance(stats, merged_signals)
        comp_anchor_value = competitor_anchor(stats, relevance)
        occupancy = estimate_occupancy(payload, date_key, merged_signals)
        demand_level = infer_demand_level(merged_signals, occupancy)

        bar_rate = as_float(first_value(stats.get("bar_rate"), merged_signals.get("bar_rate"), date_row.get("bar_rate")))
        if current_price is not None and current_trusted:
            base_price = current_price
            if comp_anchor_value is not None:
                comp_weight = {"strong": 0.45, "usable": 0.30, "weak": 0.15}.get(relevance, 0.30)
                base_price = current_price * (1 - comp_weight) + comp_anchor_value * comp_weight
        elif comp_anchor_value is not None:
            base_price = comp_anchor_value
        else:
            base_price = midpoint
        if property_type == "hotel" and bar_rate is not None:
            base_price = base_price * 0.60 + bar_rate * 0.40

        reasons: list[str] = []
        modifier = {
            "low": -0.08,
            "normal": 0.0,
            "elevated": 0.10,
            "compressed": 0.22,
        }[demand_level]
        if demand_level != "normal":
            reasons.append(f"{demand_level} demand")

        if occupancy is not None:
            occupancy_weight = 0.45 if property_type == "hotel" else 0.35
            occ_mod = clamp((occupancy - 0.65) * occupancy_weight, -0.14, 0.18)
            modifier += occ_mod
            reasons.append(f"estimated occupancy {round(occupancy * 100)}%")

        for fn in (event_modifier, holiday_modifier, weather_modifier, tourism_modifier):
            delta, why = fn(merged_signals)
            modifier += delta
            reasons.extend(why)
        for delta, why in (
            booking_window_modifier(merged_signals, occupancy),
            supply_modifier(merged_signals, property_type),
            day_modifier(date_key, property_type, merged_signals),
            branch_modifier(property_type, profile, merged_signals, occupancy),
        ):
            modifier += delta
            reasons.extend(why)

        if relevance == "weak":
            modifier *= 0.75
            reasons.append("weak comp set keeps move conservative")

        raw_price = max(0.0, base_price * (1 + modifier))
        guardrail_adjustments: list[str] = []
        if current_price is not None and current_trusted and weekly_limit > 0:
            high = current_price * (1 + weekly_limit)
            low = current_price * (1 - weekly_limit)
            if raw_price > high:
                raw_price = high
                guardrail_adjustments.append(f"weekly increase limited to {round(weekly_limit * 100)}%")
            elif raw_price < low:
                raw_price = low
                guardrail_adjustments.append(f"weekly decrease limited to {round(weekly_limit * 100)}%")

        rounded_raw = money(raw_price) or 0
        final_price = money(clamp(rounded_raw, min_price, max_price)) or 0
        if final_price != rounded_raw:
            guardrail_adjustments.append("clamped to host min/max guardrails")

        review_needed, warning = guardrail_warning(profile, min_price, max_price, rounded_raw, final_price, property_type)
        low_range, high_range = suggested_range(rounded_raw, relevance, "medium")
        low_range = money(clamp(low_range, min_price, max_price)) or int(min_price)
        high_range = money(clamp(high_range, min_price, max_price)) or int(max_price)
        if low_range > high_range:
            low_range, high_range = high_range, low_range

        confidence = confidence_level(relevance, comp_anchor_value, initial_citations, review_needed or bool(guardrail_adjustments), occupancy)
        low_range, high_range = suggested_range(rounded_raw, relevance, confidence)
        low_range = money(clamp(low_range, min_price, max_price)) or int(min_price)
        high_range = money(clamp(high_range, min_price, max_price)) or int(max_price)
        if low_range > high_range:
            low_range, high_range = high_range, low_range

        signals_used = [
            key
            for key in (
                "events",
                "holidays",
                "weather",
                "tourism",
                "seasonality",
                "booking_window_days",
                "supply",
                "compression",
                "occupancy",
                "bar_rate",
            )
            if key in merged_signals or key in stats
        ]
        if comp_anchor_value is not None:
            signals_used.append("competitor_stats")
        if initial_citations:
            signals_used.append("strategy_memory_initial")
        if review_citations:
            signals_used.append("strategy_memory_review")

        change_pct = None
        if current_price is not None and current_trusted and current_price:
            change_pct = round((final_price - current_price) / current_price * 100, 2)

        calendar.append(
            {
                "date": date_key,
                "current_price": money(current_price) if current_price is not None else None,
                "current_price_trusted": current_trusted,
                "raw_suggested_price": rounded_raw,
                "suggested_price_range_low": low_range,
                "suggested_price_range_high": high_range,
                "final_price_after_guardrails": final_price,
                "change_pct": change_pct,
                "estimated_occupancy": round(occupancy, 4) if occupancy is not None else None,
                "occupancy_source": "occupancy_rate_estimator.py",
                "occupancy_estimator_version": occupancy_estimator.get("estimator_version"),
                "demand_level": demand_level,
                "comp_set_relevance": relevance,
                "pricing_strategy": pricing_strategy(rounded_raw, base_price),
                "confidence": confidence,
                "top_reasons": list(dict.fromkeys(reasons))[:6],
                "signals_used": list(dict.fromkeys(signals_used)),
                "tavily_followups": merged_signals.get("tavily_followups") or [],
                "guardrail_adjustments": guardrail_adjustments,
                "guardrail_review_needed": review_needed,
                "guardrail_warning": warning,
                "strategy_memory_initial": initial_citations,
                "strategy_memory_review": review_citations,
                "strategy_validation_status": strategy_status,
                "corrections_applied": corrections,
                "calculator_version": CALCULATOR_VERSION,
            }
        )

    return {
        "calculator_version": CALCULATOR_VERSION,
        "property_type": property_type,
        "price_calendar": calendar,
        "strategy_memory_initial": initial_citations,
        "strategy_memory_review": review_citations,
        "strategy_validation_status": strategy_status,
        "occupancy_source": "occupancy_rate_estimator.py",
        "occupancy_estimator_version": occupancy_estimator.get("estimator_version"),
        "corrections_applied": corrections,
        "summary": {
            "date_count": len(calendar),
            "min_final_price": min((row["final_price_after_guardrails"] for row in calendar), default=None),
            "max_final_price": max((row["final_price_after_guardrails"] for row in calendar), default=None),
            "guardrail_review_needed": any(row["guardrail_review_needed"] for row in calendar),
            "strategy_validation_status": strategy_status,
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
    parser = argparse.ArgumentParser(description="Calculate a guarded RevNest pricing decision calendar.")
    parser.add_argument("--input-json", help="Calculator input JSON. If omitted, JSON is read from stdin.")
    parser.add_argument("--calculation-phase", choices=("draft", "final"), help="Override calculation_phase in input JSON.")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output.")
    args = parser.parse_args()
    try:
        payload = read_payload(args)
        if args.calculation_phase:
            payload["calculation_phase"] = args.calculation_phase
        result = calculate(payload)
        print(json.dumps(result, ensure_ascii=False, indent=2 if args.pretty else None, sort_keys=args.pretty))
    except StrategyValidationError as exc:
        print(
            json.dumps(
                {
                    "source": "pricing_decision_calculator",
                    "tool": "pricing_decision_calculator",
                    "strategy_validation_status": "unsupported",
                    "error": str(exc),
                },
                ensure_ascii=False,
                indent=2 if args.pretty else None,
                sort_keys=args.pretty,
            )
        )
        raise SystemExit(1) from exc
    except Exception as exc:
        print(
            json.dumps(
                {
                    "source": "pricing_decision_calculator",
                    "tool": "pricing_decision_calculator",
                    "error": str(exc),
                },
                ensure_ascii=False,
                indent=2 if args.pretty else None,
                sort_keys=args.pretty,
            )
        )
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
