#!/usr/bin/env bash
# Solar Charger health check — emails when something goes wrong.
# Installed at /usr/local/sbin/solar_charger_maintenance_check.sh by
# deploy/install.sh; invoked every 15 min by solar-charger-maintenance.timer.
#
# Optional: /etc/default/solar-charger-maintenance (see deploy/maintenance.env.example)

set -euo pipefail

TO="${SCC_ALERT_TO:-}"
FROM="${SCC_ALERT_FROM:-root@$(hostname -f 2>/dev/null || hostname)}"
ENVOY_URL="${SCC_ENVOY_DATA_URL:-http://127.0.0.1:8080/api/envoy_data}"

HOST="$(hostname -f 2>/dev/null || hostname)"
NOW="$(date)"
SUBJ_PREFIX="[SolarCharger][${HOST}]"

STATE_DIR="/var/lib/solar-charger/alerts"
ENV_DOWN_FLAG="${STATE_DIR}/envoy_down"

tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT

send_mail() {
  [[ -n "$TO" ]] || return 0
  printf "To: %s\nFrom: %s\nSubject: %s\n\n%s\n" \
    "$TO" "$FROM" "$1" "$2" | sendmail -t
}

# ==========================
# 1) systemd service health
# ==========================
if ! systemctl is-active --quiet solar-charger.service; then
  send_mail "${SUBJ_PREFIX} ALERT: solar-charger service stopped" \
    "solar-charger.service is NOT active on ${HOST} at ${NOW}"
fi

# ==========================
# 2) container running
# ==========================
if ! podman ps --format '{{.Names}}' | grep -qx 'solar-charger'; then
  send_mail "${SUBJ_PREFIX} ALERT: container not running" \
    "Podman container 'solar-charger' is NOT running on ${HOST} at ${NOW}"
fi

# ==========================
# 3) Dashboard / solar API check
# ==========================
if ! curl -sf --max-time 5 "$ENVOY_URL" >/dev/null; then
  if [[ ! -f "$ENV_DOWN_FLAG" ]]; then
    touch "$ENV_DOWN_FLAG"
    send_mail "${SUBJ_PREFIX} WARNING: solar dashboard unreachable" \
      "Solar data URL ${ENVOY_URL} is unreachable on ${HOST} at ${NOW}.
This alert will not repeat until the service recovers."
  fi
else
  if [[ -f "$ENV_DOWN_FLAG" ]]; then
    rm -f "$ENV_DOWN_FLAG"
    send_mail "${SUBJ_PREFIX} RECOVERY: solar dashboard reachable again" \
      "Solar data URL ${ENVOY_URL} is reachable again on ${HOST} at ${NOW}."
  fi
fi
