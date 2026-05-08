#!/usr/bin/env bash
# Idempotent install for tesla-solar-control on a fresh Linux host (Podman).
#
# Assumes:
#   - Repo checkout path is this script's parent directory (override with SOLAR_CONTROL_REPO).
#   - Podman installed.
#   - tesla-control at /usr/local/bin/tesla-control (build from Tesla vehicle-command).
#   - private.pem + cache.json in repo root.
#
# What it does (safe to re-run):
#   1. Seeds pi-zero-ble-relay/config.env from template if missing.
#   2. Builds podman image: tesla-solar-control:latest
#   3. Installs systemd units + maintenance timer.
#   4. Installs maintenance script to /usr/local/sbin/.

set -euo pipefail

REPO="${SOLAR_CONTROL_REPO:-$(cd "$(dirname "$0")/.." && pwd)}"
CONFIG_ENV="$REPO/pi-zero-ble-relay/config.env"
SYSTEMD=/etc/systemd/system
SBIN=/usr/local/sbin

cd "$REPO"

# ── 0. precondition checks ─────────────────────────────────────────────────
if [[ ! -x /usr/local/bin/tesla-control ]]; then
    echo "ERROR: /usr/local/bin/tesla-control missing. Build vehicle-command first." >&2
    exit 1
fi
if [[ ! -f "$REPO/private.pem" ]]; then
    echo "ERROR: $REPO/private.pem missing." >&2
    exit 1
fi

# ── 1. config.env ──────────────────────────────────────────────────────────
if [[ ! -f "$CONFIG_ENV" ]]; then
    echo "==> Creating $CONFIG_ENV from template (FILL IN VALUES MANUALLY)"
    install -d "$REPO/pi-zero-ble-relay"
    cp "$REPO/deploy/config.env.example" "$CONFIG_ENV"
    chmod 600 "$CONFIG_ENV"
    echo "    >>> EDIT $CONFIG_ENV (TESLA_VIN, TESLA_EMAIL, API_KEY, BLE_RELAY_HOST), then re-run <<<"
    exit 1
else
    echo "==> $CONFIG_ENV exists, leaving alone"
fi

# ── 2. build podman image ──────────────────────────────────────────────────
echo "==> Building podman image: tesla-solar-control:latest"
sudo podman build -t tesla-solar-control .

# ── 3. systemd units ───────────────────────────────────────────────────────
echo "==> Installing solar-charger.service (EDIT paths inside unit to match REPO=$REPO)"
sudo install -m 644 "$REPO/deploy/solar-charger.service" "$SYSTEMD/solar-charger.service"

echo "==> Installing solar-charger-maintenance.service + .timer"
sudo install -m 644 "$REPO/deploy/solar-charger-maintenance.service" "$SYSTEMD/solar-charger-maintenance.service"
sudo install -m 644 "$REPO/deploy/solar-charger-maintenance.timer"   "$SYSTEMD/solar-charger-maintenance.timer"

# ── 4. maintenance script ──────────────────────────────────────────────────
echo "==> Installing maintenance check script to $SBIN"
sudo install -m 755 -o root -g root \
    "$REPO/deploy/solar_charger_maintenance_check.sh" \
    "$SBIN/solar_charger_maintenance_check.sh"

sudo install -d -m 755 -o root -g root /var/lib/solar-charger/alerts

# ── 5. start services ──────────────────────────────────────────────────────
sudo systemctl daemon-reload
echo "==> Enabling + starting solar-charger.service"
sudo systemctl enable --now solar-charger.service
echo "==> Enabling + starting solar-charger-maintenance.timer"
sudo systemctl enable --now solar-charger-maintenance.timer
sleep 3

# ── 6. status ──────────────────────────────────────────────────────────────
echo ""
echo "==> Status:"
sudo systemctl --no-pager --lines=0 status solar-charger.service || true

cat <<EOF

==> Done.

Edit $SYSTEMD/solar-charger.service if your repo is not installed at /opt/tesla-solar-control.

Next steps:
  1. Verify BLE relay: curl -H "X-API-Key: ..." http://<pi-zero-ip>:5003/health
  2. Optional: sudo cp $REPO/deploy/maintenance.env.example /etc/default/solar-charger-maintenance
  3. Optional cron — see deploy/crontab.example
EOF
