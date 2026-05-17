# RevNest Tools

These tools are prepared for OpenClaw/Nemotron tool calling. They are Python standard-library only to avoid ARM compatibility issues on ASUS Ascent GX10 / DGX Spark.

Run from the repo root:

```bash
python3 Claw/tools/weather_tool.py --help
python3 Claw/tools/get_holiday.py --help
python3 Claw/tools/ticketmaster.py --help
python3 Claw/tools/serpapi.py --help
python3 Claw/tools/tavily.py --help
python3 Claw/tools/guardrail_review.py --help
python3 Claw/tools/revpar_estimate.py --help
python3 Claw/tools/progress_logger.py --help
python3 Claw/tools/reasoning_step_logger.py --help
python3 Claw/tools/nemotron_reasoning.py --help
python3 Claw/tools/run_parallel_market_data.py --help
python3 Claw/tools/run_pricing_agent.py --help
python3 Claw/tests/run_strategy_rag_gate_tests.py
```

If your shell is already in `Claw`, drop the `Claw/` prefix and use
`python3 tools/<name>.py`.

API-backed tools load `Claw/.env` automatically. Do not paste API keys into
prompts. Keep keys in `.env`, the shell environment, or pass them explicitly
with the tool's `--api-key` option.

## Commands

```bash
python3 Claw/tools/weather_tool.py weather --location "Santa Cruz, CA" --days 7
python3 Claw/tools/weather_tool.py weather --latitude 36.9741 --longitude -122.0308 --days 7
python3 Claw/tools/weather_tool.py weather-demand --zip-code 95060 --start-date 2026-05-12 --end-date 2026-05-18
python3 Claw/tools/get_holiday.py calendar --address "Santa Cruz, CA, US" --start-date 2026-05-12 --end-date 2026-05-18
python3 Claw/tools/ticketmaster.py events --address "Santa Cruz, CA, US" --start-date 2026-05-12 --end-date 2026-05-18
python3 Claw/tools/serpapi.py events --address "Santa Cruz, CA, US" --start-date 2026-05-12 --end-date 2026-05-18 --htichips date:week
python3 Claw/tools/serpapi.py hotels --address "Santa Cruz, CA, US" --check-in-date 2026-05-12 --check-out-date 2026-05-13 --adults 2 --search-mode hotels
python3 Claw/tools/serpapi.py hotels --address "Santa Cruz, CA, US" --check-in-date 2026-05-12 --pricing-horizon 3 --adults 2 --search-mode both
python3 Claw/tools/serpapi.py hotels --address "Santa Cruz, CA, US" --check-in-date 2026-05-12 --check-out-date 2026-05-13 --adults 2 --search-mode both
python3 Claw/tools/tavily.py search --query "why people travel to Palo Alto in May"
python3 Claw/tools/tavily.py pricing-context --address "Palo Alto, CA, US" --start-date 2026-05-12 --end-date 2026-05-18 --query-count 4
python3 Claw/tools/run_parallel_market_data.py --run-id demo --account-id "00000000-0000-0000-0000-000000000102" --property-id airbnb-1163080444550698185 --property-type airbnb --address "Santa Cruz, CA, US" --start-date 2026-05-12 --pricing-horizon 2 --capacity 4 --bedrooms 1 --bathrooms 1
python3 Claw/tools/guardrail_review.py --min-price 80 --max-price 260 --capacity 7 --bedrooms 3 --beds 4 --bathrooms 2.5 --property-type "entire home" --market "Santa Cruz, CA"
python3 Claw/tools/revpar_estimate.py estimate --property-id coastal-suite --price-calendar-json '[{"date":"2026-05-12","current_price":180,"final_price_after_guardrails":195}]' --rooms 1 --occupancy-rate 0.84
python3 Claw/tools/revpar_estimate.py write-prices --property-id coastal-suite --price-calendar-json '[{"date":"2026-05-12","current_price":180,"final_price_after_guardrails":195}]' --rooms 1 --occupancy-rate 0.84
python3 Claw/tools/revpar_estimate.py write-prices --property-id airbnb-1163080444550698185 --property-name "Two-Six Beach House - newly renovated!" --location "Santa Cruz, CA" --price-calendar-json '[{"date":"2026-05-13","current_price":800,"final_price_after_guardrails":900}]' --rooms 1 --occupancy-rate 0.70
python3 Claw/tools/revpar_estimate.py write-prices --account-id "00000000-0000-0000-0000-000000000102" --property-id airbnb-1163080444550698185 --price-calendar-json '[{"date":"2026-05-13","current_price":800,"final_price_after_guardrails":900}]' --rooms 1 --occupancy-rate 0.70 --run-id demo --conversation-id revy-demo --trace-log-path runs/demo.log --conversation-title "Santa Cruz pricing summary" --conversation-summary "Revy saved the guarded pricing recommendation." --final-message "Revy recommends USD 900/night because demand is elevated and the price remains inside guardrails."
python3 Claw/tools/progress_logger.py clear
python3 Claw/tools/progress_logger.py log --run-id demo --workflow pricing-workflow --skill pricing-workflow --called-skill pricing-context --stage context --status started --message "Starting pricing workflow run" --tool agent-browser
python3 Claw/tools/progress_logger.py log --run-id demo --workflow pricing-workflow --skill pricing-workflow --called-skill pricing-decision-reasoning --stage pricing_decision --substage guardrail_check --status info --message "Guardrail review completed" --tool pricing-decision-reasoning --metadata-json '{"guardrail_review_needed":true}'
python3 Claw/tools/reasoning_step_logger.py --account-id "00000000-0000-0000-0000-000000000102" --run-id demo --property-id airbnb-1163080444550698185 --substage occupancy_result --summary "Estimated occupancy is 78% from event demand and tight supply." --metrics-json '{"estimated_occupancy":0.78,"supply_index":0.72,"demand_index":0.76}' --tool occupancy_rate_estimator.py --confidence medium --dry-run
```

For web progress streaming, prefer the runner so the log receives a lifecycle
event before the model starts and another event if the model exits or times out:

```bash
cd /home/ubuntu/RevNest/Claw
python3 tools/run_pricing_agent.py \
  --session-id pricing-workflow-01 \
  --thinking medium \
  --verbose on \
  --timeout-seconds 1200 \
  --account-id "00000000-0000-0000-0000-000000000102" \
  --property-type airbnb \
  --my-place "https://www.airbnb.com/rooms/1163080444550698185?check_in=2026-05-12&check_out=2026-05-14&guests=1&adults=1" \
  --min-price 80 \
  --max-price 260 \
  --pricing-horizon 2
```

The runner appends by default so an accidental nested run does not erase earlier
stage events. For a fresh file, clear manually with `progress_logger.py clear` or
pass `--clear-log`.

## Data Source

- `weather_tool.py` uses Open-Meteo weather and geocoding APIs. `weather` falls back to deterministic simulated weather if the network/API is unavailable.
- `get_holiday.py` uses Nager.Date API `PublicHolidays/{year}/{countryCode}`. It groups rows by `types`: `Public`, `School`, and other holiday/observance types.
- `ticketmaster.py` uses Ticketmaster Discovery API v2. Set `TICKETMASTER_API_KEY` in `.env`, or pass `--api-key`.
- `serpapi.py` uses SerpApi Google Events and Google Hotels engines. Set `SERPAPI_API_KEY` or `SerpApi_API_KEY` in `.env`, or pass `--api-key`. `--search-mode hotels` is the default for hotel comps; use `--search-mode vacation-rentals` for rental-style Google results, or `--search-mode both` to retrieve both hotel and vacation-rental result sets.
- `tavily.py` uses Tavily Search API for demand and seasonality follow-up research. Set `TAVILY_API_KEY` or `Tavily_API_KEY` in `.env`, or pass `--api-key`.
- `guardrail_review.py` checks whether host min/max guardrails look plausible for listing size and warns when a large listing is likely capped too low.
- `revpar_estimate.py` estimates RevPAR from a price calendar and can upsert predicted prices into PostgreSQL `property_price`. When `write-prices` receives `--final-message`, it also saves the final pricing explanation to `revy_conversation`. Agent workflows should pass the calendar inline with `--price-calendar-json` instead of creating `price_calendar*.json` files in the workspace. Set `CLAW_DATABASE_URL` for `Claw/data`, or pass `--database-url`. `write-prices` auto-registers a missing `property` row by default, tries local `psql` first, then falls back to the `data/docker-compose.yml` Postgres service.
- RevPAR tool summaries and daily outputs are USD dollars. PostgreSQL columns
  ending in `_cents` are internal storage details only. `write-prices --dry-run`
  hides raw SQL by default; add `--include-sql` only when debugging SQL.
- `progress_logger.py` appends workflow status events to `runs/airbnb-pricing-progress.log` as JSONL for web apps or `tail -f`.
- Progress events support `workflow`, `skill`, `called_skill`, `caller_skill`, and exact `tool` fields so the UI can distinguish the pricing workflow from concrete Python tools and sub-skills.
- `reasoning_step_logger.py` upserts durable compact pricing-decision summaries
  into PostgreSQL `pricing_record` as `record_type='reasoning_step'`. It is for
  user-facing summaries and metrics, not hidden chain-of-thought.
- `nemotron_reasoning.py` is the only supported CLI path for model-authored
  pricing-decision substage reasoning. Qwen/OpenClaw should call this tool and
  use its JSON output instead of writing pricing reasoning directly.
- `run_parallel_market_data.py` is the pricing-workflow fan-out/fan-in helper. After context is verified, it starts weather, holidays, Ticketmaster, SerpApi events, SerpApi hotel/vacation-rental comps, and Tavily concurrently, writes child progress events, upserts one `market_data_summary` row per source with account/property/date context, upserts `hotel_home_dashboard` for hotel runs, and saves combined results to `runs/<run_id>-market-data.json`. MoodTrip is MCP-hosted, so run it separately when available.
- `run_pricing_agent.py` wraps `openclaw agent` for the pricing workflow, loads `.env`, and writes progress start/finish events even when the model times out before making tool calls. The runner is named generically because it supports both Airbnb and hotel pricing workflows.
- When the runner falls back to NemoClaw, its local default sandbox is
  `my-assistant`. Override with `--nemoclaw-sandbox` or
  `REVNEST_NEMOCLAW_SANDBOX` if a different sandbox is active.

## Strategy-RAG Gate Tests

Run the anti-hallucination gate smoke tests before a demo:

```bash
python3 Claw/tests/run_strategy_rag_gate_tests.py
```

Expected result: all cases print `PASS`, including calculator rejection of
`unsupported` final strategy review and publisher `write-prices --dry-run`
rejection of missing strategy memory, `draft_unreviewed`, and `unsupported`.
The script does not write to PostgreSQL.

## Notes

Weather and holiday calendars are demand modifiers, not complete pricing decisions. Combine them with events, pickup pace, occupancy, and competitor rates in the broader pricing workflow.

For local price write-back, start the Claw PostgreSQL data package from `Claw/data`:

```bash
docker compose up -d
```
