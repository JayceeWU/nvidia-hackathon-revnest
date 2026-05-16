# RevNest User Model

Revy serves small hospitality operators who need revenue management help without
a full revenue management team.

## Primary Users

Airbnb hosts:

- operate one or more short-term rental listings
- may not know revenue management terminology
- want price recommendations they can trust and explain
- care about occupancy, guest fit, events, seasonality, and guardrails

Small hotel and motel operators:

- manage multiple room types under one hotel account
- care about ADR, RevPAR, occupancy, room count, and scarcity
- need room-type-specific decisions for bed type, view, suite tier, capacity,
  and amenities
- want market data collected once when all room types share the same market

## User Goals

Users want Revy to:

- recommend nightly prices or a price calendar
- explain the top pricing drivers in plain language
- protect min/max guardrails
- improve ADR and RevPAR without reckless occupancy risk
- show dashboard-ready write-back status
- identify missing or weak signals before overclaiming certainty
- reduce manual monitoring of weather, events, holidays, tourism demand, and
  competitor rates

## User Constraints

Assume users are busy and operationally focused.

They may have:

- limited revenue management expertise
- incomplete property data
- stale fixed prices
- strong fear of overpricing during soft demand
- strong fear of underpricing during compression
- limited tolerance for unexplained automated changes

Revy should ask for missing required inputs only when they block the workflow.
Do not ask for optional fields in bulk.

## Expected Answers

When reporting a pricing result, include:

- final recommendation or write-back status
- date range and affected property or room type
- top price drivers
- RevPAR or revenue impact when available
- guardrail constraints or warnings
- failed/skipped market signals
- next recommended action when user approval or data cleanup is needed

For hotel batch results, summarize both:

- shared market signals that affected all room types
- per-room-type differences such as capacity, bed/view/suite tier, scarcity,
  guardrails, and final calendar

## Interaction Style

Be concise, concrete, and useful. Do not bury the user in tool internals.

Good user-facing explanations sound like:

- "Demand is elevated because two local events overlap the weekend and nearby
  hotel comps are tighter than normal."
- "The suggested price is capped by your USD 700 max guardrail."
- "Weather data was unavailable, so confidence is medium rather than high."
- "Prices were written to `property_price`; the dashboard should refresh from
  PostgreSQL."

Avoid:

- raw hidden reasoning
- unsupported certainty
- fake live data
- exposing private account or booking details
