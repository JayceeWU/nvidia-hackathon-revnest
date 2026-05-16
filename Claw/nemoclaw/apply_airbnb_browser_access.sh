#!/usr/bin/env bash
set -euo pipefail

SANDBOX_NAME="${1:-my-assistant}"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
POLICY_FILE="${SCRIPT_DIR}/revnest-airbnb-browser.yaml"

sudo_run() {
  if [[ -n "${REVNEST_SUDO_PASSWORD:-}" ]]; then
    printf '%s\n' "${REVNEST_SUDO_PASSWORD}" | sudo -S "$@"
  else
    sudo "$@"
  fi
}

resolve_ipv4() {
  local host="$1"
  getent ahostsv4 "${host}" | awk '{ print $1; exit }'
}

require_ipv4() {
  local host="$1"
  local ip
  ip="$(resolve_ipv4 "${host}")"
  if [[ -z "${ip}" ]]; then
    echo "Could not resolve ${host} on the host." >&2
    exit 1
  fi
  printf '%s' "${ip}"
}

echo "[airbnb] applying NemoClaw policy preset"
if ! nemoclaw "${SANDBOX_NAME}" policy-add revnest-airbnb-browser --yes >/tmp/revnest-airbnb-policy.log 2>&1; then
  if grep -q "already applied" /tmp/revnest-airbnb-policy.log; then
    cat /tmp/revnest-airbnb-policy.log
  else
    nemoclaw "${SANDBOX_NAME}" policy-add --from-file "${POLICY_FILE}" --yes
  fi
else
  cat /tmp/revnest-airbnb-policy.log
fi
if ! nemoclaw "${SANDBOX_NAME}" policy-list | grep -q "revnest-airbnb-browser"; then
  nemoclaw "${SANDBOX_NAME}" policy-add --from-file "${POLICY_FILE}" --yes
fi

echo "[airbnb] locating OpenShell sandbox container"
CONTAINER_ID="$(sudo_run docker ps --format '{{.ID}} {{.Names}}' \
  | awk -v prefix="openshell-${SANDBOX_NAME}-" '$2 ~ "^" prefix { print $1; exit }')"
if [[ -z "${CONTAINER_ID}" ]]; then
  echo "Could not find an openshell container for sandbox ${SANDBOX_NAME}." >&2
  exit 1
fi

AIRBNB_IP="$(require_ipv4 airbnb.com)"
WWW_IP="$(require_ipv4 www.airbnb.com)"
MUSCACHE_IP="$(require_ipv4 a0.muscache.com)"

echo "[airbnb] pinning host DNS entries for OpenClaw browser navigation guard"
HOST_BLOCK_FILE="$(mktemp)"
trap 'rm -f "${HOST_BLOCK_FILE}"' EXIT
{
  echo "# BEGIN revnest-airbnb-browser DNS pin"
  echo "${AIRBNB_IP} airbnb.com"
  echo "${WWW_IP} www.airbnb.com san.airbnb.com.edgekey.net"
  echo "${MUSCACHE_IP} a0.muscache.com a1.muscache.com a2.muscache.com muscache.production.global.product.origins.airbnb.net"
  echo "# END revnest-airbnb-browser DNS pin"
} > "${HOST_BLOCK_FILE}"
sudo_run docker cp "${HOST_BLOCK_FILE}" "${CONTAINER_ID}:/tmp/revnest-airbnb-hosts"
sudo_run docker exec -u root "${CONTAINER_ID}" /bin/bash -lc \
  'tmp="$(mktemp)"; awk '"'"'
    /# BEGIN revnest-airbnb-browser DNS pin/ { skip=1; next }
    /# END revnest-airbnb-browser DNS pin/ { skip=0; next }
    /revnest-airbnb-browser DNS pin/ { next }
    /(^|[[:space:]])(airbnb\.com|www\.airbnb\.com|a0\.muscache\.com|a1\.muscache\.com|a2\.muscache\.com)([[:space:]]|$)/ { next }
    !skip { print }
  '"'"' /etc/hosts > "${tmp}"; printf "\n" >> "${tmp}"; cat /tmp/revnest-airbnb-hosts >> "${tmp}"; cat "${tmp}" > /etc/hosts'

echo "[airbnb] configuring OpenClaw browser to use the OpenShell proxy"
openshell sandbox exec -n "${SANDBOX_NAME}" --timeout 60 --no-tty -- /bin/bash -lc \
  'node -e "const fs=require(\"fs\");const p=\"/sandbox/.openclaw/openclaw.json\";const c=JSON.parse(fs.readFileSync(p,\"utf8\"));c.browser||={};c.browser.enabled=true;c.browser.executablePath ||= \"/usr/bin/chromium\";c.browser.headless=true;c.browser.noSandbox=true;const args=new Set(c.browser.extraArgs||[]);for(const a of [\"--disable-dev-shm-usage\",\"--proxy-server=http://10.200.0.1:3128\",\"--proxy-bypass-list=localhost;127.0.0.1;::1;10.200.0.1\",\"--ignore-certificate-errors\"]) args.add(a);c.browser.extraArgs=Array.from(args);c.browser.ssrfPolicy={dangerouslyAllowPrivateNetwork:true};fs.writeFileSync(p,JSON.stringify(c,null,2)+\"\\n\");console.log(JSON.stringify(c.browser,null,2));"; openclaw browser stop >/tmp/browser-stop.log 2>&1 || true; pgrep -x chromium | xargs -r kill -9 || true'

echo "[airbnb] done. Verify with:"
echo "  openshell sandbox exec -n ${SANDBOX_NAME} -- openclaw browser --browser-profile openclaw open https://www.airbnb.com"
