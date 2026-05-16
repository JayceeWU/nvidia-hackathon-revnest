#!/usr/bin/env bash
set -euo pipefail
cd /home/asus/revnest/Claw
python3 tools/run_pricing_agent.py --clear-log --account-id 00000000-0000-0000-0000-000000000103 --property-type hotel --hotel-scope all-room-types --runtime-mode nemoclaw --session-id hotel-full-evidence-20260516T145841Z --run-id hotel-full-evidence-20260516T145841Z --thinking medium --verbose on --timeout-seconds 1800
