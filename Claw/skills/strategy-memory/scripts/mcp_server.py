from __future__ import annotations

import json
import sys
import traceback
from typing import Any

from strategy_memory import search_strategy_memory


TOOL_SCHEMA = {
    "name": "search_strategy_memory",
    "description": "Search local RevNest strategy memory indexed with sentence-transformers and pgvector.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "The user query to search for."},
            "top_k": {"type": "integer", "description": "Maximum chunks to return.", "default": 8},
        },
        "required": ["query"],
    },
}


def send(payload: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def result_response(request_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def error_response(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def handle(request: dict[str, Any]) -> dict[str, Any] | None:
    method = request.get("method")
    request_id = request.get("id")
    params = request.get("params") or {}

    if method == "initialize":
        return result_response(
            request_id,
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "strategy-memory", "version": "0.1.0"},
            },
        )
    if method == "notifications/initialized":
        return None
    if method == "tools/list":
        return result_response(request_id, {"tools": [TOOL_SCHEMA]})
    if method == "tools/call":
        name = params.get("name")
        arguments = params.get("arguments") or {}
        if name != "search_strategy_memory":
            return error_response(request_id, -32601, f"Unknown tool: {name}")
        query = str(arguments.get("query") or "").strip()
        if not query:
            return error_response(request_id, -32602, "query is required")
        top_k = int(arguments.get("top_k") or 8)
        payload = search_strategy_memory(query, top_k)
        return result_response(
            request_id,
            {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(payload, ensure_ascii=False, indent=2),
                    }
                ],
                "isError": False,
            },
        )
    if request_id is None:
        return None
    return error_response(request_id, -32601, f"Unknown method: {method}")


def main() -> None:
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            request = json.loads(line)
            response = handle(request)
        except Exception as exc:
            traceback.print_exc(file=sys.stderr)
            request_id = None
            if "request" in locals() and isinstance(request, dict):
                request_id = request.get("id")
            response = error_response(request_id, -32000, str(exc))
        if response is not None:
            send(response)


if __name__ == "__main__":
    main()
