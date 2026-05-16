#!/usr/bin/env python3
"""
RevNest Tavily search tool.

Provides:
- General Tavily web search
- Pricing-context follow-up search for tourism demand and seasonality

The API key is read from TAVILY_API_KEY, Tavily_API_KEY, or --api-key.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path


TAVILY_SEARCH_URL = "https://api.tavily.com/search"
ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / ".env"
US_STATE_CODES = {
    "al", "ak", "az", "ar", "ca", "co", "ct", "de", "fl", "ga", "hi", "ia",
    "id", "il", "in", "ks", "ky", "la", "ma", "md", "me", "mi", "mn", "mo",
    "ms", "mt", "nc", "nd", "ne", "nh", "nj", "nm", "nv", "ny", "oh", "ok",
    "or", "pa", "ri", "sc", "sd", "tn", "tx", "ut", "va", "vt", "wa", "wi",
    "wv", "wy", "dc",
}
US_STATE_NAMES = {
    "alabama", "alaska", "arizona", "arkansas", "california", "colorado",
    "connecticut", "delaware", "district of columbia", "florida", "georgia",
    "hawaii", "idaho", "illinois", "indiana", "iowa", "kansas", "kentucky",
    "louisiana", "maine", "maryland", "massachusetts", "michigan", "minnesota",
    "mississippi", "missouri", "montana", "nebraska", "nevada", "new hampshire",
    "new jersey", "new mexico", "new york", "north carolina", "north dakota",
    "ohio", "oklahoma", "oregon", "pennsylvania", "rhode island",
    "south carolina", "south dakota", "tennessee", "texas", "utah", "vermont",
    "virginia", "washington", "west virginia", "wisconsin", "wyoming",
}


def emit(payload: dict, exit_code: int = 0) -> None:
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    raise SystemExit(exit_code)


def load_local_env(path: Path = ENV_PATH) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def api_key_from(args: argparse.Namespace) -> str | None:
    load_local_env()
    return args.api_key or os.getenv("TAVILY_API_KEY") or os.getenv("Tavily_API_KEY")


def parse_iso_date(value: str, field_name: str) -> dt.date:
    try:
        return dt.date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} must use YYYY-MM-DD format") from exc


def city_query(address: str) -> str:
    parts = [part.strip() for part in address.split(",") if part.strip()]
    if not parts:
        return address.strip()
    city = re.sub(r"^\d+\s+", "", parts[0]).strip()
    if len(parts) >= 2:
        return f"{city}, {parts[1].strip()}"
    return city


def pricing_market_query(address: str) -> str:
    city = city_query(address)
    parts = [part.strip() for part in city.split(",") if part.strip()]
    text = city.lower()
    if "united states" in text or text.endswith(", us") or text.endswith(", usa"):
        return city
    if len(parts) >= 2 and parts[1].lower() in US_STATE_CODES | US_STATE_NAMES:
        return f"{city}, United States"
    return city


def is_us_address(address: str) -> bool:
    parts = [part.strip().lower().replace(".", "") for part in address.split(",") if part.strip()]
    if any(part in {"us", "usa", "united states", "united states of america"} for part in parts):
        return True
    return any(part in US_STATE_CODES or part in US_STATE_NAMES for part in parts)


def month_label(start: dt.date, end: dt.date | None = None) -> str:
    if end and (start.year, start.month) != (end.year, end.month):
        return f"{start.strftime('%B %Y')} to {end.strftime('%B %Y')}"
    return start.strftime("%B %Y")


def split_values(values: list[str] | None) -> list[str]:
    if not values:
        return []
    output: list[str] = []
    for value in values:
        output.extend(part.strip() for part in value.split(",") if part.strip())
    return output


def select_value(value: str) -> bool | str:
    if value == "false":
        return False
    if value == "true":
        return True
    return value


def http_post_json(payload: dict, api_key: str, timeout: int = 30) -> dict:
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        TAVILY_SEARCH_URL,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "RevNest-Tavily-Agent/0.1",
        },
    )
    context = ssl.create_default_context()
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body_text = exc.read().decode("utf-8", errors="replace")
        try:
            data = json.loads(body_text)
        except json.JSONDecodeError:
            data = {"error": body_text or str(exc)}
        if "error" not in data:
            data["error"] = str(exc)
        data["http_status"] = exc.code
        data["response_body"] = body_text[:2000]
        data["request_payload"] = payload
        return data


def build_search_payload(args: argparse.Namespace, query: str) -> dict:
    payload = {
        "query": query,
        "search_depth": args.search_depth,
        "topic": args.topic,
        "max_results": args.max_results,
        "include_answer": select_value(args.include_answer),
        "include_raw_content": select_value(args.include_raw_content),
        "include_images": args.include_images,
        "auto_parameters": args.auto_parameters,
    }

    if args.time_range:
        payload["time_range"] = args.time_range
    if args.start_date:
        payload["start_date"] = args.start_date
    if args.end_date:
        payload["end_date"] = args.end_date
    if args.country and args.topic == "general":
        payload["country"] = args.country
    if args.days is not None and args.topic == "news":
        payload["days"] = args.days
    if args.chunks_per_source is not None and args.search_depth == "advanced":
        payload["chunks_per_source"] = args.chunks_per_source

    include_domains = split_values(args.include_domain)
    exclude_domains = split_values(args.exclude_domain)
    if include_domains:
        payload["include_domains"] = include_domains
    if exclude_domains:
        payload["exclude_domains"] = exclude_domains

    return {key: value for key, value in payload.items() if value not in (None, [], "")}


def minimal_search_payload(query: str, max_results: int) -> dict:
    return {
        "query": query,
        "search_depth": "basic",
        "topic": "general",
        "max_results": max_results,
        "include_answer": False,
        "include_raw_content": False,
    }


def error_result(query: str, data: dict, payload: dict, retry_payload: dict | None = None) -> dict:
    diagnostics = {
        "request_payload": data.get("request_payload") or payload,
        "response_body": data.get("response_body"),
        "request_id": data.get("request_id"),
    }
    if retry_payload:
        diagnostics["retry_payload"] = retry_payload
    return {
        "query": query,
        "error": data.get("error", "Tavily request failed"),
        "http_status": data.get("http_status"),
        "results": [],
        "summary": summarize_results([]),
        "diagnostics": {key: value for key, value in diagnostics.items() if value not in (None, [], "")},
    }


def normalize_result(result: dict) -> dict:
    return {
        "title": result.get("title"),
        "url": result.get("url"),
        "content": result.get("content"),
        "score": result.get("score"),
        "published_date": result.get("published_date"),
        "raw_content": result.get("raw_content"),
    }


def summarize_results(results: list[dict]) -> dict:
    domains = Counter()
    for result in results:
        url = result.get("url")
        if url:
            domains[urllib.parse.urlparse(url).netloc] += 1
    return {
        "result_count": len(results),
        "top_domains": dict(domains.most_common(5)),
        "pricing_note": (
            "Use Tavily results to resolve demand and seasonality assumptions. Treat them as context, "
            "then combine with weather, holidays, events, and competitor rates before changing ADR."
        ),
    }


def tavily_search(args: argparse.Namespace, api_key: str, query: str) -> dict:
    payload = build_search_payload(args, query)
    data = http_post_json(payload, api_key, timeout=args.timeout)
    if data.get("error"):
        if data.get("http_status") == 400:
            retry_payload = minimal_search_payload(query, args.max_results)
            retry_data = http_post_json(retry_payload, api_key, timeout=args.timeout)
            if not retry_data.get("error"):
                results = [normalize_result(item) for item in retry_data.get("results", [])]
                return {
                    "query": query,
                    "answer": retry_data.get("answer"),
                    "results": results,
                    "summary": summarize_results(results),
                    "usage": retry_data.get("usage"),
                    "request_id": retry_data.get("request_id"),
                    "auto_parameters": retry_data.get("auto_parameters"),
                    "response_time": retry_data.get("response_time"),
                    "retry": {
                        "reason": "initial Tavily request returned HTTP 400",
                        "initial_payload": payload,
                        "retry_payload": retry_payload,
                    },
                }
            retry_data["initial_error"] = data.get("error")
            retry_data["initial_response_body"] = data.get("response_body")
            retry_data["initial_request_payload"] = payload
            return error_result(query, retry_data, payload, retry_payload=retry_payload)
        return error_result(query, data, payload)

    results = [normalize_result(item) for item in data.get("results", [])]
    return {
        "query": query,
        "answer": data.get("answer"),
        "results": results,
        "summary": summarize_results(results),
        "usage": data.get("usage"),
        "request_id": data.get("request_id"),
        "auto_parameters": data.get("auto_parameters"),
        "response_time": data.get("response_time"),
    }


def pricing_queries(address: str, start: dt.date, end: dt.date, extra_questions: list[str] | None) -> list[str]:
    market = pricing_market_query(address)
    month = month_label(start, end)
    date_range = f"{start.isoformat()} to {end.isoformat()}"
    queries = [
        f"{market} local tourism demand {month} hotels vacation rentals",
        f"{market} tourism seasonality {month} lodging demand",
        f"{market} {date_range} local events hotel vacation rental demand",
        f"{market} visitor bureau tourism lodging demand {month}",
        f"{market} hotel occupancy {month} demand trend",
        f"{market} vacation rental market supply demand {month}",
    ]
    if extra_questions:
        queries.extend(question.strip() for question in extra_questions if question.strip())
    return queries


def add_common_search_args(parser: argparse.ArgumentParser, include_date_filters: bool = True) -> None:
    parser.add_argument("--api-key")
    parser.add_argument("--search-depth", choices=["basic", "advanced", "fast", "ultra-fast"], default="basic")
    parser.add_argument("--topic", choices=["general", "news", "finance"], default="general")
    parser.add_argument("--max-results", type=int, default=5)
    parser.add_argument("--include-answer", choices=["false", "true", "basic", "advanced"], default="basic")
    parser.add_argument("--include-raw-content", choices=["false", "true", "markdown", "text"], default="false")
    parser.add_argument("--include-images", action="store_true")
    parser.add_argument("--time-range", choices=["day", "week", "month", "year", "d", "w", "m", "y"])
    if include_date_filters:
        parser.add_argument("--start-date")
        parser.add_argument("--end-date")
    parser.add_argument("--country")
    parser.add_argument("--days", type=int, help="Recent-day window for news searches")
    parser.add_argument("--chunks-per-source", type=int)
    parser.add_argument("--include-domain", action="append", help="Domain allow-list; repeat or comma-separate")
    parser.add_argument("--exclude-domain", action="append", help="Domain block-list; repeat or comma-separate")
    parser.add_argument("--auto-parameters", action="store_true")
    parser.add_argument("--timeout", type=int, default=30)


def cmd_search(args: argparse.Namespace) -> None:
    try:
        api_key = api_key_from(args)
        if not api_key:
            emit({"source": "tavily", "tool": "search", "error": "Missing TAVILY_API_KEY."}, exit_code=2)
        result = tavily_search(args, api_key, args.query)
        if result.get("error"):
            emit({"source": "tavily", "tool": "search", **result}, exit_code=1)
        emit({"source": "tavily", "tool": "search", **result})
    except Exception as exc:
        emit({"source": "tavily", "tool": "search", "error": str(exc)}, exit_code=1)


def cmd_pricing_context(args: argparse.Namespace) -> None:
    try:
        api_key = api_key_from(args)
        if not api_key:
            emit({"source": "tavily", "tool": "pricing-context", "error": "Missing TAVILY_API_KEY."}, exit_code=2)

        start = parse_iso_date(args.start_date, "start_date")
        end = parse_iso_date(args.end_date, "end_date")
        if end < start:
            emit({"source": "tavily", "tool": "pricing-context", "error": "end_date must be on or after start_date"}, exit_code=2)

        if not args.country and is_us_address(args.address):
            args.country = "united states"

        query_list = pricing_queries(args.address, start, end, args.question)
        if args.query_count is not None:
            if args.query_count < 1:
                emit({"source": "tavily", "tool": "pricing-context", "error": "query_count must be at least 1"}, exit_code=2)
            query_list = query_list[: args.query_count]

        searches = [tavily_search(args, api_key, query) for query in query_list]
        error_count = sum(1 for item in searches if item.get("error"))
        emit(
            {
                "source": "tavily",
                "tool": "pricing-context",
                "query": {
                    "address": args.address,
                    "start_date": start.isoformat(),
                    "end_date": end.isoformat(),
                    "query_count": len(query_list),
                },
                "summary": {
                    "search_count": len(searches),
                    "error_count": error_count,
                    "pricing_note": (
                        "Use these follow-up answers to refine demand level, seasonality, and confidence. "
                        "Do not price from Tavily alone; reconcile with event, holiday, weather, and comp-rate signals. "
                        "Use only demand evidence tied directly to the destination market; ignore unrelated source-market "
                        "or country-level travel reports unless they explicitly affect local lodging demand."
                    ),
                },
                "searches": searches,
            },
            exit_code=1 if error_count == len(searches) else 0,
        )
    except Exception as exc:
        emit({"source": "tavily", "tool": "pricing-context", "error": str(exc)}, exit_code=1)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="RevNest Tavily web search and pricing context tool")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("search", help="Run one Tavily web search")
    p.add_argument("--query", required=True)
    add_common_search_args(p)
    p.set_defaults(func=cmd_search)

    p = sub.add_parser("pricing-context", help="Run Tavily follow-up searches for local pricing demand context")
    p.add_argument("--address", required=True)
    p.add_argument("--start-date", required=True)
    p.add_argument("--end-date", required=True)
    p.add_argument("--query-count", type=int, default=4, help="Number of generated pricing queries to run")
    p.add_argument("--question", action="append", help="Extra follow-up question; repeat for multiple questions")
    add_common_search_args(p, include_date_filters=False)
    p.set_defaults(func=cmd_pricing_context)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
