---
name: pricing-decision-reasoning
description: Detailed hospitality pricing decision workflow for Airbnb and hotel agents. Use when converting collected weather, holiday, event, competitor-rate, tourism-demand, and property signals into a nightly price calendar, especially when Tavily follow-up search is needed to resolve uncertain demand or seasonality assumptions.
---

# Pricing Decision Reasoning

Use this skill after the agent has collected property details, weather, holiday calendars, local events, competitor rates, and tourism-demand context.

The goal is not to average signals mechanically. The agent must explain why each signal matters for the specific property, date, and guest segment, then choose a price that follows the configured guardrails.

## Required Inputs

- Property profile: address or market, property type, bedroom count, occupancy, amenities, review quality, and current/base price.
- Date range: `start_date`, `pricing_horizon`, and existing prices when available.
- Guardrails: `min_price`, `max_price`, and any user-provided pricing constraints.
- Market signals: weather, holidays, local events, Google Events, Google Hotels, Google vacation-rental results, MoodTrip hotel comps, Ticketmaster, and tourism-demand research.

## One-Step-At-A-Time Rule

Pricing decisions are context-sensitive. Complete exactly one pricing-decision
substage at a time, write a compact reasoning summary, then move to the next
substage. Do not combine supply research, demand research, occupancy
estimation, and final pricing into one long narrative.

For every substage below:

1. Produce a short user-facing summary with facts, numbers, tool/source, and
   confidence.
2. Log the summary with `log_progress`.
3. Persist the same summary with `upsert_reasoning_step`.

Use compact summaries only. Do not persist hidden chain-of-thought.

## Required Supply-Demand Sub-Loop

Before running strategy-RAG or the pricing calculator, analyze supply and demand
in this order:

1. `supply_snapshot`: summarize available competitor inventory, comp count,
   hotel/vacation-rental substitute supply, sellout/compression language, and
   subject inventory scarcity.
2. `demand_snapshot`: summarize events, holidays, tourism/seasonality, weather,
   booking window, guest segment, and demand strength.
3. `supply_demand_synthesis`: reconcile supply vs demand into
   `low`, `normal`, `elevated`, or `compressed` demand and state the strongest
   3-5 drivers.
4. `occupancy_input`: build the JSON input for the occupancy estimator from
   property profile, supply signals, demand signals, competitor stats, events,
   holidays, weather/tourism, booking window, and historical/RMS occupancy when
   available.
5. `occupancy_python_run`: run the deterministic occupancy estimator:

```bash
python3 skills/pricing-decision-reasoning/scripts/occupancy_rate_estimator.py --input-json '<occupancy_input_json>'
```

6. `occupancy_result`: persist per-date `estimated_occupancy`,
   `supply_index`, `demand_index`, `compression_level`, confidence, top factors,
   and the formula code summary.

The occupancy estimator output is the required source for
`estimated_occupancy` in `pricing_decision_calculator.py`. Pass the full
estimator JSON as `occupancy_estimator` and pass its date-keyed
`estimated_occupancy` map as `estimated_occupancy`; the bundled pricing
calculator rejects inputs without this estimator provenance.

For hotel batch runs, perform market-level supply/demand once, then apply
room-type-specific inventory scarcity, room tier, guardrails, and RMS/current
price facts for each room type.

Use the collected market-data bundle first. If a material supply or demand
question is still unresolved, run one focused follow-up search for that
substage, persist its summary, and then continue. Do not start a second
follow-up until the current substage has been summarized and persisted.

## Required Strategy-RAG and Calculator Loop

The pricing decision must follow this closed loop. Do not publish prices from
free-form narrative reasoning alone.

1. Call `strategy-memory__search_strategy_memory(query, top_k=8)` before
   calculating prices.
   - For `property_type=hotel`, use this query exactly:
     `hotel Dream Inn revenue management pricing strategy RMS occupancy BAR room type compression`
   - For `property_type=airbnb`, use this query exactly:
     `Airbnb short-term rental pricing strategy seasonality booking window event pricing comp set`
2. Confirm the returned chunks match the property type.
   - Hotel context must include Dream Inn, RMS, hotel, BAR, room-type,
     occupancy, compression, or revenue-management material.
   - Airbnb context must include Airbnb, short-term rental, vacation-rental,
     comp-set, booking-window, seasonality, or event-pricing material.
   - If no relevant strategy chunks are returned, stop before publishing and
     say that strategy context is unavailable.
3. Build a structured calculator input from property facts, guardrails, market
   data, competitor stats, the occupancy estimator output, and concise strategy citations.
   Set `calculation_phase` to `draft`.
4. Run the bundled calculator in draft mode:

```bash
python3 skills/pricing-decision-reasoning/scripts/pricing_decision_calculator.py --calculation-phase draft --input-json '<calculator_input_json>'
```

5. Review the draft calculator output, then call
   `strategy-memory__search_strategy_memory(query, top_k=8)` again using the
   same property-type query plus the strongest draft price drivers.
6. Validate that the draft recommendation is supported by the second retrieval
   and set `strategy_context.validation.status` to `supported`, `corrected`, or
   `unsupported`.
   - If unsupported and no correction has been used, record exactly one concise
     correction in `corrections_applied` (280 characters or fewer), update the calculator input, and
     validate again.
   - If unsupported after one correction, stop and answer:
     `I don't know. Strategy context is unavailable or insufficient.`
7. Run the bundled calculator again in final mode. Final mode must include
   relevant initial and review RAG chunks plus
   `strategy_context.validation.status=supported|corrected`.
8. Run the final reasoning verifier with the stronger local model before
   publishing:

```bash
python3 skills/pricing-decision-reasoning/scripts/final_reasoning_verifier.py --model nemotron-3-super:latest --input-json '<compact_verification_payload_json>'
```

   The verifier payload must include the final calculator output, strategy
   citations, occupancy estimator output, guardrails, and compact
   supply-demand summaries. Log and persist the result as
   `final_reasoning_verification`. If the verifier does not return
   `status=approved`, stop before publishing and answer:
   `I don't know. Strategy context is unavailable or insufficient.`
9. Return or publish only the final calculator output after strategy review,
   final reasoning verification, and
   guardrails are complete. Never publish `draft_unreviewed` or `unsupported`
   output.

## Calculator Input Contract

Pass JSON to the calculator. Keep prices in USD dollars. Minimum fields:

```json
{
  "calculation_phase": "draft or final",
  "property_type": "hotel or airbnb",
  "property_profile": {},
  "guardrails": {"min_price": 100, "max_price": 300},
  "dates": [{"date": "YYYY-MM-DD", "current_price": 180, "current_price_trusted": true}],
  "market_signals": {},
  "competitor_stats": {},
  "occupancy_estimator": {
    "source": "occupancy_rate_estimator",
    "estimator_version": "1.0.0",
    "estimated_occupancy": {"YYYY-MM-DD": 0.72}
  },
  "estimated_occupancy": {"YYYY-MM-DD": 0.72},
  "strategy_context": {
    "initial": {"chunks": []},
    "review": {"chunks": []},
    "validation": {"status": "supported"}
  },
  "corrections_applied": []
}
```

`market_signals`, `competitor_stats`, and `estimated_occupancy` may be either
global objects or per-date objects keyed by `YYYY-MM-DD`. `estimated_occupancy`
must come from `occupancy_rate_estimator.py`, and the calculator validates the
`occupancy_estimator` provenance before returning a calendar. Include only
compact strategy citations or the returned chunks; do not paste private prompts.

The calculator returns JSON with `price_calendar` rows containing the existing
handoff fields plus `suggested_price_range_low`,
`suggested_price_range_high`, `estimated_occupancy`,
`strategy_memory_initial`, `strategy_memory_review`,
`strategy_validation_status`, `corrections_applied`, and
`calculator_version`.

## Hybrid Python Policy

The default calculation path must always use the bundled calculator script.
Temporary ad-hoc Python is allowed only as a sanity check for unusual outliers.
Ad-hoc checks must read the same calculator JSON, print JSON, avoid database
writes, avoid network calls, and never replace the bundled calculator schema.
Final values must come from the bundled calculator or a bundled-calculator rerun
after documented correction.

## Reasoning Steps

1. Retrieve property-type strategy memory as described above.
2. Build and persist the supply snapshot.
3. Build and persist the demand snapshot.
4. Synthesize supply/demand and persist the result.
5. Run the occupancy estimator and persist the result.
6. Build a per-date signal table for the whole `pricing_horizon`.
7. Identify guest intent for the market: business, university, medical, family, leisure, beach/outdoor, event-driven, or mixed.
8. Compare competitor rates against the subject property, but discount weak comps that differ strongly in location, quality, or guest type.
9. Review whether the supplied guardrails are plausible for the listing size and comp set.
10. Run the bundled calculator in draft mode and use its raw price, suggested range, guarded final price, confidence, and warnings only as a draft.
11. Retrieve strategy memory again, validate the draft, and rerun the calculator once in final mode. Use one correction at most.
12. Explain the final decision in terms of demand, comp relevance, occupancy, strategy citations, calculator output, guardrail fit, and confidence.

## Competitor Market Statistics

For each date, summarize competitor rates before choosing a price:

- `comp_count`
- `avg_rate`
- `median_rate`
- `p25_rate`
- `p75_rate`
- `min_rate`
- `max_rate`
- `avg_rating`
- `review_count_range`
- `subject_price_percentile` when current price is known

Use these statistics to reason about market position:

- If the subject price is below p25 and the listing quality is not weak, it may be underpriced.
- If the subject price is near the median, avoid large moves unless events, holidays, weather, or seasonality justify it.
- If the subject price is above p75, require clear property advantages or compression signals before increasing.
- If `comp_count` is low or comps are mixed hotel/vacation-rental inventory, lower `comp_set_relevance` and confidence.
- If competitor ratings/reviews are much stronger than the subject listing, treat their prices as a weaker ceiling.
- Treat MoodTrip hotel results as an important hotel demand signal. For city-center private rooms, studios, and 1BR apartments, nearby budget or midscale hotels may be direct substitutes and can be `usable` or `strong` comps when location, guest intent, and price band overlap.
- Hotel prices often react quickly to tourism demand and compression. Use hotel rate spikes as support for uplift, but still reconcile them with Airbnb and vacation-rental comps before final pricing.

## Comp Set Relevance

Judge whether competitor rates are `weak`, `usable`, or `strong` before using them as price anchors.

Use these criteria:

- property type similarity: entire home vs room vs hotel room vs vacation rental
- location proximity: same neighborhood or close to the same demand drivers
- capacity similarity: guest count, bedrooms, beds, and bathrooms
- quality similarity: rating, review count, hotel class, and visible listing quality
- amenity similarity: parking, kitchen, washer, workspace, view, pool, hot tub, pet-friendly, and other high-value amenities

Mark the comp set:

- `strong` when most comps match property type, location, capacity, quality, and amenities.
- `usable` when comps match location and guest intent but differ on some property attributes, including budget or midscale hotel comps for private rooms, studios, and 1BR apartments.
- `weak` when comps are mostly hotels with weak guest-intent overlap, far from the listing, different capacity, or materially stronger/weaker quality.

## Tavily Follow-Up Rules

Before final pricing, list the top 1-3 unanswered questions. Search only questions that could change the recommendation.

Tool:

```bash
python3 Claw/tools/tavily.py pricing-context --address "<listing address or city, state, country>" --start-date <YYYY-MM-DD> --end-date <YYYY-MM-DD> --query-count 4
```

For a single targeted follow-up:

```bash
python3 Claw/tools/tavily.py search --query "<specific pricing question>"
```

Useful query patterns:

- `why people travel to <city> in <month>`
- `<city> <month> peak season tourism`
- `<city> <month> off season hotel demand`
- `<city> <date range> major events tourism demand`
- `<city> hotel occupancy <month> demand trend`
- `<city> vacation rental market supply demand <month>`
- `<event name> expected attendance <city> <date>`
- `what do travelers care about when staying in <city>`
- `best neighborhoods to stay in <city>`
- `common complaints Airbnb guests have in <city>`

For each Tavily search, record:

- query
- short conclusion
- whether the result changed demand level, comp relevance, price direction, or confidence

## Decision Rules

Classify each date:

- `demand_level`: `low`, `normal`, `elevated`, or `compressed`
- `comp_set_relevance`: `weak`, `usable`, or `strong`
- `pricing_strategy`: `discount`, `hold`, `modest_uplift`, or `strong_uplift`
- `confidence`: `low`, `medium`, or `high`

Use these rules:

- Strong event demand plus high hotel prices and acceptable weather supports `strong_uplift`.
- Public holidays, school vacations, and long weekends support at least `modest_uplift` when the property suits family or leisure stays.
- Sunny weekend or good outdoor weather supports higher ADR for leisure, beach, park, hiking, or sightseeing markets.
- Rain lowers leisure demand unless indoor events, conferences, or business travel dominate.
- Heavy rain, high wind, or travel disruption risk should reduce confidence and avoid aggressive increases.
- If competitor median is below the current price, pricing above market requires a property-specific reason.
- If competitor median is above the current price and comps are relevant, uplift is justified.
- If the comp set is weak, keep changes conservative and mark confidence lower.

Use guest-priority findings to adjust property fit:

- If travelers value walkability, transit, nightlife, campus access, beach access, or event proximity and the listing matches that need, support a stronger price position.
- If travelers commonly complain about parking, noise, safety, cleanliness, or misleading location and the listing has that risk, reduce confidence or keep pricing conservative.
- If the listing has amenities that match known traveler priorities, such as workspace, kitchen, washer, parking, view, family setup, or pet-friendly rules, include them in `top_reasons`.

## Guardrail Adequacy Review

Before applying final prices, evaluate whether `min_price` and `max_price` are
credible for the listing's capacity and quality. Do not silently hide a
too-low cap behind a guarded final price.

Large Airbnb indicators include:

- entire home or apartment
- capacity >= 6 guests
- bedrooms >= 3
- beds >= 4
- bathrooms >= 2
- kitchen, laundry, parking, beach/outdoor access, or other family/group
  amenities

Compute simple sanity checks when the fields are available:

- `max_price_per_guest = max_price / capacity`
- `max_price_per_bedroom = max_price / bedrooms`
- `raw_to_cap_gap = raw_suggested_price - max_price`

Set `guardrail_review_needed = true` when:

- a large entire-place listing has `max_price_per_guest` below about `$45` in a
  US leisure market
- a 3+ bedroom entire-place listing has `max_price_per_bedroom` below about
  `$100`
- relevant vacation-rental comps, hotel substitutes, or demand signals support a
  price above `max_price`
- the raw suggested price is clamped to `max_price`

When this happens, the final user-facing summary must include:

- a plain warning that the supplied min/max range may be too low for the
  property
- the affected property facts, such as "7 guests, 3 bedrooms, 4 beds, 2.5 baths"
- a note that the returned price is constrained by host guardrails
- a suggested next guardrail review range when enough comp evidence exists

Confidence cannot be `high` when a low `max_price` cap materially constrains the
recommendation.

## Observable Decision Trace

During `pricing_decision`, stream concise decision-trace events to
`runs/airbnb-pricing-progress.log`. These are not hidden chain-of-thought; they
are short, auditable summaries of the facts checked and decisions made.

Use `status=info`, `stage=pricing_decision`, and one of these `substage` values:

- `supply_snapshot`: supply count, substitute inventory, scarcity, and compression facts
- `demand_snapshot`: events, holidays, tourism, weather, booking window, and guest segment facts
- `supply_demand_synthesis`: reconciled demand level and strongest supply-demand drivers
- `occupancy_input`: compact occupancy estimator input facts
- `occupancy_python_run`: estimator version and formula execution status
- `occupancy_result`: per-date occupancy values, supply/demand indexes, compression, and confidence
- `strategy_memory_initial`: first strategy retrieval query, property-type match, and citations
- `signal_table`: major signals collected per date
- `comp_relevance`: comp set relevance and why
- `demand_assessment`: demand level and strongest drivers
- `property_fit`: capacity, bedrooms, amenities, and guest segment fit
- `guardrail_check`: min/max sanity check and whether the cap constrains price
- `calculator_input`: compact calculator input facts, not raw prompts or private data
- `calculator_run`: calculator version, price range, raw price, and guarded final price
- `strategy_memory_review`: second strategy retrieval and validation citations
- `strategy_correction`: correction applied before rerunning the calculator, if any
- `final_reasoning_verification`: stronger-model compact verification verdict before publish
- `raw_price`: raw price before guardrails
- `guardrail_application`: clamp or adjustment after guardrails
- `confidence`: confidence level and main uncertainty
- `final_calendar`: final guarded price calendar summary

Prefer the `revnest-revenue-tools` MCP `log_progress` tool when it is available. Example MCP payload:

```json
{
  "run_id": "<run id>",
  "workflow": "pricing-workflow",
  "skill": "pricing-workflow",
  "called_skill": "pricing-decision-reasoning",
  "stage": "pricing_decision",
  "substage": "guardrail_check",
  "status": "info",
  "message": "Guardrail review: max_price is low for 7 guests / 3 bedrooms; recommendation will be capped.",
  "tool": "pricing-decision-reasoning",
  "metadata": {"capacity": 7, "bedrooms": 3, "max_price": 260, "guardrail_review_needed": true}
}
```

Also persist the same compact summary with `upsert_reasoning_step`. Example MCP
payload:

```json
{
  "account_id": "<account id>",
  "run_id": "<run id>",
  "property_id": "<property id>",
  "stage": "pricing_decision",
  "substage": "occupancy_result",
  "summary": "Estimated occupancy is 78% because event demand and tight substitute supply offset normal weather.",
  "facts": ["major event demand", "limited comparable supply"],
  "metrics": {"estimated_occupancy": 0.78, "supply_index": 0.72, "demand_index": 0.76},
  "tool": "occupancy_rate_estimator.py",
  "sources": ["market_data_summary", "strategy-memory"],
  "confidence": "medium"
}
```

CLI fallback:

```bash
python3 tools/progress_logger.py log \
  --run-id "<run id>" \
  --workflow "pricing-workflow" \
  --skill "pricing-workflow" \
  --called-skill "pricing-decision-reasoning" \
  --stage pricing_decision \
  --substage guardrail_check \
  --status info \
  --message "Guardrail review: max_price is low for 7 guests / 3 bedrooms; recommendation will be capped." \
  --tool pricing-decision-reasoning \
  --metadata-json '{"capacity":7,"bedrooms":3,"max_price":260,"guardrail_review_needed":true}'
```

Reasoning-step CLI fallback:

```bash
python3 tools/reasoning_step_logger.py \
  --account-id "<account id>" \
  --run-id "<run id>" \
  --property-id "<property id>" \
  --stage pricing_decision \
  --substage occupancy_result \
  --summary "Estimated occupancy is 78% because event demand and tight supply offset normal weather." \
  --metrics-json '{"estimated_occupancy":0.78,"supply_index":0.72,"demand_index":0.76}' \
  --tool occupancy_rate_estimator.py \
  --confidence medium
```

Do not log private chain-of-thought, long deliberation, or raw prompts. Log only
compact facts, classifications, selected numeric values, and user-facing
decision summaries.

Use USD dollars in progress-log messages and metadata for all prices. For CLI fallback commands, prefer
`USD 800/night` in shell `--message` strings instead of `$800/night`, because a
dollar sign inside double quotes can be interpreted by the shell. If any input
field ends in `_cents`, divide by 100 before using it in a progress message or
final summary.

## Guardrails

- `min_price` and `max_price` are host guardrails only. They are not the current
  live price.
- Use `current_price` only when it is explicitly supplied by the user, extracted
  from the verified listing page, or read from the database. If no current price
  is available, set `current_price` and `change_pct` to `null`/unknown and say
  that no current-price baseline was available.
- Final price must be at least `min_price`.
- Final price must be no higher than `max_price`.
- Week-over-week price changes must not exceed 20% unless the user explicitly approves an exception.
- If a raw price violates a guardrail, clamp it and explain the adjustment.
- If `guardrail_review_needed` is true, include that warning in
  `guardrail_adjustments` and the final text summary.

## Internal Handoff Format

Produce a JSON-compatible price calendar for internal tool handoff. This is not the final user-facing output. Each date must include:

- `date`
- `current_price` in USD dollars
- `raw_suggested_price` in USD dollars
- `final_price_after_guardrails` in USD dollars
- `change_pct`
- `demand_level`
- `comp_set_relevance`
- `pricing_strategy`
- `confidence`
- `top_reasons`
- `signals_used`
- `tavily_followups`
- `guardrail_adjustments`
- `guardrail_review_needed`
- `guardrail_warning`
- `suggested_price_range_low`
- `suggested_price_range_high`
- `estimated_occupancy`
- `strategy_memory_initial`
- `strategy_memory_review`
- `strategy_validation_status`
- `corrections_applied`
- `calculator_version`

After the guarded price calendar is ready, use `pricing-output-publisher` to produce the final text summary, estimate RevPAR, and write predicted prices to PostgreSQL.
