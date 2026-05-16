#!/usr/bin/env python3
"""
Review whether supplied Airbnb pricing guardrails look plausible for listing size.

This does not choose the final price. It flags cases where the host-provided
min/max range may be too restrictive for the property scale, so the pricing
agent can warn the host before presenting a capped recommendation.
"""

from __future__ import annotations

import argparse
import json
import math
import re
from typing import Any


def emit(payload: dict[str, Any], exit_code: int = 0) -> None:
    print(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True))
    raise SystemExit(exit_code)


def parse_number(value: str | None) -> float | None:
    if value is None or value == "":
        return None
    text = str(value).strip()
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    if not match:
        return None
    return float(match.group(0))


def parse_money(value: str | None, name: str) -> float:
    parsed = parse_number(value)
    if parsed is None:
        raise ValueError(f"{name} is required")
    return parsed


def round_to_nearest_five(value: float) -> int:
    return int(math.ceil(value / 5.0) * 5)


def parse_comp_summary(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("--comp-summary-json must be a JSON object")
    return payload


def comp_value(comp_summary: dict[str, Any], keys: tuple[str, ...]) -> float | None:
    for key in keys:
        value = comp_summary.get(key)
        if value not in (None, ""):
            parsed = parse_number(str(value))
            if parsed is not None:
                return parsed
    return None


def review_guardrails(args: argparse.Namespace) -> dict[str, Any]:
    min_price = parse_money(args.min_price, "min_price")
    max_price = parse_money(args.max_price, "max_price")
    if min_price > max_price:
        raise ValueError("min_price cannot exceed max_price")

    capacity = parse_number(args.capacity)
    bedrooms = parse_number(args.bedrooms)
    beds = parse_number(args.beds)
    bathrooms = parse_number(args.bathrooms)
    property_type = (args.property_type or "").strip().lower()
    market = (args.market or "").strip()
    comp_summary = parse_comp_summary(args.comp_summary_json)

    is_private_or_shared = "private" in property_type or "shared" in property_type
    is_entire_place = bool(property_type) and not is_private_or_shared
    large_signals = {
        "capacity_gte_6": capacity is not None and capacity >= 6,
        "bedrooms_gte_3": bedrooms is not None and bedrooms >= 3,
        "beds_gte_4": beds is not None and beds >= 4,
        "bathrooms_gte_2": bathrooms is not None and bathrooms >= 2,
    }
    large_listing = (is_entire_place or not property_type) and any(large_signals.values())

    max_per_guest = round(max_price / capacity, 2) if capacity else None
    max_per_bedroom = round(max_price / bedrooms, 2) if bedrooms else None
    min_per_guest = round(min_price / capacity, 2) if capacity else None

    comp_median = comp_value(comp_summary, ("median_rate", "median", "p50_rate"))
    comp_p75 = comp_value(comp_summary, ("p75_rate", "p75", "upper_quartile_rate"))

    issues: list[str] = []
    if large_listing and max_per_guest is not None and max_per_guest < 45:
        issues.append(f"max_price is only ${max_per_guest:.0f} per guest for a large listing")
    if large_listing and max_per_bedroom is not None and max_per_bedroom < 100:
        issues.append(f"max_price is only ${max_per_bedroom:.0f} per bedroom for a 3+ bedroom listing")
    if comp_median is not None and comp_median > max_price:
        issues.append(f"competitor median ${comp_median:.0f} is above max_price ${max_price:.0f}")
    if comp_p75 is not None and comp_p75 > max_price:
        issues.append(f"competitor p75 ${comp_p75:.0f} is above max_price ${max_price:.0f}")

    review_needed = bool(issues)
    severity = "none"
    if review_needed:
        severity = "medium"
    if len(issues) >= 2 or (comp_median is not None and comp_median >= max_price * 1.2):
        severity = "high"

    suggested_min_candidates = [min_price]
    suggested_max_candidates = [max_price]
    if large_listing:
        if capacity:
            suggested_min_candidates.append(capacity * 45)
            suggested_max_candidates.append(capacity * 65)
        if bedrooms:
            suggested_min_candidates.append(bedrooms * 100)
            suggested_max_candidates.append(bedrooms * 150)
    if comp_median:
        suggested_min_candidates.append(comp_median * 0.85)
        suggested_max_candidates.append(comp_median * 1.25)
    if comp_p75:
        suggested_max_candidates.append(comp_p75 * 1.1)

    suggested_min = round_to_nearest_five(max(suggested_min_candidates))
    suggested_max = round_to_nearest_five(max(suggested_max_candidates))
    if suggested_max < suggested_min:
        suggested_max = suggested_min

    if review_needed:
        message = (
            "Supplied min/max may be too low for this listing size. "
            "Use the provided guardrails for the current run, but ask the host to review a higher range."
        )
    else:
        message = "Supplied min/max guardrails look plausible from the available listing-size checks."

    return {
        "source": "guardrail_review",
        "tool": "guardrail_review.py",
        "guardrail_review_needed": review_needed,
        "severity": severity,
        "message": message,
        "issues": issues,
        "metrics": {
            "min_price": min_price,
            "max_price": max_price,
            "capacity": capacity,
            "bedrooms": bedrooms,
            "beds": beds,
            "bathrooms": bathrooms,
            "max_price_per_guest": max_per_guest,
            "max_price_per_bedroom": max_per_bedroom,
            "min_price_per_guest": min_per_guest,
            "large_listing": large_listing,
            "large_signals": large_signals,
            "market": market or None,
            "comp_median": comp_median,
            "comp_p75": comp_p75,
        },
        "suggested_guardrails": {
            "min_price": suggested_min if review_needed else None,
            "max_price": suggested_max if review_needed else None,
            "requires_host_approval": review_needed,
        },
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Review Airbnb min/max guardrails against listing size")
    parser.add_argument("--min-price", required=True)
    parser.add_argument("--max-price", required=True)
    parser.add_argument("--capacity")
    parser.add_argument("--bedrooms")
    parser.add_argument("--beds")
    parser.add_argument("--bathrooms")
    parser.add_argument("--property-type", help="For example: entire home, apartment, private room")
    parser.add_argument("--market", help="City or market name")
    parser.add_argument("--comp-summary-json", help="Optional JSON object with median_rate/p75_rate")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    try:
        emit(review_guardrails(args))
    except Exception as exc:
        emit({"source": "guardrail_review", "tool": "guardrail_review.py", "error": str(exc)}, exit_code=1)


if __name__ == "__main__":
    main()
