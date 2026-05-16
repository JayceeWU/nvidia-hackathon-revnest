# RevNest Safe PMS Evidence

This directory stores judge-facing evidence for the NemoClaw Safe PMS Approval
demo. Use a fresh or reset judge sandbox named `revnest-judge` for final
evidence so unrelated presets do not weaken the least-privilege story.

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

Prepare the judge sandbox with the minimal policy:

```bash
/home/asus/revnest/Claw/nemoclaw/prepare_judge_minimal_sandbox.sh revnest-judge
```

Expected:

```text
Shields: UP (lockdown active)
Policy:  restrictive
```

The expected `policy-list` evidence has only `revnest-judge-minimal` active for
the RevNest judge story. Do not show evidence with active Airbnb, npm, PyPI,
Homebrew, Discord, Hugging Face, Slack, or Telegram presets.

The minimal judge policy allows only:

```text
GET/POST local inference on host.openshell.internal:11434, :11435, and :8000
GET/POST NVIDIA inference endpoints on /v1 chat, completions, embeddings, models
GET host.openshell.internal:3001/api/agent/current-prices
```

Direct PMS writes remain denied by OpenShell:

```text
POST host.openshell.internal:3001/api/prices
```

## Key Log Files

- `demo_transcript.md`
- `samples/safe_pms_evidence_chain.json`
- `logs/20_judge_minimal_policy_list.log`
- `logs/21_judge_minimal_openshell_policy_full.yaml`
- `logs/22_judge_minimal_shields_status.log`
- `logs/23_judge_minimal_sandbox_status.log`
- `logs/15_direct_pms_write_denied_concise.log`

Legacy `08`-`11` lockdown logs were captured from an older `my-assistant`
sandbox and may include extra active presets. Regenerate the judge logs above
before presenting NemoClaw evidence.
