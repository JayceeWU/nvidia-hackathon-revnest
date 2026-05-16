#!/usr/bin/env bash
set -euo pipefail

SANDBOX_NAME="${1:-${REVNEST_NEMOCLAW_SANDBOX:-revnest-judge}}"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
POLICY_FILE="${SCRIPT_DIR}/revnest-judge-minimal.yaml"
EVIDENCE_DIR="${SCRIPT_DIR}/evidence/logs"
POLICY_LIST_LOG="${EVIDENCE_DIR}/20_judge_minimal_policy_list.log"
FULL_POLICY_LOG="${EVIDENCE_DIR}/21_judge_minimal_openshell_policy_full.yaml"
SHIELDS_LOG="${EVIDENCE_DIR}/22_judge_minimal_shields_status.log"
SANDBOX_STATUS_LOG="${EVIDENCE_DIR}/23_judge_minimal_sandbox_status.log"

NON_JUDGE_POLICIES=(
  brave
  brew
  discord
  github
  huggingface
  jira
  local-inference
  managed-inference
  npm
  nvidia
  openclaw-api
  openclaw-docs
  outlook
  pypi
  revnest-airbnb-browser
  slack
  telegram
  wechat
)

FORBIDDEN_ACTIVE_POLICY_NAMES=(
  airbnb
  npm
  pypi
  brew
  discord
  huggingface
  slack
  telegram
)

FORBIDDEN_FULL_POLICY_KEYS=(
  brave
  brew
  clawhub
  discord
  github
  huggingface
  jira
  npm_registry
  npm_yarn
  openclaw_api
  openclaw_docs
  pypi
  revnest_airbnb_browser
  slack
  telegram
  wechat
)

mkdir -p "${EVIDENCE_DIR}"

echo "[judge-minimal] sandbox=${SANDBOX_NAME}"
echo "[judge-minimal] policy=${POLICY_FILE}"
echo "[judge-minimal] recommendation: use a fresh sandbox named 'revnest-judge' for final judging."

if ! command -v nemoclaw >/dev/null 2>&1; then
  echo "nemoclaw was not found on PATH." >&2
  exit 127
fi
if ! command -v openshell >/dev/null 2>&1; then
  echo "openshell was not found on PATH." >&2
  exit 127
fi
if [[ ! -f "${POLICY_FILE}" ]]; then
  echo "Missing judge policy file: ${POLICY_FILE}" >&2
  exit 1
fi

echo "[judge-minimal] removing known non-judge policies if present"
for policy in "${NON_JUDGE_POLICIES[@]}"; do
  if nemoclaw "${SANDBOX_NAME}" policy-remove "${policy}" --yes >/tmp/revnest-judge-policy-remove.log 2>&1; then
    sed "s/^/[judge-minimal] removed ${policy}: /" /tmp/revnest-judge-policy-remove.log
  else
    if grep -Eqi "not.*(applied|found|active|installed)|unknown|no policy" /tmp/revnest-judge-policy-remove.log; then
      sed "s/^/[judge-minimal] ${policy}: /" /tmp/revnest-judge-policy-remove.log || true
    else
      cat /tmp/revnest-judge-policy-remove.log
      exit 1
    fi
  fi
done

echo "[judge-minimal] applying revnest-judge-minimal policy"
if ! nemoclaw "${SANDBOX_NAME}" policy-add --from-file "${POLICY_FILE}" --yes >/tmp/revnest-judge-policy-add.log 2>&1; then
  if grep -Eqi "already|exists" /tmp/revnest-judge-policy-add.log; then
    cat /tmp/revnest-judge-policy-add.log
  else
    cat /tmp/revnest-judge-policy-add.log
    exit 1
  fi
else
  cat /tmp/revnest-judge-policy-add.log
fi

echo "[judge-minimal] enabling shields"
nemoclaw "${SANDBOX_NAME}" shields up

echo "[judge-minimal] capturing evidence"
nemoclaw "${SANDBOX_NAME}" shields status | tee "${SHIELDS_LOG}"
nemoclaw "${SANDBOX_NAME}" status | tee "${SANDBOX_STATUS_LOG}" >/dev/null
nemoclaw "${SANDBOX_NAME}" policy-list | tee "${POLICY_LIST_LOG}" >/dev/null
openshell policy get --full "${SANDBOX_NAME}" | tee "${FULL_POLICY_LOG}" >/dev/null

echo "[judge-minimal] verifying minimal policy evidence"
grep -q "Shields: UP" "${SHIELDS_LOG}"
grep -q "revnest-judge-minimal" "${POLICY_LIST_LOG}"
grep -q "revnest_judge_mockhotel_readonly" "${FULL_POLICY_LOG}"
grep -q "revnest_judge_local_inference" "${FULL_POLICY_LOG}"
grep -q "revnest_judge_nvidia_inference" "${FULL_POLICY_LOG}"

python3 - "${POLICY_LIST_LOG}" "${FORBIDDEN_ACTIVE_POLICY_NAMES[@]}" <<'PY_POLICY'
import pathlib
import sys

log_path = pathlib.Path(sys.argv[1])
forbidden = [item.lower() for item in sys.argv[2:]]
bad = []
unexpected = []
for line in log_path.read_text(encoding="utf-8").splitlines():
    normalized = line.strip().lower()
    if not normalized:
        continue
    active = "active" in normalized or normalized.startswith("*") or normalized.startswith("[x]")
    if not active:
        # NemoClaw currently marks active policies with a filled circle. Avoid
        # embedding that glyph in the shell logic by checking by code point.
        active = bool(normalized) and ord(normalized[0]) == 0x25CF
    if active and any(name in normalized for name in forbidden):
        bad.append(line)
    if active and "revnest-judge-minimal" not in normalized:
        unexpected.append(line)
if bad:
    print("Forbidden active policies remain in judge sandbox:", file=sys.stderr)
    for line in bad:
        print(f"  {line}", file=sys.stderr)
if unexpected:
    print("Unexpected active policies remain in judge sandbox:", file=sys.stderr)
    for line in unexpected:
        print(f"  {line}", file=sys.stderr)
if bad or unexpected:
    raise SystemExit(1)
PY_POLICY

for forbidden in "${FORBIDDEN_FULL_POLICY_KEYS[@]}"; do
  if grep -Eiq "^[[:space:]]*${forbidden}:" "${FULL_POLICY_LOG}"; then
    echo "Forbidden network policy '${forbidden}' remains in ${FULL_POLICY_LOG}" >&2
    exit 1
  fi
done

echo "[judge-minimal] complete: only the judge policy should be active for the NemoClaw story"
echo "[judge-minimal] key evidence:"
echo "  ${POLICY_LIST_LOG}"
echo "  ${FULL_POLICY_LOG}"
echo "  ${SHIELDS_LOG}"
