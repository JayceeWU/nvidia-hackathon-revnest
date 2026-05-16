---
name: pricing-guardrails
description: Review RevNest min/max price guardrails for plausibility before pricing, especially for large Airbnb listings and hotel room types whose market comps may exceed the supplied cap.
---

# Pricing Guardrails

Use this skill after `pricing-context` has produced property size, type, and
market facts.

## Review Rules

Run the guardrail review tool when capacity, bedrooms, beds, bathrooms, property
type, and market are known:

```bash
python3 tools/guardrail_review.py --min-price <min_price> --max-price <max_price> --capacity <guests> --bedrooms <bedrooms> --beds <beds> --bathrooms <bathrooms> --property-type "<property type>" --market "<city, state>"
```

Flag a review when the supplied cap appears too low for property size, when
relevant comps exceed `max_price`, when the raw suggested price will be capped,
or when most final prices land near `max_price`.

If a guardrail looks too low, still obey `min_price` and `max_price`, but state
that the result is constrained by host guardrails and recommend reviewing a
higher range when market evidence supports it.

## Progress

Use stage `guardrail_review`, tool `tools/guardrail_review.py`, and
`workflow=pricing-workflow`. Log skipped rather than failed if property size is
unavailable and the workflow can continue with lower confidence.
