---
name: pricing-events
description: Collect local event demand signals for RevNest pricing workflows from Ticketmaster and SerpApi Google Events.
---

# Pricing Events

Use this skill inside `pricing-market-data`.

Use both event sources when possible:

```bash
python3 tools/ticketmaster.py events --address "<city, state, country>" --start-date <YYYY-MM-DD> --end-date <YYYY-MM-DD>
python3 tools/serpapi.py events --address "<city, state, country>" --start-date <YYYY-MM-DD> --end-date <YYYY-MM-DD>
```

Collect event names, dates, venues, distance or market relevance, and likely
demand pressure. Treat concerts, sports, conferences, festivals, graduations,
and family events as possible compression drivers only when dates and location
match the property market.
