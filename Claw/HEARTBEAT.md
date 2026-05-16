# RevNest Hotel Pricing Heartbeat

Run the hotel pricing workflow every 30 minutes so the WebApp hotel dashboard
stays refreshed from PostgreSQL. The default heartbeat is one all-room-types
batch run for the hotel account.

## Schedule

- Frequency: every 30 minutes
- Working directory: `/home/ubuntu/RevNest/Claw`
- Command:

```bash
python3 tools/run_hotel_heartbeat.py --interval-minutes 30
```

For a local long-running heartbeat loop:

```bash
python3 tools/run_hotel_heartbeat.py --loop --interval-minutes 30
```

## Scope

- Account: `00000000-0000-0000-0000-000000000103`
- Account email: `hotel@revnest.ai`
- Property type: `hotel`
- Scope: all `Hotel Room Type` rows owned by the hotel account

The runner starts one `tools/run_pricing_agent.py` workflow with
`--hotel-scope all-room-types`. That workflow loads each room type from
PostgreSQL, fetches shared market data once, then publishes guarded calendars
and RevPAR estimates per room type.

Use the legacy per-room-type fallback only when needed:

```bash
python3 tools/run_hotel_heartbeat.py --per-room-type --dry-run
```

## Conversation Contract

During publish, each room type uses a stable automated Revy conversation id:

```text
revy-heartbeat-<property_id>
```

This lets every 30-minute heartbeat update the same `revy_conversation` row for
that room type instead of creating a new history item each cycle.

## Safety

- The runner uses `runs/hotel-heartbeat.lock` to avoid overlapping batches.
- If the lock is active, skip the cycle and print a JSON status.
- Use `--dry-run` to verify property discovery and command generation without
  launching OpenClaw/NIM work.

