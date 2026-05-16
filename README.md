# RevNest Local Access Paths

RevNest runs three local surfaces:

- WebApp dashboard: `http://localhost:3000`
- MockHotel PMS: `http://localhost:3001`
- Claw PostgreSQL: `postgres://postgres:postgres@localhost:55434/dev`

Both Next.js apps bind to `0.0.0.0` in their npm scripts so they can be reached
through a local browser, an SSH tunnel, or the host gateway used by
NemoClaw/OpenShell.

## Browser Access

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

## NemoClaw/OpenShell Access

Inside the NemoClaw sandbox, `localhost` is the sandbox container. Host services
must use `host.openshell.internal`:

```text
http://host.openshell.internal:3000
http://host.openshell.internal:3001
```

The pricing agent should only use the MockHotel read-only agent API from the
sandbox. It must not call WebApp accept APIs, MockHotel write APIs, or direct
MockHotel database writes. Human approval happens from the WebApp browser
session.

## Demo Runtime Split

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

## Health Check

The WebApp exposes the resolved paths at:

```text
http://localhost:3000/api/access-path
```
