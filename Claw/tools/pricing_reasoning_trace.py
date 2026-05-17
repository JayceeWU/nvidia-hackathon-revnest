#!/usr/bin/env python3
"""Ensure RevNest pricing runs have a WebApp-visible reasoning trace.

The default path emits compact source-fact trace steps immediately. Optional
Nemotron refinement can replace those summaries later, but live demos never wait
minutes for the large final-verifier model before showing useful progress.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
TOOLS_DIR = ROOT / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import nemotron_reasoning  # noqa: E402
import progress_logger  # noqa: E402
import reasoning_step_logger  # noqa: E402


CORE_SUBSTAGES = [
    "supply_snapshot",
    "demand_snapshot",
    "supply_demand_synthesis",
    "occupancy_result",
    "guardrail_check",
    "calculator_run",
    "final_calendar",
    "final_reasoning_verification",
]

DEFAULT_LOG_PATH = ROOT / "runs" / "airbnb-pricing-progress.log"


def as_object(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def clean_text(value: object, limit: int = 700) -> str:
    text = " ".join(str(value or "").split())
    return text[:limit]


def read_json_arg(raw: str | None, *, field: str) -> Any:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{field} must be valid JSON") from exc


def read_json_file(path: str | Path | None) -> Any:
    if not path:
        return None
    file_path = Path(path)
    if not file_path.exists():
        return None
    return json.loads(file_path.read_text(encoding="utf-8"))


def read_progress_events(log_path: Path, run_id: str) -> list[dict[str, Any]]:
    if not log_path.exists():
        return []
    events: list[dict[str, Any]] = []
    for line in log_path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and value.get("run_id") == run_id:
            events.append(value)
    return events


def placeholder_messages(substage: str) -> set[str]:
    return {
        substage,
        substage.replace("_", " "),
        substage.replace("_", "-"),
        f"{substage}.",
    }


def is_complete_reasoning_event(event: dict[str, Any]) -> bool:
    if event.get("stage") != "pricing_decision":
        return False
    substage = str(event.get("substage") or "").strip()
    if substage not in CORE_SUBSTAGES:
        return False
    metadata = as_object(event.get("metadata"))
    message = clean_text(event.get("message"), 1200)
    normalized_message = message.strip().lower()
    has_rich_metadata = any(
        key in metadata
        for key in (
            "facts",
            "metrics",
            "sources",
            "confidence",
            "reasoningEngine",
            "finalReasoningVerification",
        )
    )
    meaningful_message = bool(message) and normalized_message not in placeholder_messages(substage)
    meaningful_message = meaningful_message and len(normalized_message) > max(24, len(substage) + 4)
    return has_rich_metadata and meaningful_message


def complete_substages(events: list[dict[str, Any]]) -> set[str]:
    return {str(event.get("substage")) for event in events if is_complete_reasoning_event(event)}


def completion_summary(events: list[dict[str, Any]]) -> dict[str, Any]:
    complete = complete_substages(events)
    missing = [substage for substage in CORE_SUBSTAGES if substage not in complete]
    return {
        "complete_substages": sorted(complete),
        "missing_substages": missing,
        "complete_count": len(complete),
        "core_count": len(CORE_SUBSTAGES),
    }


def compact_event(event: dict[str, Any]) -> dict[str, Any]:
    metadata = as_object(event.get("metadata"))
    return {
        "stage": event.get("stage"),
        "substage": event.get("substage"),
        "status": event.get("status"),
        "message": clean_text(event.get("message"), 500),
        "tool": event.get("tool") or event.get("called_skill") or event.get("skill"),
        "metadata": {
            key: metadata[key]
            for key in ("facts", "metrics", "sources", "confidence", "reasoningEngine", "pending_task_count")
            if key in metadata
        },
    }


def walk(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)


def first_value(value: Any, keys: tuple[str, ...]) -> Any:
    wanted = {key.lower() for key in keys}
    for item in walk(value):
        for key, child in item.items():
            if str(key).lower() in wanted and child not in (None, "", []):
                return child
    return None


def count_listish(value: Any, key_terms: tuple[str, ...]) -> int | None:
    best = 0
    terms = tuple(term.lower() for term in key_terms)
    for item in walk(value):
        for key, child in item.items():
            lowered = str(key).lower()
            if any(term in lowered for term in terms) and isinstance(child, list):
                best = max(best, len(child))
    return best or None


def number_value(value: Any, keys: tuple[str, ...]) -> float | None:
    raw = first_value(value, keys)
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def property_name(property_payload: Any, events: list[dict[str, Any]], property_id: str | None) -> str:
    value = first_value(property_payload, ("name", "listingTitle", "title", "roomType"))
    if value:
        return clean_text(value, 120)
    for event in reversed(events):
        profile = as_object(as_object(event.get("metadata")).get("profile"))
        value = first_value(profile, ("listingTitle", "name", "title"))
        if value:
            return clean_text(value, 120)
    return property_id or "this property"


def market_name(property_payload: Any, market_data: Any, events: list[dict[str, Any]]) -> str:
    value = first_value(property_payload, ("city", "market", "location", "address", "state"))
    if value:
        return clean_text(value, 120)
    value = first_value(market_data, ("city", "market", "location", "address", "destination"))
    if value:
        return clean_text(value, 120)
    for event in reversed(events):
        message = str(event.get("message") or "")
        if "Santa Cruz" in message:
            return "Santa Cruz"
    return "the verified market"


def latest_guardrail_event(events: list[dict[str, Any]]) -> dict[str, Any] | None:
    return next((event for event in reversed(events) if event.get("stage") == "guardrail_review"), None)


def source_fact_steps(
    *,
    run_id: str,
    property_id: str | None,
    events: list[dict[str, Any]],
    market_data: Any,
    property_payload: Any,
    price_calendar: Any,
) -> dict[str, dict[str, Any]]:
    name = property_name(property_payload, events, property_id)
    market = market_name(property_payload, market_data, events)
    event_count = count_listish(market_data, ("event",)) or count_listish(events, ("event",)) or 0
    comp_count = count_listish(market_data, ("comp", "hotel", "vacation", "rate")) or 0
    weather = first_value(market_data, ("summary", "weather", "conditions")) or "weather source returned"
    min_price = number_value(property_payload, ("min_price", "minPrice", "min_price_cents"))
    max_price = number_value(property_payload, ("max_price", "maxPrice", "max_price_cents"))
    if min_price and min_price > 1000:
        min_price = round(min_price / 100, 2)
    if max_price and max_price > 1000:
        max_price = round(max_price / 100, 2)
    guardrail_message = clean_text((latest_guardrail_event(events) or {}).get("message"), 240)
    calendar_rows = as_list(price_calendar)
    if not calendar_rows:
        calendar_rows = as_list(first_value(market_data, ("priceCalendar", "price_calendar", "calendar")))
    current_price = number_value(calendar_rows, ("current_price", "fixed_price", "fixed"))
    final_price = number_value(calendar_rows, ("final_price_after_guardrails", "agent_price", "agent"))

    common = {
        "run_id": run_id,
        "property_id": property_id,
        "trace_state": "source_fact_trace_ready",
    }
    return {
        "supply_snapshot": {
            "summary": f"Source facts are ready for {name} in {market}: market-data fan-in completed and found {comp_count or 'available'} supply/comparison signal(s).",
            "facts": ["market-data fan-in completed", f"property: {name}", f"market: {market}"],
            "metrics": {**common, "comp_signal_count": comp_count},
            "sources": ["progress_log", "market_data_bundle"],
            "confidence": "medium" if comp_count else "low",
        },
        "demand_snapshot": {
            "summary": f"Demand source facts for {market} are visible: event, weather, holiday, and tourism inputs have been collected for pricing review.",
            "facts": [f"event signals: {event_count or 'available'}", f"weather: {clean_text(weather, 80)}", "tourism/seasonality source collected"],
            "metrics": {**common, "event_signal_count": event_count},
            "sources": ["events", "weather", "holidays", "tourism"],
            "confidence": "medium",
        },
        "supply_demand_synthesis": {
            "summary": "The fast trace has enough observable supply and demand inputs to continue pricing while bounded Nemotron refinement remains optional.",
            "facts": ["supply facts available", "demand facts available", "hidden chain-of-thought not stored"],
            "metrics": {**common, "refinement_optional": True},
            "sources": ["market_data_bundle", "progress_log"],
            "confidence": "medium",
        },
        "occupancy_result": {
            "summary": "Occupancy reasoning is represented from source facts first; deterministic occupancy or model refinement can update this step when available.",
            "facts": ["occupancy step is visible before long model calls", "pricing must still respect estimator/calculator evidence"],
            "metrics": {**common, "occupancy_trace_state": "source_fact_placeholder"},
            "sources": ["market_data_bundle", "pricing-decision-reasoning"],
            "confidence": "low",
        },
        "guardrail_check": {
            "summary": guardrail_message or f"Guardrail source facts are visible for {name}; final recommendations remain bounded by configured min/max prices.",
            "facts": ["guardrails collected", "final price must stay within bounds", "live write requires approval when applicable"],
            "metrics": {**common, "min_price": min_price, "max_price": max_price},
            "sources": ["guardrail_review", "property"],
            "confidence": "medium" if guardrail_message else "low",
        },
        "calculator_run": {
            "summary": "Calculator trace step is visible; final numeric recommendations must come from the deterministic calculator or saved price calendar output.",
            "facts": ["calculator output required", "source-fact trace does not invent final prices"],
            "metrics": {**common, "current_price": current_price, "final_price_after_guardrails": final_price},
            "sources": ["pricing_decision_calculator", "property_price"],
            "confidence": "low" if final_price is None else "medium",
        },
        "final_calendar": {
            "summary": "Final calendar trace is open and waiting for guarded price rows; any displayed final prices must come from persisted calculator/publisher output.",
            "facts": ["calendar step is visible", "guarded rows required before publish", "no source-fact final price invention"],
            "metrics": {**common, "calendar_rows": len(calendar_rows)},
            "sources": ["pricing-output-publisher", "property_price"],
            "confidence": "low" if not calendar_rows else "medium",
        },
        "final_reasoning_verification": {
            "summary": "Final verification remains pending until the stronger verifier approves supported strategy, guardrails, calculator output, and publish boundaries.",
            "facts": ["final verifier still required", "source-fact trace is not final approval", "approval boundary preserved"],
            "metrics": {**common, "status": "pending", "final_verifier_required": True},
            "sources": ["final_reasoning_verifier.py", "pricing-decision-reasoning"],
            "confidence": "low",
        },
    }


def build_substage_context(
    *,
    substage: str,
    run_id: str,
    property_id: str | None,
    events: list[dict[str, Any]],
    market_data: Any,
    property_payload: Any,
    price_calendar: Any,
) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "property_id": property_id,
        "requested_substage": substage,
        "property": property_payload or {},
        "market_data": market_data or {},
        "price_calendar": price_calendar or [],
        "recent_progress_events": [compact_event(event) for event in events[-40:]],
        "display_contract": {
            "purpose": "WebApp-visible compact pricing reasoning timeline",
            "forbidden": "hidden chain-of-thought, raw prompts, private deliberation",
            "include": "observable facts, numeric metrics, tool/source ids, confidence, and a concise decision summary",
        },
    }


def run_nemotron_substage(
    *,
    substage: str,
    context: dict[str, Any],
    model: str,
    base_url: str,
    timeout_seconds: int,
    max_context_chars: int,
    max_tokens: int,
) -> dict[str, Any]:
    prompt = nemotron_reasoning.build_prompt(substage, context, max_context_chars)
    response = nemotron_reasoning.call_model(base_url, model, prompt, timeout_seconds, max_tokens)
    message = response.get("choices", [{}])[0].get("message", {})
    raw_text = message.get("content") or message.get("reasoning") or ""
    return nemotron_reasoning.normalize_result(
        nemotron_reasoning.extract_json(raw_text),
        task=substage,
        model=model,
        base_url=base_url,
    )


def emit_compact_reasoning_step(
    *,
    log_path: str | Path,
    account_id: str | None,
    run_id: str,
    substage: str,
    summary: str,
    property_id: str | None = None,
    facts: Any = None,
    metrics: dict[str, Any] | None = None,
    tool: str = "pricing-decision-reasoning",
    sources: Any = None,
    confidence: str | None = "medium",
    stage: str = "pricing_decision",
    database_url: str | None = None,
    dry_run: bool = False,
    engine: str = "nemotron",
    model: str | None = None,
    endpoint: str | None = None,
    status: str = "info",
    group_key: str | None = None,
) -> dict[str, Any]:
    facts_list = as_list(facts)
    sources_list = as_list(sources)
    metrics_payload = {str(key): value for key, value in (metrics or {}).items() if value is not None}
    metrics_payload.setdefault("reasoning_engine", engine)
    metadata = {
        "facts": facts_list,
        "metrics": metrics_payload,
        "sources": sources_list,
        "confidence": confidence or "medium",
        "reasoningEngine": engine,
        "qwenRole": "tool_call_orchestration_only",
    }
    if model:
        metadata["reasoningModel"] = model
    if endpoint:
        metadata["reasoningEndpoint"] = endpoint
    verification_status = str(metrics_payload.get("status") or "").strip().lower()
    if substage == "final_reasoning_verification" and verification_status in {"approved", "rejected"}:
        metadata["finalReasoningVerification"] = {
            "status": verification_status,
            "summary": clean_text(summary, 500),
            "model": model,
            "endpoint": endpoint,
            "tool": tool,
            "checked": metrics_payload,
        }

    event = progress_logger.build_event_payload(
        run_id=run_id,
        stage=stage,
        substage=substage,
        status=status,
        message=clean_text(summary, 900),
        property_id=property_id,
        workflow="pricing-workflow",
        skill="pricing-workflow",
        called_skill="pricing-decision-reasoning",
        tool=tool,
        error=clean_text(summary, 1000) if status == "failed" else None,
        metadata=metadata,
    )
    result: dict[str, Any] = {"event": event, "record": None}
    if dry_run:
        result["dry_run"] = True
        return result

    progress_logger.write_jsonl(Path(log_path), event)
    if account_id:
        result["record"] = reasoning_step_logger.upsert_reasoning_step(
            account_id=account_id,
            run_id=run_id,
            property_id=property_id,
            stage=stage,
            substage=substage,
            summary=summary,
            facts=facts_list,
            metrics=metrics_payload,
            tool=tool,
            sources=sources_list,
            confidence=confidence,
            group_key=group_key,
            database_url=database_url,
            dry_run=False,
        )
    return result


def emit_source_fact_trace(
    *,
    args: argparse.Namespace,
    log_path: Path,
    missing: list[str],
    events: list[dict[str, Any]],
    market_data: Any,
    property_payload: Any,
    price_calendar: Any,
) -> list[dict[str, Any]]:
    step_map = source_fact_steps(
        run_id=args.run_id,
        property_id=args.property_id,
        events=events,
        market_data=market_data,
        property_payload=property_payload,
        price_calendar=price_calendar,
    )
    emitted: list[dict[str, Any]] = []
    for substage in missing:
        step = step_map[substage]
        emitted.append(
            emit_compact_reasoning_step(
                log_path=log_path,
                account_id=args.account_id,
                run_id=args.run_id,
                property_id=args.property_id,
                substage=substage,
                summary=step["summary"],
                facts=step["facts"],
                metrics=step["metrics"],
                tool="tools/pricing_reasoning_trace.py",
                sources=step["sources"],
                confidence=step["confidence"],
                database_url=args.database_url,
                dry_run=args.dry_run,
                engine="source_fact_trace",
                model="source-facts",
                endpoint="local-progress-log",
                status="info",
                group_key="source-fact-trace",
            )
        )
    return emitted


def refine_with_nemotron(
    *,
    args: argparse.Namespace,
    log_path: Path,
    substages: list[str],
    events: list[dict[str, Any]],
    market_data: Any,
    property_payload: Any,
    price_calendar: Any,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    emitted: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for substage in substages:
        context = build_substage_context(
            substage=substage,
            run_id=args.run_id,
            property_id=args.property_id,
            events=events,
            market_data=market_data,
            property_payload=property_payload,
            price_calendar=price_calendar,
        )
        try:
            reasoning = run_nemotron_substage(
                substage=substage,
                context=context,
                model=args.model,
                base_url=args.base_url,
                timeout_seconds=args.timeout_seconds,
                max_context_chars=args.max_context_chars,
                max_tokens=args.max_tokens,
            )
            status = "info" if reasoning.get("status") == "completed" else "failed"
            emitted.append(
                emit_compact_reasoning_step(
                    log_path=log_path,
                    account_id=args.account_id,
                    run_id=args.run_id,
                    property_id=args.property_id,
                    substage=substage,
                    summary=reasoning.get("summary") or f"Nemotron could not summarize {substage}.",
                    facts=reasoning.get("facts") or [],
                    metrics=as_object(reasoning.get("metrics")),
                    tool="tools/nemotron_reasoning.py",
                    sources=reasoning.get("sources") or [],
                    confidence=reasoning.get("confidence") or "medium",
                    database_url=args.database_url,
                    dry_run=args.dry_run,
                    engine="nemotron",
                    model=args.model,
                    endpoint=args.base_url,
                    status=status,
                )
            )
            if status == "failed":
                failures.append({"substage": substage, "status": reasoning.get("status"), "summary": reasoning.get("summary")})
        except Exception as exc:  # noqa: BLE001 - surface model/endpoint failures clearly.
            summary = f"Nemotron reasoning trace generation failed for {substage}: {exc}"
            failures.append({"substage": substage, "error": str(exc)})
            emitted.append(
                emit_compact_reasoning_step(
                    log_path=log_path,
                    account_id=args.account_id,
                    run_id=args.run_id,
                    property_id=args.property_id,
                    substage=substage,
                    summary=summary,
                    facts=[],
                    metrics={"reasoning_trace_error": str(exc)},
                    tool="tools/pricing_reasoning_trace.py",
                    sources=["nemotron_reasoning"],
                    confidence="low",
                    database_url=args.database_url,
                    dry_run=args.dry_run,
                    engine="nemotron",
                    model=args.model,
                    endpoint=args.base_url,
                    status="failed",
                )
            )
    return emitted, failures


def ensure_trace(args: argparse.Namespace) -> dict[str, Any]:
    log_path = Path(args.log_path or DEFAULT_LOG_PATH)
    events = read_progress_events(log_path, args.run_id)
    summary = completion_summary(events)
    missing = list(summary["missing_substages"])
    market_data = read_json_file(args.market_data_path)
    property_payload = read_json_arg(args.property_json, field="property_json")
    price_calendar = read_json_arg(args.price_calendar_json, field="price_calendar_json")

    if args.check_only:
        return {"status": "completed" if not missing else "missing_reasoning_steps", "check_only": True, **summary}

    emitted: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    if missing and not args.no_source_fact_trace:
        emitted.extend(
            emit_source_fact_trace(
                args=args,
                log_path=log_path,
                missing=missing,
                events=events,
                market_data=market_data,
                property_payload=property_payload,
                price_calendar=price_calendar,
            )
        )
        events = read_progress_events(log_path, args.run_id) if not args.dry_run else events + [item["event"] for item in emitted]
        summary = completion_summary(events)
        missing = list(summary["missing_substages"])

    if args.refine_with_nemotron:
        refine_targets = CORE_SUBSTAGES if args.refine_all else missing
        refined, refine_failures = refine_with_nemotron(
            args=args,
            log_path=log_path,
            substages=refine_targets,
            events=events,
            market_data=market_data,
            property_payload=property_payload,
            price_calendar=price_calendar,
        )
        emitted.extend(refined)
        failures.extend(refine_failures)
        events = read_progress_events(log_path, args.run_id) if not args.dry_run else events + [item["event"] for item in refined]
        summary = completion_summary(events)
        missing = list(summary["missing_substages"])

    return {
        "status": "completed" if not missing and not failures else "failed" if failures else "missing_reasoning_steps",
        "dry_run": args.dry_run,
        "source_fact_trace": not args.no_source_fact_trace,
        "refined_with_nemotron": args.refine_with_nemotron,
        "emitted_count": len(emitted),
        "failures": failures,
        **summary,
    }


def run_self_test() -> dict[str, Any]:
    events = [
        {"run_id": "self", "stage": "pricing_decision", "substage": "supply_snapshot", "message": "supply_snapshot"},
        {
            "run_id": "self",
            "stage": "pricing_decision",
            "substage": "demand_snapshot",
            "message": "Demand is elevated because local event pressure is visible.",
            "metadata": {"facts": ["event pressure"], "confidence": "medium", "reasoningEngine": "nemotron"},
        },
    ]
    summary = completion_summary(events)
    if "demand_snapshot" not in summary["complete_substages"]:
        raise AssertionError("rich demand_snapshot event should be complete")
    if "supply_snapshot" in summary["complete_substages"]:
        raise AssertionError("placeholder supply_snapshot event should be incomplete")
    emitted = emit_source_fact_trace(
        args=argparse.Namespace(
            account_id="00000000-0000-0000-0000-000000000000",
            run_id="self",
            property_id="self-property",
            database_url=None,
            dry_run=True,
        ),
        log_path=Path("/tmp/revnest-pricing-reasoning-self-test.log"),
        missing=["supply_snapshot", "final_reasoning_verification"],
        events=events,
        market_data={"events": [{"name": "test"}], "comps": [{"rate": 300}]},
        property_payload={"name": "Self Test Property", "city": "Santa Cruz", "minPrice": 100, "maxPrice": 400},
        price_calendar=[],
    )
    if len(emitted) != 2:
        raise AssertionError("source fact trace should emit requested steps")
    metadata = emitted[0]["event"].get("metadata") or {}
    for key in ("facts", "metrics", "sources", "confidence", "reasoningEngine"):
        if key not in metadata:
            raise AssertionError(f"missing metadata key: {key}")
    if metadata["reasoningEngine"] != "source_fact_trace":
        raise AssertionError("source-fact fallback must be explicitly labeled")
    return {"status": "completed", **summary, "dry_run_events": [item["event"] for item in emitted]}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Ensure a WebApp-visible compact pricing reasoning trace exists for a run.")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--run-id")
    parser.add_argument("--account-id")
    parser.add_argument("--property-id")
    parser.add_argument("--log-path", default=str(DEFAULT_LOG_PATH))
    parser.add_argument("--market-data-path")
    parser.add_argument("--property-json")
    parser.add_argument("--price-calendar-json")
    parser.add_argument("--model", default=nemotron_reasoning.default_model())
    parser.add_argument("--base-url", default=nemotron_reasoning.default_base_url())
    parser.add_argument("--database-url")
    parser.add_argument("--timeout-seconds", type=int, default=nemotron_reasoning.DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--max-context-chars", type=int, default=nemotron_reasoning.DEFAULT_MAX_CONTEXT_CHARS)
    parser.add_argument("--max-tokens", type=int, default=nemotron_reasoning.DEFAULT_MAX_TOKENS)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument("--no-source-fact-trace", action="store_true")
    parser.add_argument("--refine-with-nemotron", action="store_true")
    parser.add_argument("--refine-all", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.self_test:
            result = run_self_test()
        else:
            if not args.run_id:
                raise ValueError("--run-id is required unless --self-test is used")
            result = ensure_trace(args)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0 if result.get("status") == "completed" else 2
    except Exception as exc:  # noqa: BLE001 - CLI must return JSON errors for wrapper diagnostics.
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
