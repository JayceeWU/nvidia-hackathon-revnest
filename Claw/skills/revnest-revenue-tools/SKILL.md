---
name: revnest-revenue-tools
description: Local RevNest MCP server exposing structured revenue-management tools for property memory, progress logs, guardrail review, market-data fan-out, RevPAR, and price publishing.
---

# RevNest Revenue Tools MCP

Use this local MCP server when OpenClaw needs structured access to RevNest
pricing operations. Prefer these tools over shelling out when the server is
available; keep the existing Python CLIs as fallback commands.

## Tools

- `list_hotel_room_types`: load all hotel room-type properties for one account
  and validate that they share one market.
- `get_property_memory`: read trusted property memory from PostgreSQL.
- `log_progress` / `clear_progress`: write WebApp-compatible JSONL progress.
- `upsert_reasoning_step`: persist one compact pricing reasoning summary to
  PostgreSQL `pricing_record` with `record_type='reasoning_step'`.
- `review_guardrails`: run deterministic min/max guardrail plausibility checks.
- `collect_market_data_bundle`: run the shared market-data fan-out/fan-in bundle
  with typed arguments.
- `estimate_revpar`: estimate RevPAR without writing to PostgreSQL.
- `publish_price_calendar`: write `property_price` and optionally
  `revy_conversation`. This tool rejects calendars unless every row has final
  strategy-RAG validation with `strategy_validation_status=supported|corrected`.
- `review_hotel_price_adjustments`: compare hotel forecast calendars with
  MockHotel live rates, create material pending approval tasks, and send one
  best-effort Discord summary. This tool also rejects unvalidated strategy
  calendars before creating pending tasks.
- `upsert_airbnb_property_profile`: persist verified Airbnb context fields after
  browser verification.

## Privacy

The server reads database credentials from environment variables and never
returns them. Tool outputs are sanitized to omit account emails, password hashes,
API keys, guest/booking identifiers, and private profit or margin fields.
External market APIs still receive only public market context.
