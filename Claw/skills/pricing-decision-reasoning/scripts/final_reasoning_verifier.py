#!/usr/bin/env python3
"""Final compact pricing-reasoning verifier using a stronger local model.

This script is intentionally JSON-in / JSON-out. It asks the configured model
to audit only the provided evidence and final calendar, then returns a compact
verdict suitable for logging and publication gates.
"""

from __future__ import annotations

import argparse
import json
import os
import ssl
import sys
import urllib.error
import urllib.request
from typing import Any


DEFAULT_MODEL = "nemotron-3-super:latest"
DEFAULT_HOST_BASE_URL = "http://127.0.0.1:11434/v1"
DEFAULT_SANDBOX_BASE_URL = "https://inference.local/v1"


def default_base_url() -> str:
    env_value = os.environ.get("REVNEST_FINAL_REASONING_BASE_URL") or os.environ.get("OPENAI_BASE_URL")
    if env_value:
        return env_value.rstrip("/")
    if os.path.exists("/sandbox"):
        return DEFAULT_SANDBOX_BASE_URL
    return DEFAULT_HOST_BASE_URL


def read_payload(args: argparse.Namespace) -> dict[str, Any]:
    if args.input_json:
        return json.loads(args.input_json)
    raw = sys.stdin.read()
    if not raw.strip():
        raise ValueError("Expected JSON on stdin or --input-json.")
    return json.loads(raw)


def compact_json(value: Any, limit: int) -> str:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    if len(text) <= limit:
        return text
    return text[:limit] + "...<truncated>"


def build_prompt(payload: dict[str, Any], max_chars: int) -> str:
    return f"""You are the final pricing reasoning verifier for RevNest.

Grounding rule:
Answer strictly and only based on the provided context. If you cannot find the answer in the context, say you don't know.

Task:
Audit whether the final price calendar is supported by the provided strategy citations, supply-demand facts, occupancy estimator output, guardrails, and calculator output. Do not invent facts. Do not include hidden chain-of-thought. Return JSON only.

Required JSON schema:
{{
  "status": "approved" | "rejected",
  "summary": "one concise sentence",
  "issues": ["compact issue strings"],
  "checked": {{
    "strategy_rag": true,
    "occupancy_estimator": true,
    "guardrails": true,
    "calculator": true
  }}
}}

Reject if any required evidence is missing, if the calendar lacks strategy_memory_initial/review, if strategy_validation_status is not supported/corrected, if occupancy was not sourced from occupancy_rate_estimator.py, or if final prices violate guardrails.

Provided context JSON:
{compact_json(payload, max_chars)}
"""


def extract_json(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        if stripped.startswith("json"):
            stripped = stripped[4:].strip()
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start < 0 or end < start:
        raise ValueError("Verifier model did not return JSON.")
    return json.loads(stripped[start : end + 1])


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
        raw = response.read().decode("utf-8")
    return json.loads(raw)


def normalize_verdict(value: dict[str, Any]) -> dict[str, Any]:
    status = str(value.get("status") or "").strip().lower()
    if status not in {"approved", "rejected"}:
        status = "rejected"
    issues = value.get("issues")
    if not isinstance(issues, list):
        issues = [str(issues)] if issues else []
    checked = value.get("checked")
    if not isinstance(checked, dict):
        checked = {}
    return {
        "source": "final_reasoning_verifier",
        "status": status,
        "summary": " ".join(str(value.get("summary") or "").split())[:500],
        "issues": [" ".join(str(item).split())[:240] for item in issues if str(item).strip()][:8],
        "checked": {
            "strategy_rag": bool(checked.get("strategy_rag")),
            "occupancy_estimator": bool(checked.get("occupancy_estimator")),
            "guardrails": bool(checked.get("guardrails")),
            "calculator": bool(checked.get("calculator")),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify a final RevNest price calendar with a stronger local model.")
    parser.add_argument("--input-json", help="Verification payload JSON. If omitted, JSON is read from stdin.")
    parser.add_argument("--model", default=os.environ.get("REVNEST_FINAL_REASONING_MODEL", DEFAULT_MODEL))
    parser.add_argument("--base-url", default=default_base_url())
    parser.add_argument("--timeout-seconds", type=int, default=300)
    parser.add_argument("--max-context-chars", type=int, default=18000)
    parser.add_argument("--max-tokens", type=int, default=768)
    parser.add_argument("--dry-run", action="store_true", help="Print prompt metadata without calling the model.")
    args = parser.parse_args()

    try:
        payload = read_payload(args)
        prompt = build_prompt(payload, args.max_context_chars)
        if args.dry_run:
            print(
                json.dumps(
                    {
                        "source": "final_reasoning_verifier",
                        "status": "dry_run",
                        "model": args.model,
                        "base_url": args.base_url,
                        "prompt_chars": len(prompt),
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
            return
        response = call_model(args.base_url, args.model, prompt, args.timeout_seconds, args.max_tokens)
        content = response.get("choices", [{}])[0].get("message", {}).get("content") or ""
        reasoning = response.get("choices", [{}])[0].get("message", {}).get("reasoning") or ""
        verdict = normalize_verdict(extract_json(content or reasoning))
        verdict["model"] = args.model
        verdict["base_url"] = args.base_url
        print(json.dumps(verdict, ensure_ascii=False, sort_keys=True))
        if verdict["status"] != "approved":
            raise SystemExit(2)
    except Exception as exc:
        print(
            json.dumps(
                {
                    "source": "final_reasoning_verifier",
                    "status": "error",
                    "model": args.model,
                    "base_url": args.base_url,
                    "error": str(exc),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
