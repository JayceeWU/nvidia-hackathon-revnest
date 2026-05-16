---
name: pricing-market-data
description: Coordinate RevNest market-data fan-out and fan-in for pricing runs, delegating weather, holidays, events, competitor, and tourism-demand collection to focused sub-skills.
---

# Pricing Market Data

Use this skill after context and guardrail review are complete.

## Fan-Out

When `revnest-revenue-tools` MCP is available, call
`collect_market_data_bundle` with the same structured fields instead of asking
the agent to assemble a shell command. Use `tools/run_parallel_market_data.py`
only as the fallback/debug path.

Run local signal collection through the helper whenever a location and date
range are known:

```bash
python3 tools/run_parallel_market_data.py   --run-id "<run_id>"   --account-id "<account_id>"   --property-id "<property_id>"   --property-type "<airbnb|hotel>"   --address "<verified location or hotel market>"   --start-date "<YYYY-MM-DD>"   --pricing-horizon "<pricing_horizon>"   --capacity "<guest capacity>"   --bedrooms "<bedroom count>"   --bathrooms "<bathroom count>"   --stdout-mode summary
```

This helper owns local Python/API stages for `pricing-weather`,
`pricing-holidays`, `pricing-events`, `pricing-competitors`, and
`pricing-tourism-demand`. After each source finishes, it writes a concise
human-readable source summary to PostgreSQL `market_data_summary` with
`account_id`, `property_id`, `start_date`, and `end_date`. For
`property_type=hotel`, after fan-in it must also upsert the WebApp hotel home
page market-signal payload to PostgreSQL `hotel_home_dashboard` with
`id='home'`, including `demandSignals.weather`, `demandSignals.events`,
`demandSignals.competitor`, and `demandSignals.occupancy` when those facts are
available. It also writes `runs/<run_id>-market-data.json` as the combined file
backup. Keep `--stdout-mode summary` for agent runs so the model receives a
compact handoff instead of the full source payload. Use `--stdout-mode full`
only for manual debugging.

MoodTrip is MCP-hosted and is not launched by the helper. Invoke
`pricing-competitors` for MoodTrip hotel comps as a parallel MCP task when the
runtime supports it, or immediately after the helper.

## Fan-In

Use the combined JSON, the persisted `market_data_summary` rows, and for hotel
runs the persisted `hotel_home_dashboard` payload as market-data evidence for
`pricing-decision-reasoning`. Keep failed/skipped sources in the evidence list;
do not silently drop them.
