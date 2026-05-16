---
name: pricing-tourism-demand
description: Research tourism demand, seasonality, traveler priorities, and unresolved demand questions for RevNest pricing workflows using Tavily.
---

# Pricing Tourism Demand

Use this skill inside `pricing-market-data` and during
`pricing-decision-reasoning` follow-up when demand remains uncertain.

Run destination-market research:

```bash
python3 tools/tavily.py pricing-context --address "<city, state, country>" --start-date <YYYY-MM-DD> --end-date <YYYY-MM-DD> --query-count 4
```

Use targeted follow-ups only when they could change demand level, comp
relevance, price direction, or confidence:

```bash
python3 tools/tavily.py search --query "why people travel to <city> in <month>"
python3 tools/tavily.py search --query "<city> hotel occupancy <month> demand trend"
python3 tools/tavily.py search --query "what do travelers care about when staying in <city>"
```

Ignore country-level or source-market travel reports unless they explicitly
connect to lodging demand in the verified destination market.
