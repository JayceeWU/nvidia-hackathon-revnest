---
name: pricing-weather
description: Collect and summarize weather demand modifiers for RevNest pricing workflows using the verified property or hotel market location.
---

# Pricing Weather

Use this skill inside `pricing-market-data`.

Run weather collection for the pricing horizon:

```bash
python3 tools/weather_tool.py weather --location "<city, state or address>" --start-date <YYYY-MM-DD> --end-date <YYYY-MM-DD>
```

Weather is a demand modifier, not a standalone pricing decision. Summarize
conditions that can affect travel demand, such as clear leisure weather, rain,
high wind, heat, cold, or disruption risk. Mark the stage skipped or failed if
the tool cannot return usable data, then continue.
