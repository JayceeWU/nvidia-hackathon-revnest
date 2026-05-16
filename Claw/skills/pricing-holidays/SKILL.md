---
name: pricing-holidays
description: Collect holiday and school-break calendars for RevNest pricing workflows using the verified destination market.
---

# Pricing Holidays

Use this skill inside `pricing-market-data`.

Run holiday collection:

```bash
python3 tools/get_holiday.py calendar --address "<city, state, country>" --start-date <YYYY-MM-DD> --end-date <YYYY-MM-DD>
```

Collect public holidays, school vacations, observances, and long-weekend
patterns. Treat holidays as demand signals to be reconciled with events,
competitor rates, and property fit.
