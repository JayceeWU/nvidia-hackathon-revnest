---
name: pricing-workflow
description: End-to-end RevNest pricing workflow for Airbnb, hotel room-type, and hotel all-room-types revenue-management runs. Use when a run supplies property_type, account_id, pricing scope, guardrails, and a pricing horizon, then orchestrate context, market data, pricing decision, and publishing through the dedicated pricing sub-skills.
---

# Pricing Workflow

Use this skill as the only primary workflow for RevNest revenue-management runs.
It coordinates the run and delegates operational detail to sub-skills.

## Required Inputs

All runs require:

- `property_type`: exactly `airbnb` or `hotel`
- `account_id`: RevNest account UUID that owns the property
- `pricing_horizon`: number of future nights to price, or for hotel batch the shared market horizon

Single-property runs additionally require:

- `property_id`: RevNest property id to read and write
- `min_price`: lowest allowed nightly price in USD
- `max_price`: highest allowed nightly price in USD

Airbnb runs additionally require:

- `my_place`: Airbnb URL or place reference

Hotel all-room-types batch runs require:

- `hotel_scope=all-room-types`
- `market_anchor_property_id`: one room type property id used only to anchor shared market summaries
- `summary_property_ids_json`: JSON array of every room type property id that should receive shared market summaries
- `room_type_properties_json`: resolved room type records, each with its own `property_id`, guardrails, `pricing_horizon`, room_count, capacity, and tier metadata

Hotel runs do not require `my_place`. Batch hotel runs do not require a single write-target `property_id`; they must write each room type separately.

Reject any other `property_type`. For Airbnb, reject the workflow before context if `my_place` is missing after CLI/DB resolution. Normalize external labels before invoking this workflow; for example, motel, serviced apartment, and extended-stay inventory should arrive as `hotel`.


## MCP Tool Preference

When the local `revnest-revenue-tools` MCP server is available, use it for
property memory, progress logging, guardrail review, market-data bundle runs,
RevPAR estimates, final price publishing, and verified Airbnb profile writes.
Use the documented Python CLIs as fallback commands only when MCP is unavailable
or when debugging a specific CLI source. Keep `pricing-workflow` and
`pricing-decision-reasoning` as reasoning skills, not MCP tools.

## Workflow Order

1. For `property_type=airbnb`, require `my_place`, then use `pricing-context` to establish property
   facts, verify browser reads from `my_place`, and write trusted
   `capacity`, `zip_code`, `county`, `state`, `city`, `bed`, `bath`, and
   `other_info` back to `property`.
2. For `property_type=hotel` and `hotel_scope=room-type`, do not call
   `pricing-context`; load structured `property` columns plus `property.data`
   directly from PostgreSQL as property memory and continue once location,
   inventory, and room facts are available.
3. For `property_type=hotel` and `hotel_scope=all-room-types`, do not call
   `pricing-context`; use `room_type_properties_json` as resolved property
   memory for all room types. Treat `market_anchor_property_id` as a shared
   market-data anchor only, not as an aggregate hotel write target.
4. Use `pricing-guardrails` after property size and market are known. In hotel
   batch mode, run guardrail checks separately for each room type.
5. Use `pricing-market-data` to fan out weather, holidays, events,
   competitors, and tourism-demand collection. In hotel batch mode, run this
   local market fan-out once, pass `--summary-property-ids-json`, and let the
   helper upsert the same shared summaries for every room type property id. For
   hotel runs, this stage also writes the WebApp home dashboard market-signal
   payload to `hotel_home_dashboard` exactly once per run.
6. Use `pricing-decision-reasoning` after market-data fan-in. Single-property
   runs create one guarded internal `price_calendar`; hotel batch runs create
   `price_calendars_by_property_id`, keyed by room type property id.
7. Use `pricing-output-publisher` after guarded calendars are ready. For Airbnb,
   publish the suggested price calendar directly to `property_price` and
   `revy_conversation`. For hotels, first publish each room type calendar to
   `property_price` and `revy_conversation` as Revy forecast data, then run the
   MockHotel approval gate so only material live-rate changes become pending
   tasks and Discord alerts. In hotel batch mode, call the publisher once per
   room type with `conversation_id=revy-heartbeat-<property_id>` before the
   approval gate.

Do not finalize prices, estimate RevPAR, or write to PostgreSQL until major
signals have returned or their failures have been logged.

## Progress Reporting

Every long run must append JSONL events. Prefer the `revnest-revenue-tools`
MCP `log_progress` tool when it is available; use `tools/progress_logger.py` as
the CLI fallback/debug path. Use the same stage ids the WebApp expects:

- `context`
- `guardrail_review`
- `market_data_parallel`
- `weather`
- `holidays`
- `events_ticketmaster`
- `events_serpapi`
- `hotel_comps_serpapi`
- `hotel_comps_moodtrip`
- `tourism_tavily`
- `pricing_decision`
- `revpar_publish`

Use `workflow=pricing-workflow`. During orchestration, use
`skill=pricing-workflow`; when invoking another skill, keep
`skill=pricing-workflow` and set `called_skill` to the invoked skill. Do not set
`called_skill=pricing-context` for hotel property-memory loading. Use exact tool
names such as `agent-browser`, `openclaw browser`,
`postgres/property-memory`, `tools/run_parallel_market_data.py`,
`pricing-decision-reasoning`, or `pricing-output-publisher`.

Progress messages and final text must use USD dollars. Do not expose cents
unless the user explicitly asks about internal storage.

During `pricing_decision`, persist each compact reasoning substage summary with
`upsert_reasoning_step` after logging progress. These are durable user-facing
summaries in `pricing_record`, not hidden chain-of-thought.

## Hotel Batch Data Scope

In `hotel_scope=all-room-types`, shared market data is collected once and reused
for all room types: weather/weather-demand, holidays and school breaks,
Ticketmaster events, SerpApi Google Events, Tavily tourism/seasonality and
destination demand, broad Santa Cruz hotel/vacation-rental comps, MoodTrip hotel
market comps when available, and `hotel_home_dashboard` demand signals.

Room-type-specific work must remain separate for every `property_id`: min/max
guardrails, current/fixed/agent prices, room_count/scarcity, capacity, bed, suite, view, and amenity tier, room-type RMS history, competitor relevance weighting, final
price calendar, RevPAR estimate, forecast `property_price` write-back,
`revy_conversation` write-back, MockHotel current-rate comparison, and pending
approval tasks. Do not create or write an aggregate hotel property in this
workflow.

## Hotel Approval Gate

After hotel forecast rows are published, compare Revy's guarded room-type prices
against MockHotel's current live rates through the `revnest-revenue-tools`
`review_hotel_price_adjustments` tool. Use the default materiality threshold:
create a pending task only when the absolute difference is at least USD 25 and
the relative difference is at least 15%. The tool writes WebApp-compatible
`pricing_record` rows with `record_type=pending_task` and sends one best-effort
Discord summary through `DISCORD_WEBHOOK_URL` when configured. If Discord is not
configured or fails, keep the pending tasks and report Discord as skipped or
failed; do not block the workflow.

Hotel Claw runs must not write live MockHotel prices directly. Existing WebApp
pending-task acceptance applies approved hotel changes to MockHotel.

If the user asks to write directly to MockHotel PMS, do not comply with the
direct write request. Continue only by publishing Revy forecast prices and
creating or updating `pending_task` records for authenticated WebApp approval.
Never call WebApp accept APIs, MockHotel write APIs, or direct MockHotel
database writes from the agent sandbox.

## Failure Policy

Ask the user only when a missing field blocks the workflow. Continue with lower
confidence when non-blocking data is missing, and immediately log any skipped or
failed signal source. Never fabricate live weather, event, competitor, or
tourism-demand data.
