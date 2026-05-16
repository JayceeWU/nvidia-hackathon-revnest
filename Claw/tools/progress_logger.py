#!/usr/bin/env python3
"""
RevNest workflow progress logger.

Appends one JSON object per line so a web app can stream workflow progress with
tail -f or a file watcher.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LOG_PATH = ROOT / "runs" / "airbnb-pricing-progress.log"
WORKFLOW_NAME = "pricing-workflow"
STATUSES = {"started", "completed", "skipped", "failed", "info"}
WORKFLOW_TOOL_ALIASES = {"pricing-workflow", "pricing_workflow", "airbnb-pricing", "airbnb_pricing", "workflow"}
STAGE_TOOL_DEFAULTS = {
    "context": "agent-browser",
    "weather": "tools/weather_tool.py",
    "holidays": "tools/get_holiday.py",
    "events_ticketmaster": "tools/ticketmaster.py",
    "events_serpapi": "tools/serpapi.py",
    "hotel_comps_serpapi": "tools/serpapi.py",
    "hotel_comps_moodtrip": "moodtrip__searchHotelsWithRates",
    "tourism_tavily": "tools/tavily.py",
    "guardrail_review": "tools/guardrail_review.py",
    "market_data_parallel": "tools/run_parallel_market_data.py",
    "pricing_decision": "pricing-decision-reasoning",
    "revpar_publish": "tools/revpar_estimate.py",
}
STAGE_CALLED_SKILL_DEFAULTS = {
    "hotel_comps_moodtrip": "moodtrip-hotel-search",
    "pricing_decision": "pricing-decision-reasoning",
    "revpar_publish": "pricing-output-publisher",
}


def utc_timestamp() -> str:
    return dt.datetime.now(dt.UTC).isoformat().replace("+00:00", "Z")


def parse_json_object(raw: str | None, field_name: str) -> dict[str, Any] | None:
    if not raw:
        return None
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{field_name} must be valid JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{field_name} must be a JSON object")
    return value


def write_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


def build_event_payload(
    *,
    run_id: str,
    stage: str,
    status: str,
    message: str,
    property_id: str | None = None,
    substage: str | None = None,
    workflow: str | None = None,
    skill: str | None = None,
    called_skill: str | None = None,
    caller_skill: str | None = None,
    tool: str | None = None,
    error: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    status = status.strip().lower()
    if status not in STATUSES:
        raise ValueError(f"status must be one of: {', '.join(sorted(STATUSES))}")

    stage = stage.strip()

    if stage in STAGE_TOOL_DEFAULTS:
        workflow = workflow or WORKFLOW_NAME
        skill = skill or workflow
        called_skill = called_skill or STAGE_CALLED_SKILL_DEFAULTS.get(stage)
        if not tool or tool.strip().lower() in WORKFLOW_TOOL_ALIASES:
            tool = STAGE_TOOL_DEFAULTS[stage]

    payload: dict[str, Any] = {
        "timestamp": utc_timestamp(),
        "run_id": run_id,
        "stage": stage,
        "status": status,
        "message": message,
    }
    optional_fields = {
        "property_id": property_id,
        "substage": substage,
        "workflow": workflow,
        "skill": skill,
        "called_skill": called_skill,
        "caller_skill": caller_skill,
        "tool": tool,
        "error": error,
    }
    payload.update({key: value for key, value in optional_fields.items() if value})
    if metadata is not None:
        payload["metadata"] = metadata
    return payload


def append_event(log_path: str | Path, **kwargs: Any) -> dict[str, Any]:
    payload = build_event_payload(**kwargs)
    write_jsonl(Path(log_path), payload)
    return payload


def clear_log(log_path: str | Path) -> dict[str, str]:
    path = Path(log_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("", encoding="utf-8")
    return {"log_path": str(path), "status": "cleared"}


def cmd_log(args: argparse.Namespace) -> None:
    status = args.status.strip().lower()
    if status not in STATUSES:
        raise ValueError(f"status must be one of: {', '.join(sorted(STATUSES))}")
    metadata = parse_json_object(args.metadata_json, "metadata_json")
    payload = append_event(
        args.log_path,
        run_id=args.run_id,
        stage=args.stage,
        status=args.status,
        message=args.message,
        property_id=args.property_id,
        substage=args.substage,
        workflow=args.workflow,
        skill=args.skill,
        called_skill=args.called_skill,
        caller_skill=args.caller_skill,
        tool=args.tool,
        error=args.error,
        metadata=metadata,
    )
    print(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True))


def cmd_clear(args: argparse.Namespace) -> None:
    print(json.dumps(clear_log(args.log_path), indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Append RevNest workflow progress events as JSONL")
    parser.add_argument("--log-path", default=str(DEFAULT_LOG_PATH), help="Progress JSONL file path")
    sub = parser.add_subparsers(dest="command", required=True)

    log = sub.add_parser("log", help="Append one progress event")
    log.add_argument("--run-id", required=True, help="Stable id for this workflow run")
    log.add_argument("--stage", required=True, help="Workflow stage id")
    log.add_argument("--substage", help="Optional step within a stage, for example guardrail_check")
    log.add_argument("--status", required=True, help="started, completed, skipped, failed, or info")
    log.add_argument("--message", required=True, help="Short user-facing progress message")
    log.add_argument("--property-id", help="RevNest property id when known")
    log.add_argument("--workflow", help="Top-level workflow, for example pricing-workflow")
    log.add_argument("--skill", help="Skill currently handling this stage")
    log.add_argument("--called-skill", help="Sub-skill invoked by the current skill, when relevant")
    log.add_argument("--caller-skill", help="Parent skill that invoked the current skill, when relevant")
    log.add_argument("--tool", help="Specific executable/tool involved, for example tools/weather_tool.py")
    log.add_argument("--error", help="Error text for failed/skipped events")
    log.add_argument("--metadata-json", help="Optional JSON object with compact extra details")
    log.set_defaults(func=cmd_log)

    clear = sub.add_parser("clear", help="Truncate the progress log")
    clear.set_defaults(func=cmd_clear)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    try:
        args.func(args)
    except Exception as exc:
        print(json.dumps({"error": str(exc)}, indent=2, ensure_ascii=False))
        raise SystemExit(2)


if __name__ == "__main__":
    main()
