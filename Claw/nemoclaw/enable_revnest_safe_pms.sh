#!/usr/bin/env bash
set -euo pipefail

SANDBOX_NAME="${1:-${REVNEST_NEMOCLAW_SANDBOX:-my-assistant}}"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
POLICY_FILE="${ROOT_DIR}/nemoclaw/revnest-safe-pms.yaml"
EVIDENCE_DIR="${ROOT_DIR}/nemoclaw/evidence/logs"

mkdir -p "${EVIDENCE_DIR}"

echo "[safe-pms] sandbox=${SANDBOX_NAME}"
echo "[safe-pms] policy=${POLICY_FILE}"

if ! command -v nemoclaw >/dev/null 2>&1; then
  echo "nemoclaw was not found on PATH." >&2
  exit 127
fi
if ! command -v openshell >/dev/null 2>&1; then
  echo "openshell was not found on PATH." >&2
  exit 127
fi

echo "[safe-pms] applying revnest-safe-pms policy"
if ! nemoclaw "${SANDBOX_NAME}" policy-add revnest-safe-pms --yes >/tmp/revnest-safe-pms-policy.log 2>&1; then
  if grep -qi "already" /tmp/revnest-safe-pms-policy.log; then
    cat /tmp/revnest-safe-pms-policy.log
  else
    cat /tmp/revnest-safe-pms-policy.log
    nemoclaw "${SANDBOX_NAME}" policy-add --from-file "${POLICY_FILE}" --yes
  fi
else
  cat /tmp/revnest-safe-pms-policy.log
fi

echo "[safe-pms] enabling shields"
nemoclaw "${SANDBOX_NAME}" shields up

echo "[safe-pms] capturing status evidence"
nemoclaw "${SANDBOX_NAME}" shields status | tee "${EVIDENCE_DIR}/08_shields_status_after_lockdown.log"
nemoclaw "${SANDBOX_NAME}" status | tee "${EVIDENCE_DIR}/09_sandbox_status_after_lockdown.log" >/dev/null
nemoclaw "${SANDBOX_NAME}" policy-list | tee "${EVIDENCE_DIR}/10_policy_list_after_lockdown.log" >/dev/null
openshell policy get --full "${SANDBOX_NAME}" | tee "${EVIDENCE_DIR}/11_openshell_policy_full_after_lockdown.yaml" >/dev/null

echo "[safe-pms] verifying policy and shields"
grep -q "Shields: UP" "${EVIDENCE_DIR}/08_shields_status_after_lockdown.log"
grep -q "revnest-safe-pms" "${EVIDENCE_DIR}/10_policy_list_after_lockdown.log"
grep -q "revnest_mockhotel_readonly" "${EVIDENCE_DIR}/11_openshell_policy_full_after_lockdown.yaml"

echo "[safe-pms] complete: revnest-safe-pms is active and shields are up"
