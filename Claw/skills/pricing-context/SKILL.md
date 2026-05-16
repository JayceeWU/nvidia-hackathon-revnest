---
name: pricing-context
description: Establish Airbnb pricing-run context from my_place, property_id, and account_id; verify listing facts with redundant browser reads, write extracted profile fields to property, and stop on untrusted extraction.
---

# Pricing Context

Use this skill only for `property_type=airbnb` runs inside `pricing-workflow`.
Hotel runs should load PostgreSQL property memory directly in the workflow and
should not invoke this skill.

## Inputs

- `my_place`: Airbnb URL or place reference. Required.
- `property_id`: RevNest property id. Required.
- `account_id`: RevNest account UUID. Required.

Do not require any other input for this skill. If `my_place` is missing or blank, log `context` as failed, stop the workflow before market data or pricing, and return a user-facing message asking for an Airbnb URL or place reference.

## Airbnb Browser Reads

Verify the current Airbnb page from `my_place` before completing `context`. Use at least two successful reads before trusting extracted facts.

Primary read: existing `agent-browser` / `agent-browser-clawdbot` in an isolated
session based on the run id:

```bash
agent-browser --session "<run_id>" open "<my_place>"
agent-browser --session "<run_id>" wait --load networkidle
agent-browser --session "<run_id>" get url --json
agent-browser --session "<run_id>" get title --json
agent-browser --session "<run_id>" snapshot --json
```

Secondary read: OpenClaw built-in Browser with the managed `openclaw` profile:

```bash
openclaw browser --browser-profile openclaw status --json
openclaw browser --browser-profile openclaw start --json
openclaw browser --browser-profile openclaw open "<my_place>" --json
openclaw browser --browser-profile openclaw wait --load networkidle --json
openclaw browser --browser-profile openclaw snapshot --interactive --json
```

Prefer the managed `openclaw` profile. Use the documented `user` / existing
Chrome session profile only when signed-in browser state is explicitly needed
and the user can approve any attach prompt.

If one browser method is unavailable or fails, repeat the successful method a
second time after reload/wait and compare the stable fields. A context read is
trusted only when two successful reads agree on the listing identity and do not
conflict on capacity, city/state, bed, or bath.

If `my_place` contains `/rooms/<room_id>`, every successful read must end on a
URL that still contains that room id. Otherwise log `context` as failed and stop
before location-based tools.

## Extract And Write

Extract these fields from the trusted browser reads:

- `capacity`
- `listing_title`
- `listing_type` or `room_type`
- `neighborhood` when visible
- `zip_code`
- `county`
- `state`
- `city`
- `bed`
- `bath`
- `other_info`

`other_info` must be a concise LLM summary of useful listing context outside the
structured fields. Include review signals, amenities/facilities, photo or image
count, listing-quality signals, and caveats. Do not repeat capacity, zip code,
county, state, city, bed, or bath as the main content of `other_info`.

Write successful extraction back to `property` and merge compatible JSON keys:

```sql
UPDATE property
SET capacity = <capacity>,
    zip_code = <zip_code>,
    county = <county>,
    state = <state>,
    city = <city>,
    bed = <bed>,
    bath = <bath>,
    other_info = <other_info>,
    data = data || <profile_json>::jsonb,
    updated_at = now()
WHERE account_id = <account_id>::uuid
  AND id = <property_id>;
```

Use JSON keys `capacity`, `listingTitle`, `listingType`, `roomType`,
`neighborhood`, `zipCode`, `county`, `state`, `city`, `bed`, `bath`,
`otherInfo`; include `beds` and `bathroom` as compatibility aliases when those
values are known. Also write a human-readable `name` built from the trusted
listing title, city/state or neighborhood, and listing/room type. Never leave a
final Airbnb display name as `Airbnb <long room id>` or the raw `airbnb-...`
property id.

## Stop Conditions

If listing read, URL verification, required extraction, or database write-back
fails, immediately log `context` as failed and stop the workflow before market
data or pricing. Return a user-facing message that names the failed read/write
step and explains what could not be verified. Do not continue reasoning or make
pricing decisions from untrusted context.

## Progress

Log `context started`, compact `status=info` events for each browser read, a compact `status=info` event for `property_profile_write`, and then
`context completed`. Use `workflow=pricing-workflow` and
`skill=pricing-workflow`, with `called_skill=pricing-context` when invoked by the
main workflow.
