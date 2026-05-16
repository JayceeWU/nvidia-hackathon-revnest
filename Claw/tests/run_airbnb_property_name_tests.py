#!/usr/bin/env python3
"""Smoke tests for human-readable Airbnb property names."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import sys


ROOT = Path(__file__).resolve().parents[1]
TOOLS_DIR = ROOT / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import revpar_estimate  # noqa: E402
import run_pricing_agent  # noqa: E402


ROOM_ID = "1386388491046164092"
URL = f"https://www.airbnb.com/rooms/{ROOM_ID}?photo_id=2119296775"


def assert_equal(actual: object, expected: object, label: str) -> None:
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


def assert_not_contains(actual: str, fragment: str, label: str) -> None:
    if fragment in actual:
        raise AssertionError(f"{label}: {actual!r} unexpectedly contains {fragment!r}")


def test_runner_name_from_profile() -> None:
    name = run_pricing_agent.human_readable_airbnb_property_name(
        f"airbnb-{ROOM_ID}",
        URL,
        {
            "name": f"Airbnb {ROOM_ID}",
            "listingTitle": "Ocean View Studio - Airbnb",
            "city": "Santa Cruz",
            "state": "CA",
            "roomType": "Entire rental unit",
        },
    )
    assert_equal(name, "Ocean View Studio - Santa Cruz, CA - Entire rental unit", "runner profile name")


def test_runner_fallback_uses_short_suffix() -> None:
    name = run_pricing_agent.human_readable_airbnb_property_name(f"airbnb-{ROOM_ID}", URL, {})
    assert_equal(name, "Airbnb Listing 4092", "runner fallback name")
    assert_not_contains(name, ROOM_ID, "runner fallback should hide long room id")


def test_manual_name_is_preserved() -> None:
    name = run_pricing_agent.human_readable_airbnb_property_name(
        f"airbnb-{ROOM_ID}",
        URL,
        {"city": "Santa Cruz", "state": "CA"},
        "Jaycee Coastal Studio",
    )
    assert_equal(name, "Jaycee Coastal Studio", "manual display name")


def test_revpar_publish_name_from_payload() -> None:
    args = SimpleNamespace(
        property_id=f"airbnb-{ROOM_ID}",
        property_name=None,
        location="Santa Cruz, CA",
    )
    name = revpar_estimate.human_readable_airbnb_property_name(
        args,
        {
            "name": f"airbnb-{ROOM_ID}",
            "listingTitle": "Garden Guest Suite | Airbnb",
            "listingType": "Private room",
        },
    )
    assert_equal(name, "Garden Guest Suite - Santa Cruz, CA - Private room", "revpar publish name")


def main() -> None:
    test_runner_name_from_profile()
    test_runner_fallback_uses_short_suffix()
    test_manual_name_is_preserved()
    test_revpar_publish_name_from_payload()
    print("airbnb_property_name_tests: PASS")


if __name__ == "__main__":
    main()
