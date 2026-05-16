# RevNest Safe PMS Demo Transcript

This transcript is the fixed, judge-facing evidence chain for the NemoClaw Safe
PMS Approval demo. It proves that Revy can do useful autonomous revenue
management work, while NemoClaw/OpenShell and the WebApp approval gate prevent
unauthorized MockHotel PMS writes.

## Result

- Demo: `revnest_nemoclaw_safe_pms_approval_chain`
- Passed: `true`
- Sandbox: `my-assistant`
- Policy: `revnest-safe-pms`

## Act 1: Revy Creates A Pending Task

Revy compares a guarded hotel calendar against MockHotel current PMS prices. It
does not write MockHotel directly. It stages a `pricing_record` pending task for
human approval.

- Property: `Demo Required Room`
- Date: `2026-05-20`
- Current MockHotel PMS price: `$150`
- Revy suggested price: `$210`
- Pending task type: `price_adjustment_required`
- Approval gate: `Approval required`
- Reason: `current MockHotel price is below Revy's strategy range; final recommendation differs by $60 and +40%`

```json
{
  "agentSuggestedPrice": "$210",
  "currentPrice": "$150",
  "id": "task-hotel-review-demo-required-room-2026-05-20",
  "propertyId": "demo-required-room",
  "source": "mockhotel_price_review",
  "strategyRange": {
    "currentPosition": "below_range",
    "high": 230.0,
    "low": 190.0
  },
  "taskType": "price_adjustment_required"
}
```

## Act 2: NemoClaw/OpenShell Denies Direct PMS Write

A direct sandbox POST to MockHotel `/api/prices` is denied by the active
`revnest-safe-pms` policy. This is the core NemoClaw-specific guardrail: the
agent cannot bypass the approval workflow.

- Shields: `Shields: UP (lockdown active)`
- Policy state: `revnest-safe-pms active`
- Evidence log: `logs/15_direct_pms_write_denied_concise.log`

```text
318:[1778939579.802] [sandbox] [OCSF ] [ocsf] HTTP:POST [MED] DENIED /usr/bin/python3.13(29927) -> POST http://host.openshell.internal:3001/api/prices [policy:revnest_mockhotel_readonly engine:l7] [reason:FORWARD_L7 deny POST host.openshell.internal:3001/api/prices reason=POST /api/pr...]
```

## Act 3: WebApp Accept Changes MockHotel

Only an authenticated WebApp operator can accept the pending task. The accepted
price log includes human approval metadata and the MockHotel sync result.

- Before Accept: `150.0`
- After Accept: `210.0`
- Approval source: `webapp_accept_button`
- Accepted by: `hotel@revnest.ai`
- MockHotel sync ok: `true`

```json
{
  "acceptedAt": "2026-05-16T16:00:00.000Z",
  "acceptedBy": {
    "accountType": "hotel",
    "email": "hotel@revnest.ai",
    "id": "00000000-0000-0000-0000-000000000103",
    "name": "Hotel Operator",
    "role": "host"
  },
  "approvalSource": "webapp_accept_button",
  "mockHotelSync": {
    "ok": true,
    "updatedRoomTypePrices": 1,
    "updates": [
      {
        "newPrice": 210.0,
        "oldPrice": 150.0,
        "roomType": "Demo Required Room",
        "roomTypeId": "demo-required-room",
        "stayDate": "2026-05-20"
      }
    ]
  }
}
```

## Judge Takeaway

OpenClaw alone could be prompted to write PMS data. RevNest uses NemoClaw and
OpenShell to enforce that Revy can only stage work inside bounds. Live MockHotel
mutation happens only after a human clicks Accept in the WebApp.
