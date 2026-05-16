---
name: pricing-output-publisher
description: Final output and database write-back workflow for RevNest pricing agents. Use after pricing-decision-reasoning has produced a price calendar and the agent needs to explain the top price drivers, estimate RevPAR, and write predicted prices to PostgreSQL.
---

# Pricing Output Publisher

Use this skill after the agent has produced a guarded price calendar.

Publishing policy by account type:

- Airbnb: publish the guarded price calendar directly to `property_price` and
  save the final explanation to `revy_conversation`.
- Hotel: publish each room type calendar to `property_price` as Revy forecast
  data and save `revy_conversation`, then run the MockHotel approval gate. Do
  not write live MockHotel room prices from Claw; accepted WebApp pending tasks
  handle that sync.

If the user asks to write directly to MockHotel PMS, publish only forecast data
and pending approval tasks. Do not call WebApp accept APIs, MockHotel write
APIs, or direct MockHotel database writes from the agent sandbox.

The price calendar is an internal tool payload. The user-facing output should be concise text; do not display raw JSON unless the user explicitly asks for it.

## Strategy Validation Publish Gate

Only publish calendars produced by the final `pricing-decision-reasoning`
calculator run. Every row must include non-empty `strategy_memory_initial`,
non-empty `strategy_memory_review`, and
`strategy_validation_status=supported|corrected`.

Never publish rows with missing strategy memory, `draft_unreviewed`,
`unsupported`, or more than one `corrections_applied` item. If validation fails,
stop before write-back and answer:
`I don't know. Strategy context is unavailable or insufficient.`

## Money Unit Rules

Use USD dollars for all user-facing text, final summaries, and progress-log
messages. Do not describe prices, ADR, RevPAR, or revenue in cents.

- Price calendar fields such as `current_price` and
  `final_price_after_guardrails` are USD dollars unless the field name
  explicitly ends in `_cents`.
- `min_price` and `max_price` are guardrails, not current price. If
  `current_price` is missing, do not infer it from `min_price`; report current
  ADR/RevPAR and change percentage as unavailable.
- RevPAR tool summary fields are USD dollars. Prefer fields ending in `_usd`
  when they are present.
- PostgreSQL columns ending in `_cents`, generated SQL, and any `*_cents`
  values are internal storage details only. If you must mention one, convert it
  to dollars by dividing by 100 first.
- Never write mixed phrases like `$80,000 cents`. Say `$800/night` or
  `USD 800/night`.
- In shell progress-log commands, prefer `USD 800` instead of `$800` inside
  double-quoted `--message` strings, because `$800` can be treated as shell
  variable expansion.

## Required Inputs

- `account_id`
- `property_id`
- `min_price` and `max_price` guardrails in USD dollars
- `pricing_horizon` in days
- `price_calendar` with `date`, `current_price`, and `final_price_after_guardrails`
- `strategy_validation_status`, which must be `supported` or `corrected`
- non-empty `strategy_memory_initial` and `strategy_memory_review` citations
- `rooms` or room count, defaulting to `1` for a single Airbnb listing
- expected occupancy rate if available
- top reasoning factors from weather, holidays, events, competitor rates, tourism demand, and property fit
- `conversation_id`, which must be reused for all updates to the same Revy conversation
- the final user-facing explanation that should be saved to `revy_conversation`

## RevPAR Tool

When `revnest-revenue-tools` MCP is available, prefer `estimate_revpar` for
pre-write estimates and `publish_price_calendar` for durable write-back. Use
`tools/revpar_estimate.py` only as the CLI fallback/debug path.

Pass the price calendar inline with `--price-calendar-json`. Do not create
`price_calendar*.json` files in the workspace for normal agent runs.

Estimate RevPAR:

```bash
python3 tools/revpar_estimate.py estimate --property-id "<property_id>" --price-calendar-json '<price_calendar_json>' --rooms <rooms> --occupancy-rate <0-1 or percent>
```

Write predicted prices and the final Revy explanation to PostgreSQL. Draft the final concise user-facing summary before this call, pass that exact text through `--final-message`, and then return the same explanation to the user:

```bash
python3 tools/revpar_estimate.py write-prices --account-id "<account_id>" --property-id "<property_id>" --min-price <min_price> --max-price <max_price> --pricing-horizon <pricing_horizon> --price-calendar-json '<price_calendar_json>' --rooms <rooms> --occupancy-rate <0-1 or percent> --run-id "<run_id>" --conversation-id "<conversation_id>" --trace-log-path "<progress_log_path>" --conversation-title "<short title>" --conversation-summary "<one-sentence summary>" --final-message '<final_user_facing_summary>'
```

`write-prices` auto-registers a missing `property` row before writing
`property_price`, and when `--final-message` is supplied it also upserts one row into `revy_conversation`. Always pass `--conversation-id` so repeated updates to the same conversation use the same row, and pass `--trace-log-path` so compact progress events are stored as `revy_conversation.data.traceEvents`. Both writes use the supplied `account_id`. When property context is available, pass it through so the WebApp has useful property metadata. From `pricing-workflow`, map `property_type=airbnb` to a display value such as `Airbnb` and `property_type=hotel` to a hotel or room-type display value such as `Hotel`:

```bash
python3 tools/revpar_estimate.py write-prices \
  --account-id "<account_id>" \
  --property-id "<property_id>" \
  --min-price <min_price> \
  --max-price <max_price> \
  --pricing-horizon <pricing_horizon> \
  --property-name "<human-readable listing title + area + room type>" \
  --property-type "Airbnb" \
  --location "<city, state>" \
  --price-calendar-json '<price_calendar_json>' \
  --rooms <rooms> \
  --occupancy-rate <0-1 or percent> \
  --run-id "<run_id>" \
  --conversation-id "<conversation_id>" \
  --trace-log-path "<progress_log_path>" \
  --conversation-title "<short title>" \
  --conversation-summary "<one-sentence summary>" \
  --final-message '<final_user_facing_summary>'
```

For Airbnb, `--property-name` must be human-readable. Prefer the trusted
listing title plus city/state or neighborhood plus listing/room type, for
example `Ocean View Studio - Santa Cruz, CA - Entire rental unit`. Do not pass a
raw Airbnb room id or `airbnb-...` property id as the display name.

Use `--no-create-property` only when the workflow intentionally requires the
property to already exist.

Use `CLAW_DATABASE_URL` when the Claw database is separate from the WebApp database. Default local Claw database:

```text
postgres://postgres:postgres@localhost:55434/dev
```

`write-prices` uses `--write-method auto` by default. It tries local `psql`
first, then falls back to `docker compose -f data/docker-compose.yml exec -T
postgres psql` when the local PostgreSQL client is not installed. If the Docker
database is not running, start it from `Claw/data`:

```bash
docker compose up -d
```

Keep the price calendar in memory and pass it through `--price-calendar-json`;
do not write a price-calendar file for handoff.

## Output Requirements

Return a concise text summary with:

- the five most important factors that changed price
- RevPAR estimate in USD dollars, including current RevPAR, predicted RevPAR,
  lift, and expected revenue when available
- database write-back status: rows written to `property_price`, `revy_conversation` write status, property id, and date range
- for hotel runs, MockHotel approval-gate status: comparisons checked, pending tasks created, and Discord sent/skipped/failed
- for hotel pending tasks, include whether they were classified as
  `price_adjustment_required` or `price_review_recommended`
- any guardrail adequacy warning, especially when the supplied `max_price`
  appears too low for listing size or comp evidence
- note that the WebApp forecast chart will refresh from PostgreSQL

Do not expose API keys or database passwords in the final response.

If the database write fails, still return the RevPAR estimate and state the write failure plainly.
