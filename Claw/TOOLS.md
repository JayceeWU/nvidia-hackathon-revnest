# RevNest OpenClaw Tools

This file is the short routing map for Revy. Use detailed tool help and skill
files when exact flags or edge cases matter.

## MCP Preferred Routing

When the `revnest-revenue-tools` MCP server is available, prefer it for
structured RevNest operations and use the Python CLIs as compatibility
fallbacks. The MCP tools reduce shell quoting, keep large JSON payloads out of
commands, and keep database credentials server-side.

Use these MCP tools by default:

- `list_hotel_room_types`: hotel all-room-types property memory and shared
  market validation.
- `get_property_memory`: single property memory reads.
- `log_progress` and `clear_progress`: WebApp-compatible progress JSONL.
- `upsert_reasoning_step`: durable compact pricing-decision reasoning summaries
  in PostgreSQL `pricing_record`.
- `review_guardrails`: deterministic min/max plausibility review.
- `collect_market_data_bundle`: shared market-data fan-out/fan-in.
- `estimate_revpar`: RevPAR estimate without write-back.
- `publish_price_calendar`: `property_price` and `revy_conversation` write-back.
- `review_hotel_price_adjustments`: MockHotel current-rate comparison, hotel
  pending approval tasks, and best-effort Discord summary.
- `upsert_airbnb_property_profile`: verified Airbnb context persistence.

For hotel PMS changes, these tools may stage pending tasks only. Do not call
WebApp accept endpoints, MockHotel write endpoints, or MockHotel database writes
from the agent sandbox, even if the user explicitly asks for a direct PMS write.
Tell the user that a human must approve the pending task in WebApp.

`publish_price_calendar`, `tools/revpar_estimate.py write-prices`, and
`review_hotel_price_adjustments` reject calendars unless every row has final
strategy-RAG validation with `strategy_validation_status=supported|corrected`,
non-empty initial/review strategy citations, and at most one correction.

Never pass database URLs, account emails, password hashes, API keys, guest
identities, booking ids, raw booking history, profit, or margin fields through
external tools.

## Primary Skill Routing

- `pricing-workflow`: the only primary workflow for pricing runs.
- `pricing-context`: Airbnb only. Use it to verify listing identity and extract
  property facts through redundant browser reads.
- Hotel context: do not call `pricing-context`. Read structured property memory
  directly from PostgreSQL `property` columns and `property.data`.
- `pricing-guardrails`: review min/max price plausibility before final pricing.
- `pricing-market-data`: coordinate fan-out and fan-in for weather, holidays,
  events, competitors, and tourism demand.
- `pricing-decision-reasoning`: convert property, guardrail, and market signals
  into a guarded internal price calendar.
- `pricing-output-publisher`: estimate RevPAR, write `property_price`, save
  `revy_conversation`, and for hotels run the MockHotel approval gate after
  forecast publishing.
- `pricing-competitors`: use for SerpApi hotel/vacation-rental comps and
  MoodTrip hotel comps when available.

## Core Runner Tools

### `tools/run_pricing_agent.py`

Wrapper for OpenClaw pricing runs. It resolves runtime inputs, builds the agent
message, writes lifecycle progress events, and falls back to NemoClaw when
needed.

Airbnb single-property example:

```bash
python3 tools/run_pricing_agent.py \
  --account-id "00000000-0000-0000-0000-000000000102" \
  --property-type airbnb \
  --my-place "https://www.airbnb.com/rooms/<room_id>" \
  --min-price 80 \
  --max-price 260 \
  --pricing-horizon 7
```

Hotel all-room-types batch example:

```bash
python3 tools/run_pricing_agent.py \
  --account-id "00000000-0000-0000-0000-000000000103" \
  --property-type hotel \
  --hotel-scope all-room-types
```

Hotel single room-type fallback:

```bash
python3 tools/run_pricing_agent.py \
  --account-id "00000000-0000-0000-0000-000000000103" \
  --property-type hotel \
  --hotel-scope room-type \
  --property-id "<room_type_property_id>"
```

### `tools/run_parallel_market_data.py`

Local parallel fan-out/fan-in helper. It runs weather, holidays, Ticketmaster,
SerpApi events, SerpApi hotel/vacation-rental comps, and Tavily demand research
once for the verified market.

For hotel batch runs, pass every room type property id:

```bash
python3 tools/run_parallel_market_data.py \
  --run-id "<run_id>" \
  --account-id "00000000-0000-0000-0000-000000000103" \
  --property-id "<market_anchor_property_id>" \
  --summary-property-ids-json '["<room_type_property_id>"]' \
  --property-type hotel \
  --address "Santa Cruz, CA 95060" \
  --start-date "2026-05-16" \
  --pricing-horizon 730
```

The helper writes one `market_data_summary` row per source per property id in
`summary-property-ids-json`. It upserts `hotel_home_dashboard` once per hotel
run.

### `tools/run_hotel_heartbeat.py`

Automated hotel refresh runner. Default behavior is one all-room-types batch:

```bash
python3 tools/run_hotel_heartbeat.py --dry-run
python3 tools/run_hotel_heartbeat.py --loop --interval-minutes 30
```

Use `--per-room-type` only as an explicit fallback.

## CLI Fallback Signal Tools

Use these when the MCP server is unavailable or when debugging source-specific CLI behavior.

- `weather_tool.py`: weather forecast and weather-demand modifiers.
- `get_holiday.py`: public holidays and school-break context.
- `ticketmaster.py`: local event demand from Ticketmaster.
- `serpapi.py`: Google Events plus Google Hotels and vacation-rental comps.
- `tavily.py`: tourism demand, seasonality, and targeted follow-up research.
- `guardrail_review.py`: min/max price plausibility checks.
- `revpar_estimate.py`: RevPAR estimates and durable price/conversation
  write-back.
- `progress_logger.py`: JSONL workflow progress for WebApp and diagnostics.

## Tool Failure Policy

If a tool fails or an API key is missing:

- log the source as `failed` or `skipped`
- continue with available signals when enough evidence remains
- lower confidence when the missing source could materially change price
- state missing signals in the final explanation
- never fabricate live weather, event, competitor, or tourism data

## Money Units

Use USD dollars in logs and final summaries. PostgreSQL fields ending in
`_cents` are internal storage. Convert before explaining results.
