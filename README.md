# RevNest

RevNest is a local demo stack for AI-assisted revenue management. It combines a
host-facing dashboard, a mock hotel PMS, and a Claw/OpenClaw pricing agent named
Revy. The demo is designed around a safety boundary: Revy can research,
recommend, write forecast records, and create pending pricing tasks, but live
hotel price changes require a human approval action from WebApp.

## Judge Demo In 3 Minutes

1. Start the local surfaces:

```bash
docker compose -f Claw/data/docker-compose.yml up -d
docker compose -f MockHotel/docker-compose.yml up -d postgres
npm --prefix WebApp run dev
npm --prefix MockHotel run dev
```

2. Open `http://localhost:3000` and `http://localhost:3001`.
3. In WebApp, sign in as `airbnb@revnest.ai` / `demo`, add an Airbnb property,
   and show Revy pricing the new property.
4. Sign in as `hotel@revnest.ai` / `demo`, open the hotel home dashboard, and
   click `Run Revy` to price all Dream Inn room types.
5. Show the hotel `Pending Tasks` panel with Revy's recommended price changes.
6. Demonstrate the safety boundary: attempt a direct PMS write from NemoClaw and
   show it is denied by the safe PMS policy.
7. Approve the task through WebApp, Discord, or a human approval prompt.
8. Switch to MockHotel and show the accepted room-type price changed in the PMS.

## What Is In This Repo

```text
WebApp/       RevNest dashboard on port 3000
MockHotel/    Dream Inn mock PMS on port 3001
Claw/         Revy pricing agent runtime, tools, skills, tests, and seed DB
README.md     Project-level setup and operating guide
```

### WebApp

The main dashboard for Airbnb hosts and hotel operators. It reads the Claw
PostgreSQL database, shows properties or hotel room types, streams Revy progress,
stores Revy conversations, displays pending tasks and price logs, and exposes the
human approval flow.

Important paths:

- `WebApp/app/page.js` - main dashboard UI.
- `WebApp/app/api/agent-runs/route.js` - starts pricing runs.
- `WebApp/lib/agentRunStore.js` - launches `Claw/tools/run_pricing_agent.py`.
- `WebApp/lib/db.js` - Claw database connection.
- `WebApp/lib/mockHotelSync.js` - hotel PMS sync helper after approval.

### MockHotel

A small Dream Inn room-type price management system. It has its own PostgreSQL
database and mirrors the hotel room-type seed data used by WebApp. Revy may read
current PMS prices through the protected agent API, but live write-back should go
through WebApp's authenticated human approval flow.

Important paths:

- `MockHotel/app/page.js` - PMS UI.
- `MockHotel/app/api/prices/route.js` - authenticated PMS price mutation.
- `MockHotel/app/api/agent/current-prices/route.js` - read-only agent API.
- `MockHotel/sql/` - mock PMS schema and seed data.

### Claw

The Revy agent runtime. It contains the pricing workflow, tools, skills, progress
logging, database write-back helpers, NemoClaw policies, and smoke tests.

Important paths:

- `Claw/tools/run_pricing_agent.py` - primary pricing workflow runner.
- `Claw/tools/run_parallel_market_data.py` - parallel market-data fan-out.
- `Claw/tools/revpar_estimate.py` - forecast and conversation write-back.
- `Claw/tools/progress_logger.py` - JSONL progress events for WebApp.
- `Claw/data/sql/` - dashboard schema and seed data.
- `Claw/skills/` - pricing workflow skills.
- `Claw/nemoclaw/` - sandbox policies and demo notes.
- `Claw/tests/` - local smoke and consistency tests.

## Local Access Paths

RevNest runs three local surfaces:

- WebApp dashboard: `http://localhost:3000`
- MockHotel PMS: `http://localhost:3001`
- Claw PostgreSQL: `postgres://postgres:postgres@localhost:55434/dev`
- MockHotel PostgreSQL: `postgres://postgres:postgres@localhost:55432/dev`

Both Next.js apps bind to `0.0.0.0` in their npm scripts so they can be reached
through a local browser, an SSH tunnel, or the host gateway used by
NemoClaw/OpenShell.

From the GX10 desktop or a VS Code forwarded port, open:

```text
http://localhost:3000
```

If your browser is on another machine, `localhost` means that other machine, not
the GX10. Use an SSH tunnel instead:

```bash
ssh -L 3000:localhost:3000 -L 3001:localhost:3001 asus@<gx10-host>
```

Then open `http://localhost:3000` in that browser.

Inside the NemoClaw sandbox, `localhost` is the sandbox container. Host services
must use `host.openshell.internal`:

```text
http://host.openshell.internal:3000
http://host.openshell.internal:3001
```

The WebApp exposes the resolved paths at:

```text
http://localhost:3000/api/access-path
```

## Demo Accounts

WebApp seed accounts:

| Account | Email | Password | Purpose |
| --- | --- | --- | --- |
| Airbnb Host | `airbnb@revnest.ai` | `demo` | Airbnb property pricing flow |
| Hotel Operator | `hotel@revnest.ai` | `demo` | Dream Inn hotel room-type flow |

MockHotel seed account:

| Username | Password |
| --- | --- |
| `manager` | `password123` |

## Prerequisites

- Node.js and npm compatible with Next.js 16.
- Python 3.10 or newer.
- Docker and Docker Compose.
- PostgreSQL client tools are useful for debugging, but not required for the
  basic WebApp flow.
- API keys in `Claw/.env` when using external market-data tools.

The Claw database compose file attaches to an external Docker network named
`openshell-docker`. Create it once if it does not exist:

```bash
docker network create openshell-docker
```

If the network already exists, Docker will report that and you can continue.

## First-Time Setup

Run these commands from the repo root.

Install JavaScript dependencies:

```bash
npm --prefix WebApp install
npm --prefix MockHotel install
```

Install Python dependencies for Claw:

```bash
python3 -m venv Claw/.venv
Claw/.venv/bin/pip install -r Claw/requirements.txt
```

Start the dashboard database:

```bash
docker compose -f Claw/data/docker-compose.yml up -d
```

Start MockHotel's database:

```bash
docker compose -f MockHotel/docker-compose.yml up -d postgres
```

Start WebApp:

```bash
npm --prefix WebApp run dev
```

Start MockHotel in a second terminal:

```bash
npm --prefix MockHotel run dev
```

Open `http://localhost:3000` and sign in with one of the WebApp demo accounts.

## Environment Variables

The default local values are intentionally simple. Add `.env.local` files only
when you need to override them.

Useful WebApp variables:

```text
DATABASE_URL=postgres://postgres:postgres@localhost:55434/dev
MOCKHOTEL_DATABASE_URL=postgres://postgres:postgres@localhost:55432/dev
REVNEST_SESSION_SECRET=<local-session-secret>
REVNEST_WEBAPP_PORT=3000
MOCKHOTEL_PORT=3001
MOCKHOTEL_HOST_URL=http://localhost:3001
MOCKHOTEL_SANDBOX_URL=http://host.openshell.internal:3001
```

Useful MockHotel variables:

```text
DATABASE_URL=postgres://postgres:postgres@localhost:55432/dev
SESSION_SECRET=mock-hotel-local-secret
MOCKHOTEL_AGENT_TOKEN=<shared-read-token>
```

Useful Claw variables live in `Claw/.env`:

```text
CLAW_DATABASE_URL=postgres://postgres:postgres@localhost:55434/dev
SERPAPI_API_KEY=<optional>
TAVILY_API_KEY=<optional>
TICKETMASTER_API_KEY=<optional>
MOCKHOTEL_AGENT_TOKEN=<same-shared-read-token>
REVNEST_NEMOCLAW_SANDBOX=my-assistant
```

Do not paste API keys into prompts or commit them to the repository.

## Common Workflows

### Hotel Batch Pricing

1. Sign in to WebApp as `hotel@revnest.ai`.
2. Open the hotel home dashboard.
3. Click `Run Revy`.
4. WebApp calls `/api/agent-runs` with `propertyType=hotel` and
   `hotelScope=all-room-types`.
5. `Claw/tools/run_pricing_agent.py` prices every hotel room type for the
   account.
6. Forecast prices and Revy conversation summaries are written to the Claw
   database.
7. Material hotel PMS changes become pending tasks.
8. A human accepts pending tasks in WebApp before MockHotel prices are updated.

Equivalent CLI command:

```bash
cd Claw
python3 tools/run_pricing_agent.py \
  --account-id "00000000-0000-0000-0000-000000000103" \
  --property-type hotel \
  --hotel-scope all-room-types
```

### Airbnb Pricing

1. Sign in to WebApp as `airbnb@revnest.ai`.
2. Add or select a property.
3. Run Revy for the property or ask Revy about a price point.
4. WebApp starts a property-scoped agent run.
5. Revy writes forecast prices and a conversation summary back to PostgreSQL.

Example CLI command:

```bash
cd Claw
python3 tools/run_pricing_agent.py \
  --account-id "00000000-0000-0000-0000-000000000102" \
  --property-type airbnb \
  --property-id airbnb-1163080444550698185 \
  --my-place "https://www.airbnb.com/rooms/1163080444550698185" \
  --min-price 80 \
  --max-price 260 \
  --pricing-horizon 3
```

### MockHotel PMS

Open `http://localhost:3001` and sign in as `manager`. Use this app to inspect
the PMS side of the hotel demo. In the safe demo path, Revy should not directly
mutate MockHotel prices. WebApp's human approval flow owns live PMS sync.

## Runtime Split

For the hackathon demo, keep the runtime split deliberately simple:

- Hotel / MockHotel Safe PMS path: run through NemoClaw `my-assistant` with
  `revnest-safe-pms` active. This is the primary live path for judging because
  it proves policy-enforced safety.
- Airbnb external-web path: run through host OpenClaw. Airbnb browsing is useful
  as an extension, but it is not the primary NemoClaw safety demo because the
  current sandbox network/proxy path can block Airbnb.

`Claw/tools/run_pricing_agent.py` defaults to `--runtime-mode split-demo`, which
means `property_type=hotel` uses NemoClaw and `property_type=airbnb` uses host
OpenClaw. Override explicitly when needed:

```bash
python3 Claw/tools/run_pricing_agent.py --runtime-mode nemoclaw ...
python3 Claw/tools/run_pricing_agent.py --runtime-mode host-openclaw ...
```

For experimental Airbnb-in-NemoClaw browser reads, apply the project
browser-read policy before running the workflow:

```bash
/home/asus/revnest/Claw/nemoclaw/apply_airbnb_browser_access.sh my-assistant
```

This allows the sandbox browser to read Airbnb listing pages and Airbnb static
assets through OpenShell without opening unrestricted outbound internet access.
The script also configures Chromium to use the OpenShell proxy, pins the few
Airbnb hostnames needed by OpenClaw's navigation guard, and restarts the
sandbox browser.

## Data Flow

```text
WebApp UI
  -> /api/agent-runs
  -> WebApp/lib/agentRunStore.js
  -> Claw/tools/run_pricing_agent.py
  -> Claw tools and skills
  -> Claw PostgreSQL tables
  -> WebApp dashboard, Revy history, pending tasks, price logs
  -> human approval
  -> MockHotel PMS
```

Core Claw tables:

- `account` - WebApp demo accounts.
- `property` - Airbnb properties and hotel room types.
- `property_price` - forecast/current price rows shown in WebApp.
- `pricing_record` - pending tasks, price logs, and durable reasoning steps.
- `revy_conversation` - Revy final messages and history.
- `hotel_home_dashboard` - hotel dashboard aggregate state.
- `market_data_summary` - retrieved market data by run and source.

Core MockHotel tables:

- `account` - PMS users.
- `room_type` - Dream Inn room types.
- `room_type_price` - live PMS room-type prices by stay date.

## Reseeding Local Databases

Local Docker volumes persist data. If you change seed SQL and need a fresh local
database, reset only the local demo volumes:

```bash
docker compose -f Claw/data/docker-compose.yml down -v
docker compose -f Claw/data/docker-compose.yml up -d
```

For MockHotel:

```bash
docker compose -f MockHotel/docker-compose.yml down -v
docker compose -f MockHotel/docker-compose.yml up -d postgres
```

This deletes local demo data for that service.

## Validation Commands

WebApp:

```bash
npm --prefix WebApp run lint
npm --prefix WebApp run build
```

MockHotel:

```bash
npm --prefix MockHotel run lint
npm --prefix MockHotel run build
```

Claw smoke tests:

```bash
python3 Claw/tests/run_strategy_rag_gate_tests.py
python3 Claw/tests/run_hotel_seed_consistency_tests.py
python3 Claw/tests/run_safe_pms_evidence_chain_demo.py
python3 Claw/tests/run_demo1_airbnb_e2e.py
python3 Claw/tests/run_demo2_hotel_e2e.py
```

The Demo1 and Demo2 e2e tests start a temporary WebApp production server and use
deterministic agent fixtures by default. Demo1 verifies Airbnb login, default
add-property data, OpenClaw run launch, completed run status, and the new
property appearing in My Properties. Demo2 verifies the hotel batch pricing
flow, generated pending task, Discord notification, Discord prompt approval
routing through WebApp Accept, and MockHotel database update only after approval.

To exercise real OpenClaw/NemoClaw runs instead, start WebApp yourself and run:

```bash
python3 Claw/tests/run_demo1_airbnb_e2e.py --live-agent --no-start-webapp --webapp-url http://localhost:3000 --timeout-seconds 1800
python3 Claw/tests/run_demo2_hotel_e2e.py --live-agent --no-start-webapp --webapp-url http://localhost:3000 --timeout-seconds 1800 --skip-discord-check
```

The default Demo2 fixture run injects a local `DISCORD_WEBHOOK_URL` capture
server. For externally managed live-agent runs, start WebApp with your own
Discord test webhook if you want to inspect the live notification path.

Useful tool checks:

```bash
python3 Claw/tools/run_pricing_agent.py --help
python3 Claw/tools/run_parallel_market_data.py --help
python3 Claw/tools/revpar_estimate.py --help
```

## Troubleshooting

### Port Already In Use

WebApp uses port `3000` and MockHotel uses port `3001`. Stop the existing
process, or run the relevant Next.js app on a different port by adjusting its
npm script or environment.

### WebApp Cannot Log In

Make sure the Claw database is running on port `55434` and has been initialized
from `Claw/data/sql/schema.sql` and `Claw/data/sql/data.sql`.

### Hotel Room Types Do Not Appear

Sign in with `hotel@revnest.ai`, then confirm the Claw `property` table contains
rows where `data->>'propertyType' = 'Hotel Room Type'`. If you recently edited
seed SQL, reseed the Claw database.

### Agent Run Starts But UI Does Not Update

Check the run log under `Claw/runs/`. WebApp reads JSONL progress events from
the run log and final database records from PostgreSQL. Confirm the Python
runner can write to `Claw/runs/` and connect to `CLAW_DATABASE_URL`.

### MockHotel Agent API Returns 401 Or 503

Set the same `MOCKHOTEL_AGENT_TOKEN` in MockHotel and Claw. The read-only agent
API requires a bearer token when fetching current PMS prices.

## Additional Docs

- `MockHotel/README.md` - MockHotel-specific setup.
- `Claw/tools/README.md` - pricing tool commands and data-source notes.
- `Claw/BOOTSTRAP.md` - Revy runtime operating contract.
- `Claw/nemoclaw/SAFE_PMS_APPROVAL_DEMO.md` - safe PMS demo notes.
- `Claw/nemoclaw/revnest-safe-pms.yaml` - NemoClaw policy for MockHotel safety.
