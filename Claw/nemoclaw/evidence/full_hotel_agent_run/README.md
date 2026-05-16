# Full Hotel Agent Run Evidence

This folder is the fixed evidence layout for the live hotel NemoClaw run.

## Runtime

- Account: `00000000-0000-0000-0000-000000000103`
- Runtime: Hotel -> NemoClaw `my-assistant`
- Policy: `revnest-safe-pms`
- Run id: `hotel-full-evidence-20260516T145841Z`
- Generated at: `2026-05-16T14:58:41Z`
- Agent executed: `false`

## Evidence Files

- `db_before.json`: `property_price`, pending tasks, and recent
  `revy_conversation` rows before the run.
- `agent_stdout.log`: full stdout/stderr from the agent when `--run-agent` is
  used.
- `db_after.json`: same DB snapshot after the run.
- `webapp_before.json` / `webapp_after.json`: WebApp dashboard API snapshots.
- `run_command.sh`: exact command for the full live run.

## Live Run Command

```bash
python3 tools/run_pricing_agent.py --clear-log --account-id 00000000-0000-0000-0000-000000000103 --property-type hotel --hotel-scope all-room-types --runtime-mode nemoclaw --session-id hotel-full-evidence-20260516T145841Z --run-id hotel-full-evidence-20260516T145841Z --thinking medium --verbose on --timeout-seconds 1800
```

## Judge Story

1. Before: DB snapshot shows current forecast rows and pending tasks.
2. During: agent stdout shows OpenClaw running inside NemoClaw, using the hotel
   all-room-types branch.
3. After: DB snapshot and WebApp API show Revy forecast rows, saved
   `revy_conversation`, and pending tasks. MockHotel live PMS writes remain gated
   by WebApp Accept.
