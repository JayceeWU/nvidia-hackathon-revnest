---
name: pricing-competitors
description: Collect and evaluate hotel, motel, and vacation-rental competitor rates for RevNest Airbnb and hotel pricing workflows.
---

# Pricing Competitors

Use this skill inside `pricing-market-data` and before
`pricing-decision-reasoning`.

## SerpApi Comps

Use Google Hotels and vacation-rental views as complementary signals:

```bash
python3 tools/serpapi.py hotels --address "<city or address>" --check-in-date <YYYY-MM-DD> --pricing-horizon <pricing_horizon> --adults 2 --search-mode both
```

For hotel inventory, hotel and motel comps usually carry the strongest weight.
For Airbnb inventory, vacation-rental comps and overlapping budget/midscale
hotel comps can both be useful depending on guest intent.

## MoodTrip Comps

When MoodTrip MCP tools are available, use the `moodtrip-hotel-search` skill or
namespaced tools such as `moodtrip__searchHotelsWithRates`. Run several focused
queries when broader coverage is needed, then deduplicate by hotel name/id.

## Summary

Keep Google Hotels, Google vacation rentals, and MoodTrip hotel comps separate
before synthesis. Summarize rates, ratings, reviews, class, amenities, location,
and comp-set relevance.
