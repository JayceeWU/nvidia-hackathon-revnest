#!/usr/bin/env python3
"""Collect compact Airbnb listing context with bounded browser steps."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import progress_logger
import revnest_mcp_server
import run_pricing_agent


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_NAME = "pricing-workflow"


def compact_error(text: str, limit: int = 900) -> str:
    clean = " ".join(str(text or "").split())
    return clean[:limit]


def emit(
    args: argparse.Namespace,
    status: str,
    message: str,
    *,
    substage: str | None = None,
    tool: str = "agent-browser",
    error: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    progress_logger.append_event(
        args.log_path,
        run_id=args.run_id,
        workflow=WORKFLOW_NAME,
        skill=WORKFLOW_NAME,
        called_skill="pricing-context",
        stage="context",
        substage=substage,
        status=status,
        message=message,
        property_id=args.property_id,
        tool=tool,
        error=error,
        metadata=metadata,
    )


def browser_env() -> dict[str, str]:
    env = run_pricing_agent.env_with_local_bins(run_pricing_agent.load_dotenv(os.environ))
    browser_executable = run_pricing_agent.find_browser_executable(env)
    if browser_executable:
        env.setdefault("AGENT_BROWSER_EXECUTABLE_PATH", browser_executable)
    env["AGENT_BROWSER_ARGS"] = run_pricing_agent.merge_browser_args(env.get("AGENT_BROWSER_ARGS"))
    env.setdefault("AGENT_BROWSER_IGNORE_HTTPS_ERRORS", "1")
    return env


def browser(args: argparse.Namespace, *command: str, timeout: int = 20) -> subprocess.CompletedProcess[str]:
    cmd = ["agent-browser", "--session", args.run_id, *command]
    try:
        return subprocess.run(
            cmd,
            cwd=ROOT,
            env=browser_env(),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        output = exc.stdout if isinstance(exc.stdout, str) else ""
        return subprocess.CompletedProcess(cmd, 124, output + f"\nTimed out after {timeout}s")


def parse_json_output(raw: str) -> dict[str, Any]:
    text = raw.strip()
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < start:
        raise ValueError(f"Expected JSON output, got: {compact_error(raw)}")
    return json.loads(text[start : end + 1])


def browser_json(args: argparse.Namespace, *command: str, timeout: int = 20) -> dict[str, Any]:
    result = browser(args, *command, timeout=timeout)
    if result.returncode != 0:
        raise RuntimeError(compact_error(result.stdout))
    payload = parse_json_output(result.stdout)
    if payload.get("success") is False:
        raise RuntimeError(compact_error(payload.get("error") or result.stdout))
    return payload.get("data") if isinstance(payload.get("data"), dict) else payload


def parse_open_output(raw: str) -> tuple[str | None, str | None]:
    title = None
    url = None
    for line in raw.splitlines():
        text = line.strip()
        if not text:
            continue
        if text.startswith("http://") or text.startswith("https://"):
            url = text
        elif text.startswith("✓"):
            title = text.lstrip("✓").strip()
    return title, url


def first_match(text: str, patterns: list[str], flags: int = re.I) -> str | None:
    for pattern in patterns:
        match = re.search(pattern, text, flags)
        if match:
            return next((group for group in match.groups() if group), match.group(0)).strip()
    return None


def int_match(text: str, patterns: list[str]) -> int | None:
    value = first_match(text, patterns)
    if value is None:
        return None
    try:
        return int(float(value))
    except ValueError:
        return None


def listing_type_from_title(title: str) -> str | None:
    match = re.search(r"-\s*([^-\n]+?)\s+for\s+rent\s+in\s+", title, re.I)
    if not match:
        return None
    value = match.group(1).strip()
    singular = {
        "apartments": "Apartment",
        "homes": "Home",
        "houses": "House",
        "condos": "Condo",
        "cabins": "Cabin",
    }.get(value.lower())
    return singular or value.rstrip("s").title()


def location_from_title(title: str) -> tuple[str | None, str | None]:
    match = re.search(r"\s+in\s+([^,\n-]+),\s*([^,\n-]+),\s*United States", title, re.I)
    if not match:
        return None, None
    return match.group(1).strip(), match.group(2).strip()


def room_id_from_url(url: str) -> str | None:
    match = re.search(r"/rooms/([0-9]+)", url)
    return match.group(1) if match else None


def close_translation_dialog(args: argparse.Namespace, snapshot_data: dict[str, Any]) -> bool:
    refs = snapshot_data.get("refs") if isinstance(snapshot_data.get("refs"), dict) else {}
    for ref, meta in refs.items():
        if str(meta.get("role") or "").lower() == "button" and str(meta.get("name") or "").lower() == "close":
            result = browser(args, "click", ref, timeout=8)
            return result.returncode == 0
    return False


def extract_profile(url: str, title: str, snapshot_text: str) -> dict[str, Any]:
    text = f"{title}\n{snapshot_text}"
    city, state = location_from_title(title)
    listing_title = title.split(" - ")[0].strip() if title else None
    neighborhood = first_match(
        text,
        [
            r"In\s+([A-Za-z][A-Za-z0-9 .'-]{2,40}),\s+close",
            r"neighborhood\s+of\s+([A-Za-z][A-Za-z0-9 .'-]{2,40})",
        ],
    )
    rating = first_match(text, [r"([0-5]\.\d{1,2})\s+out of 5", r"Rated\s+([0-5]\.\d{1,2})"])
    reviews = first_match(text, [r"([0-9][0-9,]*)\s+reviews?"])
    permit = first_match(text, [r"\b(STR[0-9-]+)\b"])
    superhost = "Superhost" if re.search(r"\bSuperhost\b", text, re.I) else None

    other_bits = []
    for value in [
        f"Rating {rating}/5" if rating else None,
        f"{reviews} reviews" if reviews else None,
        superhost,
        f"Permit {permit}" if permit else None,
        f"Neighborhood {neighborhood}" if neighborhood else None,
    ]:
        if value:
            other_bits.append(value)

    amenities = []
    for keyword in ["beach", "kitchen", "wifi", "workspace", "parking", "washer", "dryer", "bike"]:
        if re.search(rf"\b{keyword}\b", text, re.I):
            amenities.append(keyword)
    if amenities:
        other_bits.append("Amenities/signals: " + ", ".join(amenities[:10]))

    profile: dict[str, Any] = {
        "airbnbUrl": url,
        "myPlace": url,
        "verificationStatus": "verified",
        "listingTitle": listing_title,
        "listingType": listing_type_from_title(title),
        "city": city,
        "state": state,
        "neighborhood": neighborhood,
        "capacity": int_match(text, [r"([0-9]+)\s+guests?"]),
        "maxGuests": int_match(text, [r"([0-9]+)\s+guests?"]),
        "bedrooms": int_match(text, [r"([0-9]+)\s+bedrooms?"]),
        "bed": int_match(text, [r"([0-9]+)\s+beds?"]),
        "bath": first_match(text, [r"([0-9]+(?:\.[0-9]+)?)\s+baths?"]),
        "otherInfo": ". ".join(other_bits) or "Verified from Airbnb browser read.",
    }
    return {key: value for key, value in profile.items() if value not in (None, "")}


def run(args: argparse.Namespace) -> dict[str, Any]:
    emit(args, "started", "Starting Airbnb context probe", substage="probe_start")
    try:
        revnest_mcp_server.get_property_memory_impl(args.account_id, args.property_id)
    except Exception as exc:
        message = f"Property {args.property_id} was not found for account {args.account_id}"
        emit(args, "failed", message, substage="property_memory", tool="postgres/property-memory", error=str(exc))
        raise RuntimeError(message) from exc

    emit(args, "info", "Opening Airbnb listing in isolated browser session", substage="browser_open")
    opened = browser(args, "open", args.my_place, timeout=args.open_timeout)
    if opened.returncode != 0:
        raise RuntimeError(compact_error(opened.stdout))

    open_title, open_url = parse_open_output(opened.stdout)
    try:
        url_data = browser_json(args, "get", "url", "--json", timeout=8)
    except Exception as exc:
        emit(
            args,
            "info",
            "agent-browser get url timed out; using URL returned by open",
            substage="browser_url",
            metadata={"warning": str(exc)},
        )
        url_data = {"url": open_url}
    try:
        title_data = browser_json(args, "get", "title", "--json", timeout=8)
    except Exception as exc:
        emit(
            args,
            "info",
            "agent-browser get title timed out; using title returned by open",
            substage="browser_title",
            metadata={"warning": str(exc)},
        )
        title_data = {"title": open_title}
    url = str(url_data.get("url") or open_url or args.my_place)
    title = str(title_data.get("title") or open_title or "")

    expected_room_id = room_id_from_url(args.my_place)
    actual_room_id = room_id_from_url(url)
    if expected_room_id and actual_room_id and expected_room_id != actual_room_id:
        raise RuntimeError(f"Airbnb redirected to room {actual_room_id}, expected {expected_room_id}")

    snapshot_data = browser_json(args, "snapshot", "--json", timeout=args.snapshot_timeout)
    snapshot_text = str(snapshot_data.get("snapshot") or "")
    if "Translation on" in snapshot_text and close_translation_dialog(args, snapshot_data):
        browser(args, "wait", "--load", "networkidle", timeout=args.wait_timeout)
        snapshot_data = browser_json(args, "snapshot", "--json", timeout=args.snapshot_timeout)
        snapshot_text = str(snapshot_data.get("snapshot") or "")
    visible_text = ""
    text_result = browser(args, "get", "text", "body", timeout=8)
    if text_result.returncode == 0:
        visible_text = text_result.stdout

    profile = extract_profile(url, title, f"{snapshot_text}\n{visible_text}")
    if not profile.get("listingTitle") or not profile.get("city"):
        raise RuntimeError("Airbnb context probe could not verify listing title and city")

    emit(
        args,
        "info",
        f"Verified Airbnb listing {profile.get('listingTitle')} in {profile.get('city')}, {profile.get('state')}",
        substage="browser_extract",
        metadata={"profile": profile},
    )
    upsert = revnest_mcp_server.upsert_airbnb_property_profile_impl(args.account_id, args.property_id, profile)
    emit(
        args,
        "completed",
        f"Context completed for {profile.get('listingTitle')} in {profile.get('city')}, {profile.get('state')}",
        substage="profile_upsert",
        tool="upsert_airbnb_property_profile",
        metadata={"profile": profile, "upsertStatus": upsert.get("status")},
    )
    return {"status": "completed", "profile": profile, "property": upsert.get("property")}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Bounded Airbnb context probe for RevNest live runs")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--account-id", required=True)
    parser.add_argument("--property-id", required=True)
    parser.add_argument("--my-place", required=True)
    parser.add_argument("--log-path", required=True)
    parser.add_argument("--open-timeout", type=int, default=35)
    parser.add_argument("--wait-timeout", type=int, default=15)
    parser.add_argument("--snapshot-timeout", type=int, default=20)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    try:
        print(json.dumps(run(args), ensure_ascii=False, indent=2, sort_keys=True))
    except Exception as exc:
        emit(args, "failed", "Airbnb context probe failed", substage="probe_failed", error=str(exc))
        print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False, indent=2, sort_keys=True))
        raise SystemExit(2)


if __name__ == "__main__":
    main()
