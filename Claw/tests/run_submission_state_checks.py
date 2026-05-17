#!/usr/bin/env python3
"""Check the RevNest hackathon submission tree for path/state risks."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[2]

REQUIRED_PATHS = [
    "README.md",
    ".gitignore",
    "Claw/AGENTS.md",
    "Claw/BOOTSTRAP.md",
    "Claw/data/sql/schema.sql",
    "Claw/data/sql/data.sql",
    "Claw/data/sql/test.sql",
    "Claw/nemoclaw/revnest-safe-pms.yaml",
    "Claw/nemoclaw/revnest-judge-minimal.yaml",
    "Claw/nemoclaw/enable_revnest_safe_pms.sh",
    "Claw/nemoclaw/prepare_judge_minimal_sandbox.sh",
    "Claw/nemoclaw/evidence/demo_transcript.md",
    "Claw/nemoclaw/evidence/full_hotel_agent_run/README.md",
    "Claw/tests/run_safe_pms_evidence_chain_demo.py",
    "Claw/tests/run_full_hotel_agent_evidence_design.py",
    "Claw/tests/run_hotel_seed_consistency_tests.py",
    "Claw/tests/run_demo1_airbnb_e2e.py",
    "Claw/tests/run_demo2_hotel_e2e.py",
    "Claw/tools/run_pricing_agent.py",
    "Claw/tools/nemotron_reasoning.py",
    "Claw/tools/pricing_reasoning_trace.py",
    "Claw/tools/run_hotel_heartbeat.py",
    "WebApp/package.json",
    "WebApp/app/page.js",
    "MockHotel/package.json",
    "MockHotel/sql/schema.sql",
    "MockHotel/sql/data.sql",
]

FORBIDDEN_JUDGE_ACTIVE_POLICY_NAMES = [
    "airbnb",
    "npm",
    "pypi",
    "brew",
    "discord",
    "huggingface",
    "slack",
    "telegram",
]

FORBIDDEN_JUDGE_FULL_POLICY_KEYS = [
    "brave",
    "brew",
    "clawhub",
    "discord",
    "github",
    "huggingface",
    "jira",
    "npm_registry",
    "npm_yarn",
    "openclaw_api",
    "openclaw_docs",
    "pypi",
    "revnest_airbnb_browser",
    "slack",
    "telegram",
    "wechat",
]


def line_is_active_policy(line: str) -> bool:
    normalized = line.strip().lower()
    if not normalized:
        return False
    return (
        "active" in normalized
        or normalized.startswith("*")
        or normalized.startswith("[x]")
        or ord(normalized[0]) == 0x25CF
    )


def judge_policy_evidence_violations() -> dict[str, list[str]]:
    policy_list_path = ROOT / "Claw/nemoclaw/evidence/logs/20_judge_minimal_policy_list.log"
    full_policy_path = ROOT / "Claw/nemoclaw/evidence/logs/21_judge_minimal_openshell_policy_full.yaml"
    active_policy_violations: list[str] = []
    unexpected_active_policies: list[str] = []
    full_policy_violations: list[str] = []

    if policy_list_path.exists():
        for line in policy_list_path.read_text(encoding="utf-8").splitlines():
            normalized = line.strip().lower()
            if not line_is_active_policy(line):
                continue
            if any(name in normalized for name in FORBIDDEN_JUDGE_ACTIVE_POLICY_NAMES):
                active_policy_violations.append(line)
            if "revnest-judge-minimal" not in normalized:
                unexpected_active_policies.append(line)

    if full_policy_path.exists():
        for line in full_policy_path.read_text(encoding="utf-8").splitlines():
            normalized = line.strip().lower()
            for key in FORBIDDEN_JUDGE_FULL_POLICY_KEYS:
                if normalized.startswith(f"{key}:"):
                    full_policy_violations.append(line)

    return {
        "forbidden_active_policy_lines": active_policy_violations,
        "unexpected_active_policy_lines": unexpected_active_policies,
        "forbidden_full_policy_keys": full_policy_violations,
    }


def git_lines(*args: str) -> list[str]:
    result = subprocess.run(
        ["git", "-C", str(ROOT), *args],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        return []
    return [line for line in result.stdout.splitlines() if line.strip()]


def main() -> int:
    missing = [path for path in REQUIRED_PATHS if not (ROOT / path).exists()]
    run_agent_text = (ROOT / "Claw/tools/run_pricing_agent.py").read_text(encoding="utf-8", errors="replace")
    decision_skill_text = (ROOT / "Claw/skills/pricing-decision-reasoning/SKILL.md").read_text(encoding="utf-8", errors="replace")
    model_boundary_violations = []
    if "ollama-local/qwen3.6:35b" not in run_agent_text:
        model_boundary_violations.append("run_pricing_agent.py does not default the tool-call model to qwen3.6:35b")
    if "tools/nemotron_reasoning.py" not in run_agent_text or "tools/nemotron_reasoning.py" not in decision_skill_text:
        model_boundary_violations.append("pricing reasoning is not routed through tools/nemotron_reasoning.py")
    if "tool_call_orchestration_only" not in run_agent_text:
        model_boundary_violations.append("model routing metadata does not mark qwen as tool-call orchestration only")
    if "final_reasoning_verifier.py" not in run_agent_text:
        model_boundary_violations.append("final reasoning verifier is not required in the main wrapper prompt")
    if "pricing_reasoning_trace.py" not in run_agent_text:
        model_boundary_violations.append("run_pricing_agent.py does not enforce WebApp-visible pricing reasoning trace completeness")
    lowercase_dir_exists = (ROOT / "claw").exists()
    tracked_lowercase = [path for path in git_lines("ls-files") if path.startswith("claw/")]
    high_value_untracked = [
        line
        for line in git_lines("status", "--short")
        if line.startswith("?? WebApp/")
        or line.startswith("?? MockHotel/")
        or line.startswith("?? README.md")
        or line.startswith("?? Claw/tests/")
        or line.startswith("?? Claw/nemoclaw/")
    ]
    judge_policy_violations = judge_policy_evidence_violations()
    expected_submission_commands = [
        "git rm -r --cached claw",
        "git add README.md .gitignore Claw WebApp MockHotel",
        "git status --short",
    ]
    result = {
        "ok": not missing and not model_boundary_violations and not lowercase_dir_exists and not any(judge_policy_violations.values()),
        "root": str(ROOT),
        "missing_required_paths": missing,
        "lowercase_claw_directory_exists": lowercase_dir_exists,
        "tracked_lowercase_claw_paths": tracked_lowercase,
        "high_value_untracked_paths": high_value_untracked,
        "judge_policy_evidence_violations": judge_policy_violations,
        "model_boundary_violations": model_boundary_violations,
        "expected_submission_commands": expected_submission_commands,
        "notes": [
            "The working tree intentionally uses uppercase Claw as the canonical path.",
            "If tracked_lowercase_claw_paths is non-empty, stage their deletion before final submission.",
            "If high_value_untracked_paths is non-empty, stage those directories/files before final submission.",
            "Judge NemoClaw evidence should show only revnest-judge-minimal active; regenerate logs with prepare_judge_minimal_sandbox.sh if violations appear.",
        ],
    }
    print(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
