# RevNest Safe PMS Approval Demo

This demo proves the NemoClaw-specific boundary: Revy can do autonomous revenue
management work, but it cannot directly mutate live MockHotel PMS prices from the
agent sandbox. Live PMS writes are reserved for an authenticated WebApp operator
clicking Accept.

## Security Boundary

- Revy may read MockHotel current rates through:
  `GET host.openshell.internal:3001/api/agent/current-prices`.
- Revy may publish forecast rows to RevNest PostgreSQL and create
  `pricing_record.record_type = 'pending_task'`.
- Revy must not call WebApp accept APIs, MockHotel write APIs, or direct
  MockHotel database writes.
- WebApp accept APIs require a signed `revnest_session` cookie whose account id
  matches the submitted `accountId`.
- Accepted price logs include `acceptedBy`, `acceptedAt`,
  `approvalSource: "webapp_accept_button"`, and `mockHotelSync`.

## Access Paths

- Human/operator browser: use `http://localhost:3000` on the GX10 host or
  through an SSH/VS Code forwarded port.
- NemoClaw/OpenShell sandbox: `localhost` is the sandbox itself. Host services
  are reached through `host.openshell.internal`.
- Revy may use `http://host.openshell.internal:3001/api/agent/current-prices`
  for read-only MockHotel comparison. Revy must not use the WebApp access path
  to approve tasks; approval belongs to the human browser session.

## Pending Task Types

WebApp pending tasks are intentionally named by approval reason, not only by
price direction:

- `price_adjustment_required`: the current MockHotel PMS price is outside
  Revy's strategy-backed range. The task is marked **Approval required** because
  accepting it is the only allowed path to mutate live PMS prices.
- `price_review_recommended`: the current MockHotel PMS price is still inside
  Revy's strategy-backed range, but the suggested final price has a material
  delta, low confidence, or a guardrail concern. The task is marked
  **Review recommended** so the operator can inspect the evidence before sync.

`Increase` and `Decrease` remain as `priceDirection`, but they are no longer the
main task type. This makes the safety value visible: Revy stages work, explains
why approval is needed, and WebApp decides whether to sync MockHotel.

## NemoClaw Policy

The judge-facing policy preset is:

```text
/home/asus/revnest/Claw/nemoclaw/revnest-judge-minimal.yaml
```

For judging, use a fresh or reset sandbox and apply only the minimal RevNest
policy:

```bash
/home/asus/revnest/Claw/nemoclaw/prepare_judge_minimal_sandbox.sh revnest-judge
```

The setup script removes known non-judge presets, applies
`revnest-judge-minimal`, turns shields up, captures policy evidence, and fails
if active Airbnb, npm, PyPI, Homebrew, Discord, Hugging Face, Slack, or Telegram
policies remain.

The expected status is:

```text
Shields: UP (lockdown active)
Policy:  restrictive
```

The older `revnest-safe-pms.yaml` remains as the narrow MockHotel read-only
building block, but the judge preset is preferred because it also makes the
allowed inference routes explicit and keeps the active policy list clean.

## Demo Flow

1. Happy path: ask Revy to price MockHotel rooms. Revy collects market context,
   writes RevNest forecast rows, and creates pending tasks.
2. Verify before approval: MockHotel live prices remain unchanged, while
   `pricing_record` has pending tasks and RevNest charts show forecast prices.
   In WebApp, pending cards show `Price adjustment required` or
   `Price review recommended` plus the approval gate label.
3. Blocked path: ask Revy to write directly to MockHotel PMS. Revy must stage
   pending tasks and say WebApp approval is required. If a direct write is
   attempted, NemoClaw/OpenShell policy should deny it and log the denial.
4. Approval path: log in to WebApp as the hotel operator and click Accept. Only
   this path calls MockHotel sync and writes the accepted `price_log`.

## Evidence To Capture

The fixed, saved evidence chain for judges is:

```text
/home/asus/revnest/Claw/nemoclaw/evidence/demo_transcript.md
```

Regenerate it with:

```bash
python3 /home/asus/revnest/Claw/tests/run_safe_pms_evidence_chain_demo.py
```

This creates a three-act transcript and matching JSON evidence:

- Revy creates a `price_adjustment_required` pending task.
- NemoClaw/OpenShell denies a direct MockHotel PMS write.
- WebApp Accept is the only represented path that syncs the accepted price to
  MockHotel with human approval metadata.

Use the transcript first, then open the raw logs below if judges ask for the
underlying policy evidence.

- `nemoclaw revnest-judge logs --follow`
- `openshell policy get --full revnest-judge`
- `nemoclaw revnest-judge shields status`
- Policy denial for direct PMS write attempts
- WebApp pending task before Accept
- MockHotel live price unchanged before Accept
- WebApp accepted `price_log` with human approval metadata
- MockHotel live price changed after Accept

Saved evidence from the locked local sandbox is available under:

```text
/home/asus/revnest/Claw/nemoclaw/evidence/logs/
```

The key files to show judges are:

- `demo_transcript.md`
- `samples/safe_pms_evidence_chain.json`
- `20_judge_minimal_policy_list.log`
- `21_judge_minimal_openshell_policy_full.yaml`
- `22_judge_minimal_shields_status.log`
- `15_direct_pms_write_denied_concise.log`

## Classification Demo

Run this local dry-run to generate two pending tasks without database or PMS
writes:

```bash
python3 /home/asus/revnest/Claw/tests/run_pending_task_classification_demo.py
```

Expected evidence:

- `dry_run: true`
- `database_write.status: skipped`
- one `price_adjustment_required` task where current PMS price is outside the
  strategy range
- one `price_review_recommended` task where current PMS price is inside the
  strategy range but the suggested change is material
