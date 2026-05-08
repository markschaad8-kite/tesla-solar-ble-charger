#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CACHE="${PROJECT_DIR}/cache.json"
KEY="${PROJECT_DIR}/private.pem"
TESLA_CTL="/usr/local/bin/tesla-control"

JSON_MODE=false
if [[ "${1:-}" == "--json" ]]; then
  JSON_MODE=true
fi

status="pass"
reason="ok"

fail() {
  status="fail"
  reason="$1"
}

# -------------------------------
# CHECKS
# -------------------------------
check_project_dir() {
  [[ -d "$PROJECT_DIR" ]] || fail "project_dir_missing"
}

check_required_files() {
  for f in Dockerfile requirements.txt solar_charger_twc.py cache.json private.pem; do
    [[ -f "$PROJECT_DIR/$f" ]] || fail "missing_file:$f"
  done
}

check_auth_cache() {
  if ! grep -q '"access_token"' "$CACHE" || ! grep -q '"refresh_token"' "$CACHE"; then
    fail "auth_tokens_missing"
  fi
}

check_tesla_control() {
  [[ -x "$TESLA_CTL" ]] || fail "tesla_control_missing"
}

check_relay_host_runtime() {
  # Validate the effective systemd unit is using a static IP for BLE_RELAY_HOST.
  local unit
  unit="$(systemctl cat solar-charger.service 2>/dev/null || true)"
  if [[ -z "$unit" ]]; then
    fail "systemd_unit_unreadable"
    return
  fi

  local relay_ip
  relay_ip="$(printf '%s\n' "$unit" | grep -Eo 'BLE_RELAY_HOST=[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+' | head -n1 | cut -d= -f2 || true)"
  if [[ -z "$relay_ip" ]]; then
    fail "ble_relay_host_missing_or_non_ip"
    return
  fi
}

check_permissions() {
  cache_perm="$(stat -c '%a' "$CACHE" 2>/dev/null || echo unknown)"
  key_perm="$(stat -c '%a' "$KEY" 2>/dev/null || echo unknown)"
}

# -------------------------------
# RUN CHECKS
# -------------------------------
check_project_dir
check_required_files
check_auth_cache
check_tesla_control
check_relay_host_runtime
check_permissions

# -------------------------------
# OUTPUT
# -------------------------------
if $JSON_MODE; then
  cat <<EOF
{
  "project_dir": "$PROJECT_DIR",
  "status": "$status",
  "reason": "$reason",
  "checks": {
    "project_dir": "$( [[ -d "$PROJECT_DIR" ]] && echo ok || echo fail )",
    "cache_json": "$( [[ -f "$CACHE" ]] && echo ok || echo fail )",
    "private_pem": "$( [[ -f "$KEY" ]] && echo ok || echo fail )",
    "auth_tokens": "$( grep -q '"access_token"' "$CACHE" && echo ok || echo fail )",
    "tesla_control": "$( [[ -x "$TESLA_CTL" ]] && echo ok || echo fail )",
    "ble_relay_host_runtime": "$( systemctl cat solar-charger.service 2>/dev/null | grep -Eq 'BLE_RELAY_HOST=[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+' && echo ok || echo fail )"
  },
  "permissions": {
    "cache_json": "$cache_perm",
    "private_pem": "$key_perm"
  }
}
EOF
else
  echo "=== Solar Charger Preflight ==="
  echo "Project dir: $PROJECT_DIR"
  echo
  echo "Auth cache: $(grep -q '"access_token"' "$CACHE" && echo OK || echo FAIL)"
  echo "private.pem perms: $key_perm (recommended 600)"
  echo "cache.json perms: $cache_perm (recommended 600)"
  echo "tesla-control: $( [[ -x "$TESLA_CTL" ]] && echo OK || echo MISSING )"
  echo "BLE relay host runtime: $( systemctl cat solar-charger.service 2>/dev/null | grep -Eq 'BLE_RELAY_HOST=[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+' && echo OK || echo FAIL )"
  echo
  echo "RESULT: $status"
  echo "REASON: $reason"
fi

[[ "$status" == "pass" ]] && exit 0 || exit 1
