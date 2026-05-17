#!/usr/bin/env python3
"""Nemotron-only compact reasoning worker for RevNest pricing decisions.

OpenClaw's main agent model may orchestrate tools, but pricing reasoning must be
produced here with the configured Nemotron endpoint. The output is intentionally
compact JSON so it can be logged, persisted, and shown in WebApp without storing
hidden chain-of-thought.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import ssl
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
TOOLS_DIR = ROOT / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import progress_logger  # noqa: E402
import reasoning_step_logger  # noqa: E402


DEFAULT_MODEL = "nemotron-3-super:latest"
DEFAULT_TRACE_MODEL = "nemotron3:33b"
DEFAULT_BASE_URL = "http://127.0.0.1:11434/v1"
DEFAULT_TIMEOUT_SECONDS = int(os.environ.get("REVNEST_TRACE_REASONING_TIMEOUT_SECONDS", "45"))
DEFAULT_MAX_CONTEXT_CHARS = int(os.environ.get("REVNEST_TRACE_REASONING_MAX_CONTEXT_CHARS", "6000"))
DEFAULT_MAX_TOKENS = int(os.environ.get("REVNEST_TRACE_REASONING_MAX_TOKENS", "256"))


def ollama_model_available(model: str) -> bool:
    if not shutil.which("ollama"):
        return False
    try:
        result = subprocess.run(
            ["ollama", "list"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=3,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    if result.returncode != 0:
        return False
    wanted = model.split(":", 1)[0]
    return any(line.split()[0] in {model, wanted} for line in result.stdout.splitlines() if line.split())


def default_model() -> str:
    if os.environ.get("REVNEST_TRACE_REASONING_MODEL"):
        return os.environ["REVNEST_TRACE_REASONING_MODEL"]
    if ollama_model_available(DEFAULT_TRACE_MODEL):
        return DEFAULT_TRACE_MODEL
    return os.environ.get("REVNEST_FINAL_REASONING_MODEL", DEFAULT_MODEL)


def default_base_url() -> str:
    return (
        os.environ.get("REVNEST_TRACE_REASONING_BASE_URL")
        or os.environ.get("REVNEST_FINAL_REASONING_BASE_URL")
        or os.environ.get("OPENAI_BASE_URL")
        or DEFAULT_BASE_URL
    ).rstrip("/")


def compact_json(value: Any, limit: int) -> str:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    if len(text) <= limit:
        return text
    return text[:limit] + "...<truncated>"


def read_payload(args: argparse.Namespace) -> dict[str, Any]:
    if args.input_json:
        payload = json.loads(args.input_json)
    else:
        raw = sys.stdin.read()
        if not raw.strip():
            raise ValueError("Expected JSON on stdin or --input-json.")
        payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("Reasoning input must be a JSON object.")
    return payload


def build_prompt(task: str, payload: dict[str, Any], max_context_chars: int) -> str:
    return f"""You are the Nemotron pricing reasoning worker for RevNest.

Role boundary:
- Produce the compact pricing reasoning for exactly one substage.
- Do not call tools.
- Do not include hidden chain-of-thought.
- Use only the provided context. If support is missing, say that in the JSON.

Substage:
{task}

Return JSON only with this schema:
{{
  "status": "completed" | "insufficient_context",
  "summary": "one user-facing sentence, no hidden chain-of-thought",
  "facts": ["short observable facts"],
  "metrics": {{"key": "value"}},
  "sources": ["tool/source ids from the provided context"],
  "confidence": "low" | "medium" | "high"
}}

Provided context JSON:
{compact_json(payload, max_context_chars)}
"""


def call_model(base_url: str, model: str, prompt: str, timeout: int, max_tokens: int) -> dict[str, Any]:
    body = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
        "max_tokens": max_tokens,
        "stream": False,
    }
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": "Bearer local"},
        method="POST",
    )
    context = ssl._create_unverified_context() if base_url.startswith("https://") else None
    with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
        return json.loads(response.read().decode("utf-8"))


def extract_json(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        if stripped.startswith("json"):
            stripped = stripped[4:].strip()
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start < 0 or end < start:
        raise ValueError("Nemotron reasoning model did not return JSON.")
    value = json.loads(stripped[start : end + 1])
    if not isinstance(value, dict):
        raise ValueError("Nemotron reasoning output must be a JSON object.")
    return value


def clean_text(value: object, limit: int) -> str:
    text = " ".join(str(value or "").split())
    return text[:limit]


def normalize_list(value: object, limit: int = 10) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        value = [value]
    return [clean_text(item, 240) for item in value if str(item).strip()][:limit]


def normalize_result(raw: dict[str, Any], *, task: str, model: str, base_url: str) -> dict[str, Any]:
    status = str(raw.get("status") or "completed").strip().lower()
    if status not in {"completed", "insufficient_context"}:
        status = "insufficient_context"
    metrics = raw.get("metrics") if isinstance(raw.get("metrics"), dict) else {}
    metrics = {str(key): value for key, value in metrics.items()}
    metrics["reasoning_model"] = model
    metrics["reasoning_endpoint"] = base_url
    return {
        "source": "nemotron_reasoning",
        "task": task,
        "status": status,
        "summary": clean_text(raw.get("summary"), 700) or "Nemotron did not provide a summary.",
        "facts": normalize_list(raw.get("facts")),
        "metrics": metrics,
        "sources": normalize_list(raw.get("sources")),
        "confidence": str(raw.get("confidence") or "medium").strip().lower()
        if str(raw.get("confidence") or "").strip().lower() in {"low", "medium", "high"}
        else "medium",
        "model": model,
        "base_url": base_url,
    }


def maybe_log_started(args: argparse.Namespace, prompt_chars: int) -> None:
    if not args.log_path or not args.run_id:
        return
    progress_logger.append_event(
        args.log_path,
        run_id=args.run_id,
        stage=args.stage,
        substage=args.substage or args.task,
        status="started",
        message=f"Starting compact reasoning for {args.substage or args.task} with {args.model}.",
        property_id=args.property_id,
        workflow="pricing-workflow",
        skill="pricing-workflow",
        called_skill="pricing-decision-reasoning",
        tool="tools/nemotron_reasoning.py",
        metadata={
            "reasoningModel": args.model,
            "reasoningEndpoint": args.base_url,
            "reasoningEngine": "nemotron",
            "promptChars": prompt_chars,
            "timeoutSeconds": args.timeout_seconds,
            "maxTokens": args.max_tokens,
            "qwenRole": "tool_call_orchestration_only",
        },
    )


def error_result(args: argparse.Namespace, exc: Exception) -> dict[str, Any]:
    text = str(exc)
    if isinstance(exc, TimeoutError) or isinstance(exc, socket.timeout):
        text = f"Timed out after {args.timeout_seconds}s waiting for {args.model}."
    elif isinstance(exc, urllib.error.URLError) and isinstance(getattr(exc, "reason", None), socket.timeout):
        text = f"Timed out after {args.timeout_seconds}s waiting for {args.model}."
    return {
        "source": "nemotron_reasoning",
        "task": args.task,
        "status": "error",
        "summary": clean_text(f"Nemotron reasoning failed for {args.task}: {text}", 700),
        "facts": [],
        "metrics": {
            "reasoning_model": args.model,
            "reasoning_endpoint": args.base_url,
            "timeout_seconds": args.timeout_seconds,
            "error": clean_text(text, 300),
        },
        "sources": ["tools/nemotron_reasoning.py"],
        "confidence": "low",
        "model": args.model,
        "base_url": args.base_url,
    }


def maybe_log_progress(args: argparse.Namespace, result: dict[str, Any]) -> None:
    if not args.log_path or not args.run_id:
        return
    progress_logger.append_event(
        args.log_path,
        run_id=args.run_id,
        stage=args.stage,
        substage=args.substage or args.task,
        status="info" if result["status"] == "completed" else "failed",
        message=result["summary"],
        property_id=args.property_id,
        workflow="pricing-workflow",
        skill="pricing-workflow",
        called_skill="pricing-decision-reasoning",
        tool="tools/nemotron_reasoning.py",
        error=None if result["status"] == "completed" else result["summary"],
        metadata={
            "facts": result["facts"],
            "metrics": result["metrics"],
            "sources": result["sources"],
            "confidence": result["confidence"],
            "reasoningModel": result["model"],
            "reasoningEndpoint": result["base_url"],
            "reasoningEngine": "nemotron",
            "qwenRole": "tool_call_orchestration_only",
        },
    )


def maybe_persist(args: argparse.Namespace, result: dict[str, Any]) -> None:
    if args.no_persist or not args.account_id or not args.run_id:
        return
    reasoning_step_logger.upsert_reasoning_step(
        account_id=args.account_id,
        run_id=args.run_id,
        property_id=args.property_id,
        stage=args.stage,
        substage=args.substage or args.task,
        summary=result["summary"],
        facts=result["facts"],
        metrics=result["metrics"],
        tool="tools/nemotron_reasoning.py",
        sources=result["sources"],
        confidence=result["confidence"],
        group_key=args.group_key,
        database_url=args.database_url,
        dry_run=args.dry_run,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run one compact pricing reasoning substage through Nemotron.")
    parser.add_argument("--task", required=True, help="Pricing reasoning substage, for example supply_snapshot.")
    parser.add_argument("--input-json", help="Compact substage input JSON. If omitted, JSON is read from stdin.")
    parser.add_argument("--model", default=default_model())
    parser.add_argument("--base-url", default=default_base_url())
    parser.add_argument("--timeout-seconds", type=int, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--max-context-chars", type=int, default=DEFAULT_MAX_CONTEXT_CHARS)
    parser.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS)
    parser.add_argument("--account-id")
    parser.add_argument("--run-id")
    parser.add_argument("--property-id")
    parser.add_argument("--stage", default="pricing_decision")
    parser.add_argument("--substage")
    parser.add_argument("--group-key")
    parser.add_argument("--log-path")
    parser.add_argument("--database-url")
    parser.add_argument("--no-persist", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="Do not call Nemotron; print prompt metadata and optional dry-run DB SQL.")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        payload = read_payload(args)
        prompt = build_prompt(args.task, payload, args.max_context_chars)
        if args.dry_run:
            result = {
                "source": "nemotron_reasoning",
                "task": args.task,
                "status": "dry_run",
                "summary": f"Dry run for {args.task}",
                "facts": [],
                "metrics": {"reasoning_model": args.model, "reasoning_endpoint": args.base_url, "prompt_chars": len(prompt)},
                "sources": [],
                "confidence": "medium",
                "model": args.model,
                "base_url": args.base_url,
            }
        else:
            maybe_log_started(args, len(prompt))
            response = call_model(args.base_url, args.model, prompt, args.timeout_seconds, args.max_tokens)
            message = response.get("choices", [{}])[0].get("message", {})
            raw_text = message.get("content") or message.get("reasoning") or ""
            result = normalize_result(extract_json(raw_text), task=args.task, model=args.model, base_url=args.base_url)
        maybe_log_progress(args, result)
        maybe_persist(args, result)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0 if result["status"] in {"completed", "dry_run"} else 2
    except Exception as exc:
        if "args" in locals():
            result = error_result(args, exc)
            maybe_log_progress(args, result)
            maybe_persist(args, result)
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        else:
            print(
                json.dumps(
                    {
                        "source": "nemotron_reasoning",
                        "status": "error",
                        "task": None,
                        "model": DEFAULT_MODEL,
                        "base_url": DEFAULT_BASE_URL,
                        "error": str(exc),
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
