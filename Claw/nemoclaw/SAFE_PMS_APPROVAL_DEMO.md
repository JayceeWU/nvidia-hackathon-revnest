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

## NemoClaw Policy

The demo policy preset is:

```text
/home/asus/revnest/Claw/nemoclaw/revnest-safe-pms.yaml
```

It is also installed in the local NemoClaw blueprint presets directory as
`revnest-safe-pms`.

Preview the policy without changing the current sandbox:

```bash
nemoclaw my-assistant policy-add revnest-safe-pms --dry-run
```

For judging, use a fresh hardened sandbox or snapshot, then apply:

```bash
nemoclaw my-assistant policy-add revnest-safe-pms --yes
openshell policy get --full my-assistant
```

If the preset has not been installed into NemoClaw on another machine, apply the
project copy instead:

```bash
nemoclaw my-assistant policy-add --from-file /home/asus/revnest/Claw/nemoclaw/revnest-safe-pms.yaml --yes
```

## Demo Flow

1. Happy path: ask Revy to price MockHotel rooms. Revy collects market context,
   writes RevNest forecast rows, and creates pending tasks.
2. Verify before approval: MockHotel live prices remain unchanged, while
   `pricing_record` has pending tasks and RevNest charts show forecast prices.
3. Blocked path: ask Revy to write directly to MockHotel PMS. Revy must stage
   pending tasks and say WebApp approval is required. If a direct write is
   attempted, NemoClaw/OpenShell policy should deny it and log the denial.
4. Approval path: log in to WebApp as the hotel operator and click Accept. Only
   this path calls MockHotel sync and writes the accepted `price_log`.

## Evidence To Capture

- `nemoclaw my-assistant logs --follow`
- `openshell policy get --full my-assistant`
- Policy denial for direct PMS write attempts
- WebApp pending task before Accept
- MockHotel live price unchanged before Accept
- WebApp accepted `price_log` with human approval metadata
- MockHotel live price changed after Accept
