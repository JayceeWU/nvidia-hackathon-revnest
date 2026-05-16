#!/usr/bin/env python3
"""Executable smoke tests for RevNest strategy-RAG anti-hallucination gates.

These tests are intentionally CLI-based so demo reviewers can see the same
failure modes an agent would hit: calculator final gates exit nonzero, and the
publisher dry-run refuses to produce write SQL for unsupported calendars.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CALCULATOR = ROOT / "skills" / "pricing-decision-reasoning" / "scripts" / "pricing_decision_calculator.py"
PUBLISHER = ROOT / "tools" / "revpar_estimate.py"
PYTHON = sys.executable or "python3"
TEST_DATE = "2026-05-20"


def airbnb_chunk(section: str = "Airbnb Pricing Strategy") -> dict[str, Any]:
    return {
        "source": "US_Airbnb_Pricing_Strategy_Manual_EN.docx",
        "section": section,
        "score": 0.92,
        "content": (
            "Airbnb short-term rental pricing strategy uses seasonality, booking window, "
            "event pricing, vacation-rental comp set, and guest segment fit."
        ),
    }


def base_calculator_payload(*, phase: str = "draft", validation_status: str = "supported") -> dict[str, Any]:
    strategy_context: dict[str, Any] = {
        "initial": {"chunks": [airbnb_chunk("Initial Airbnb strategy")]},
    }
    if phase == "final":
        strategy_context["review"] = {"chunks": [airbnb_chunk("Review Airbnb strategy")]}
        strategy_context["validation"] = {"status": validation_status}

    return {
        "calculation_phase": phase,
        "property_type": "airbnb",
        "property_profile": {
            "name": "Strategy Gate Test Airbnb",
            "capacity": 2,
            "current_price": 500,
            "current_price_trusted": True,
        },
        "guardrails": {
            "min_price": 300,
            "max_price": 700,
            "max_weekly_change_pct": 20,
        },
        "dates": [
            {
                "date": TEST_DATE,
                "current_price": 500,
                "current_price_trusted": True,
            }
        ],
        "market_signals": {
            TEST_DATE: {
                "events": "Local event demand is elevated.",
                "booking_window_days": 14,
                "supply": "usable vacation-rental supply with some compression",
            }
        },
        "competitor_stats": {
            TEST_DATE: {
                "p25_rate": 420,
                "median_rate": 520,
                "p75_rate": 610,
                "comp_count": 8,
                "comp_set_relevance": "strong",
            }
        },
        "occupancy_estimator": {
            "source": "occupancy_rate_estimator.py",
            "estimator_version": "test",
            "estimated_occupancy": {
                TEST_DATE: {"estimated_occupancy": 0.72}
            },
        },
        "strategy_context": strategy_context,
    }


def publisher_row(*, status: str = "supported", include_memory: bool = True, corrections: list[str] | None = None) -> dict[str, Any]:
    row: dict[str, Any] = {
        "date": TEST_DATE,
        "current_price": 500,
        "final_price_after_guardrails": 560,
        "estimated_occupancy": 0.72,
        "strategy_validation_status": status,
        "corrections_applied": corrections or [],
    }
    if include_memory:
        row["strategy_memory_initial"] = [{"source": "US_Airbnb_Pricing_Strategy_Manual_EN.docx", "section": "Initial Airbnb strategy"}]
        row["strategy_memory_review"] = [{"source": "US_Airbnb_Pricing_Strategy_Manual_EN.docx", "section": "Review Airbnb strategy"}]
    return row


def run_json(cmd: list[str], payload: Any | None = None) -> tuple[int, dict[str, Any], str]:
    result = subprocess.run(
        cmd,
        cwd=ROOT,
        input=json.dumps(payload) if payload is not None else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )
    stdout = result.stdout.strip()
    try:
        parsed = json.loads(stdout)
    except json.JSONDecodeError:
        parsed = {"raw_output": stdout}
    return result.returncode, parsed, stdout


def run_calculator(payload: dict[str, Any]) -> tuple[int, dict[str, Any], str]:
    return run_json([PYTHON, str(CALCULATOR)], payload)


def run_publisher(calendar: list[dict[str, Any]]) -> tuple[int, dict[str, Any], str]:
    return run_json(
        [
            PYTHON,
            str(PUBLISHER),
            "write-prices",
            "--dry-run",
            "--property-id",
            "strategy-gate-test-airbnb",
            "--account-id",
            "00000000-0000-0000-0000-000000000102",
            "--price-calendar-json",
            json.dumps(calendar),
            "--rooms",
            "1",
            "--occupancy-rate",
            "0.72",
            "--no-create-property",
        ]
    )


def assert_case(name: str, condition: bool, detail: dict[str, Any]) -> dict[str, Any]:
    status = "PASS" if condition else "FAIL"
    print(f"{status} {name}")
    if not condition:
        print(json.dumps(detail, indent=2, ensure_ascii=False, sort_keys=True))
    return {"name": name, "status": status, "detail": detail}


def main() -> int:
    cases: list[dict[str, Any]] = []

    code, parsed, raw = run_calculator(base_calculator_payload(phase="draft"))
    cases.append(
        assert_case(
            "calculator draft with initial RAG returns draft_unreviewed",
            code == 0 and parsed.get("strategy_validation_status") == "draft_unreviewed",
            {"returncode": code, "strategy_validation_status": parsed.get("strategy_validation_status"), "raw": raw[:500]},
        )
    )

    code, parsed, raw = run_calculator(base_calculator_payload(phase="final", validation_status="supported"))
    cases.append(
        assert_case(
            "calculator final supported returns publishable status",
            code == 0 and parsed.get("strategy_validation_status") == "supported",
            {"returncode": code, "strategy_validation_status": parsed.get("strategy_validation_status"), "raw": raw[:500]},
        )
    )

    code, parsed, raw = run_calculator(base_calculator_payload(phase="final", validation_status="unsupported"))
    cases.append(
        assert_case(
            "calculator final unsupported exits nonzero",
            code != 0
            and parsed.get("strategy_validation_status") == "unsupported"
            and "unsupported" in str(parsed.get("error", "")).lower(),
            {"returncode": code, "error": parsed.get("error"), "raw": raw[:500]},
        )
    )

    two_corrections = base_calculator_payload(phase="final", validation_status="corrected")
    two_corrections["corrections_applied"] = ["Narrow to event-supported uplift.", "Apply extra unsupported premium."]
    code, parsed, raw = run_calculator(two_corrections)
    cases.append(
        assert_case(
            "calculator final corrected rejects more than one correction",
            code != 0 and "one strategy correction" in str(parsed.get("error", "")).lower(),
            {"returncode": code, "error": parsed.get("error"), "raw": raw[:500]},
        )
    )

    code, parsed, raw = run_publisher([publisher_row(include_memory=False)])
    cases.append(
        assert_case(
            "publisher dry-run rejects calendar missing strategy memory before write",
            code != 0 and "missing strategy_memory_initial" in str(parsed.get("error", "")),
            {"returncode": code, "error": parsed.get("error"), "raw": raw[:500]},
        )
    )

    code, parsed, raw = run_publisher([publisher_row(status="draft_unreviewed")])
    cases.append(
        assert_case(
            "publisher dry-run rejects draft_unreviewed before write",
            code != 0 and "strategy_validation_status must be supported or corrected" in str(parsed.get("error", "")),
            {"returncode": code, "error": parsed.get("error"), "raw": raw[:500]},
        )
    )

    code, parsed, raw = run_publisher([publisher_row(status="unsupported")])
    cases.append(
        assert_case(
            "publisher dry-run rejects unsupported before write",
            code != 0 and "strategy_validation_status must be supported or corrected" in str(parsed.get("error", "")),
            {"returncode": code, "error": parsed.get("error"), "raw": raw[:500]},
        )
    )

    code, parsed, raw = run_publisher([publisher_row(status="corrected", corrections=["Corrected to stay within supported Airbnb event-pricing guidance."])])
    cases.append(
        assert_case(
            "publisher dry-run accepts corrected with exactly one correction",
            code == 0 and parsed.get("dry_run") is True and parsed.get("rows_to_write") == 1,
            {"returncode": code, "dry_run": parsed.get("dry_run"), "rows_to_write": parsed.get("rows_to_write"), "raw": raw[:500]},
        )
    )

    failed = [case for case in cases if case["status"] != "PASS"]
    summary = {
        "source": "run_strategy_rag_gate_tests",
        "total": len(cases),
        "passed": len(cases) - len(failed),
        "failed": len(failed),
        "evidence": "unsupported/draft calendars exited nonzero before publisher dry-run could write SQL",
    }
    print(json.dumps(summary, indent=2, ensure_ascii=False, sort_keys=True))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
