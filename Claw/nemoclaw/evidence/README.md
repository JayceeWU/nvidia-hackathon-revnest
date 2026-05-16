# RevNest Safe PMS Evidence

This directory stores judge-facing evidence for the NemoClaw Safe PMS Approval
demo. The current sandbox is `my-assistant`.

## One-Command Evidence Chain

Generate the fixed judge transcript and JSON evidence package:

```bash
python3 /home/asus/revnest/Claw/tests/run_safe_pms_evidence_chain_demo.py
```

The script verifies and writes:

- `demo_transcript.md`: the three-act transcript judges can read first.
- `samples/safe_pms_evidence_chain.json`: structured evidence for the same
  chain.

The transcript proves:

1. Revy creates a `price_adjustment_required` pending task instead of writing
   MockHotel directly.
2. NemoClaw/OpenShell denies a direct PMS write to
   `POST host.openshell.internal:3001/api/prices`.
3. WebApp Accept is the only path represented as changing MockHotel, with
   `acceptedBy`, `acceptedAt`, `approvalSource: "webapp_accept_button"`, and
   `mockHotelSync`.

## Full Hotel Agent Run Evidence Layout

Prepare the saved evidence folder for a complete hotel NemoClaw run:

```bash
python3 /home/asus/revnest/Claw/tests/run_full_hotel_agent_evidence_design.py
```

This writes `full_hotel_agent_run/` with DB before/after snapshots, WebApp
dashboard API snapshots, and the exact `run_command.sh` for the live run. To
execute the long agent workflow and capture stdout, run:

```bash
python3 /home/asus/revnest/Claw/tests/run_full_hotel_agent_evidence_design.py --run-agent
```

## Fixed Security State

The sandbox is locked with shields:

```bash
nemoclaw my-assistant shields status
```

Expected:

```text
Shields: UP (lockdown active)
Policy:  restrictive
```

The `revnest-safe-pms` policy is active:

```bash
nemoclaw my-assistant policy-list
openshell policy get --full my-assistant
```

The policy allows only read-only MockHotel inspection from the sandbox:

```text
GET host.openshell.internal:3001/api/agent/current-prices
```

Direct PMS writes are denied by OpenShell:

```text
POST host.openshell.internal:3001/api/prices
```

## Key Log Files

- `demo_transcript.md`
- `samples/safe_pms_evidence_chain.json`
- `logs/08_shields_status_after_lockdown.log`
- `logs/09_sandbox_status_after_lockdown.log`
- `logs/10_policy_list_after_lockdown.log`
- `logs/11_openshell_policy_full_after_lockdown.yaml`
- `logs/13_openshell_exec_direct_pms_write_probe_after_lockdown.log`
- `logs/15_direct_pms_write_denied_concise.log`
