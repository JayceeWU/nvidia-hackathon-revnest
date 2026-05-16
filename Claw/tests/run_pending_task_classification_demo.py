#!/usr/bin/env python3
"""Dry-run demo for MockHotel pending task safety classifications.

The demo creates two guarded hotel calendar rows and compares them to provided
MockHotel current prices without touching PostgreSQL or MockHotel. It proves the
two human-approval task types that make the NemoClaw safety boundary visible:

- price_adjustment_required: current PMS price is outside Revy's strategy range.
- price_review_recommended: current PMS price is inside range, but still merits
  human review because the recommended change is material.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
TOOLS_DIR = ROOT / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import revnest_mcp_server  # noqa: E402


ACCOUNT_ID = "00000000-0000-0000-0000-000000000103"
RUN_ID = "pending-task-classification-demo"
PRICE_DATE = "2026-05-20"


def strategy_memory(section: str) -> list[dict[str, Any]]:
    return [
        {
            "source": "Dream_Inn_Santa_Cruz_Pricing_Strategy_Manual.docx",
            "section": section,
            "score": 0.91,
            "content": (
                "Hotel revenue management uses BAR bands, occupancy, room-type scarcity, "
                "competitive compression, and guardrails before live PMS updates."
            ),
        }
    ]


def guarded_row(
    *,
    final_price: int,
    range_low: int,
    range_high: int,
    confidence: str = "high",
    summary: str,
) -> dict[str, Any]:
    return {
        "date": PRICE_DATE,
        "current_price": final_price,
        "final_price_after_guardrails": final_price,
        "suggested_price_range_low": range_low,
        "suggested_price_range_high": range_high,
        "estimated_occupancy": 0.74,
        "confidence": confidence,
        "summary": summary,
        "strategy_memory_initial": strategy_memory("Initial hotel BAR strategy"),
        "strategy_memory_review": strategy_memory("Review hotel RMS strategy"),
        "strategy_validation_status": "supported",
        "corrections_applied": [],
    }


def main() -> int:
    price_calendars = {
        "demo-required-room": [
            guarded_row(
                final_price=210,
                range_low=190,
                range_high=230,
                summary="Current PMS price is below the supported hotel BAR band.",
            )
        ],
        "demo-review-room": [
            guarded_row(
                final_price=235,
                range_low=190,
                range_high=240,
                summary="The PMS price is inside range, but Revy recommends a material change.",
            )
        ],
    }
    room_type_properties = {
        "demo-required-room": {"property_id": "demo-required-room", "name": "Demo Required Room"},
        "demo-review-room": {"property_id": "demo-review-room", "name": "Demo Review Room"},
    }
    mock_hotel_room_types = [
        {"id": "demo-required-room", "name": "Demo Required Room", "prices": {PRICE_DATE: 150}},
        {"id": "demo-review-room", "name": "Demo Review Room", "prices": {PRICE_DATE: 200}},
    ]

    result = revnest_mcp_server.review_hotel_price_adjustments_impl(
        account_id=ACCOUNT_ID,
        run_id=RUN_ID,
        price_calendars_by_property_id=price_calendars,
        room_type_properties=room_type_properties,
        mock_hotel_room_types=mock_hotel_room_types,
        dry_run=True,
    )
    tasks = result.get("pending_tasks", [])
    classifications = sorted({task.get("classification") for task in tasks})
    expected = ["price_adjustment_required", "price_review_recommended"]
    passed = classifications == expected and result.get("pending_task_count") == 2

    evidence = {
        "demo": "mockhotel_pending_task_classification",
        "passed": passed,
        "dry_run": result.get("dry_run"),
        "database_write": result.get("database_write"),
        "pending_task_count": result.get("pending_task_count"),
        "classifications": classifications,
        "pending_tasks": [
            {
                "property": task.get("property"),
                "priceDate": task.get("priceDate"),
                "type": task.get("type"),
                "taskType": task.get("taskType"),
                "approvalGateLabel": task.get("approvalGateLabel"),
                "priceDirection": task.get("priceDirection"),
                "currentPrice": task.get("currentPrice"),
                "agentSuggestedPrice": task.get("agentSuggestedPrice"),
                "strategyRange": task.get("strategyRange"),
                "reviewReason": task.get("reviewReason"),
            }
            for task in tasks
        ],
    }
    print(json.dumps(evidence, indent=2, ensure_ascii=False, sort_keys=True))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
