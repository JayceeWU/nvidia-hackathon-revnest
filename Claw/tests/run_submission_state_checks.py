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
    "Claw/nemoclaw/revnest-safe-pms.yaml",
    "Claw/nemoclaw/enable_revnest_safe_pms.sh",
    "Claw/nemoclaw/evidence/demo_transcript.md",
    "Claw/nemoclaw/evidence/full_hotel_agent_run/README.md",
    "Claw/tests/run_safe_pms_evidence_chain_demo.py",
    "Claw/tests/run_full_hotel_agent_evidence_design.py",
    "Claw/tests/run_hotel_seed_consistency_tests.py",
    "Claw/tests/run_demo1_airbnb_e2e.py",
    "Claw/tests/run_demo2_hotel_e2e.py",
    "Claw/tools/run_pricing_agent.py",
    "Claw/tools/run_hotel_heartbeat.py",
    "WebApp/package.json",
    "WebApp/app/page.js",
    "MockHotel/package.json",
    "MockHotel/sql/schema.sql",
    "MockHotel/sql/data.sql",
]


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
    lowercase_dir_exists = (ROOT / "claw").exists()
    tracked_lowercase = [path for path in git_lines("ls-files") if path.startswith("claw/")]
    high_value_untracked = [
        line
        for line in git_lines("status", "--short")
        if line.startswith("?? WebApp/")
        or line.startswith("?? MockHotel/")
        or line.startswith("?? README.md")
        or line.startswith("?? Claw/tests/")
        or line.startswith("?? Claw/nemoclaw/evidence/")
    ]
    expected_submission_commands = [
        "git rm -r --cached claw",
        "git add README.md .gitignore Claw WebApp MockHotel",
        "git status --short",
    ]
    result = {
        "ok": not missing and not lowercase_dir_exists,
        "root": str(ROOT),
        "missing_required_paths": missing,
        "lowercase_claw_directory_exists": lowercase_dir_exists,
        "tracked_lowercase_claw_paths": tracked_lowercase,
        "high_value_untracked_paths": high_value_untracked,
        "expected_submission_commands": expected_submission_commands,
        "notes": [
            "The working tree intentionally uses uppercase Claw as the canonical path.",
            "If tracked_lowercase_claw_paths is non-empty, stage their deletion before final submission.",
            "If high_value_untracked_paths is non-empty, stage those directories/files before final submission.",
        ],
    }
    print(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
