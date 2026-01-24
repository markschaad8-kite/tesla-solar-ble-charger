# Tesla Solar Charger (BLE + TWC Edition) - v4.0.6

Automated Tesla charging control script running on Raspberry Pi. This system adjusts charging amperage in real-time based on solar excess, using local Bluetooth (BLE) control to avoid Tesla API rate limits and wake issues.

## ⚡ Core Features (v4.0.6)

* **Solar Tracking:** Monitors Enphase Envoy data to adjust vehicle charging amps (1A increments) to match solar export.
* **BLE-First Control:** Uses `tesla-control` (Bluetooth Low Energy) for all commands (Start/Stop/Set Amps). This is faster than the HTTP API and prevents "waking" the car unnecessarily.
* **TWC Integration:** Polls the Tesla Wall Connector (Gen 2/3) API locally to detect "Plugged In" state instantly.
* **Smart Disconnect:** Automatically resets the car to **MAX_AMPS (48A)** when unplugged.
    * *Edge Case Handling:* If BLE is on cooldown when you unplug, the system flags a "pending normalization" and forces the reset immediately upon the next connection.
* **Zero-Grid Drain:** "Night Mode" automatically stops charging when solar production drops below 100W for 10 minutes.
* **Emergency Mode:** If battery drops below 50%, the system overrides solar rules and charges at full speed (48A) until the target is reached.
* **BLE Relay Support (v4.0.5):** Optional Pi Zero proxy for improved BLE range.
* **Fast MANUAL Wake (v4.0.6):** When MANUAL mode is enabled and the vehicle is asleep, immediately wakes and retries BLE (~30s vs ~3min old behavior).

## 🛠️ Technical Architecture

* **Hardware:** Raspberry Pi 2/3/4/5 (requires Bluetooth & WiFi/Ethernet).
* **Software Stack:** Python 3, Docker (Podman), Systemd.
* **Refactor (v4):** Uses a consolidated `ChargerState` object for robust tracking of charging history, BLE backoff timers, and connection state.

## 📋 Requirements

* **Tesla Wall Connector** (Must be on local network)
* **Enphase Envoy** (or compatible solar gateway with local API)
* `tesla-control` binary installed
* Tesla Auth Token (`cache.json`) & Private Key (`private.pem`)

## 🚀 Setup

1.  **Sanitize:** Update `CONFIG` section in `solar_charger.py` with your VIN, Email, and IP addresses.
2.  **Auth:** Place your `private.pem` and `cache.json` in the application directory.
3.  **Deploy:** Run via Systemd or Docker.

## 🔌 Dashboard API Contract

The charger expects a dashboard/controller to provide these HTTP endpoints. You can implement these using Home Assistant, Node-RED, Flask, or any web framework.

### Required Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/envoy_data` | GET | Returns solar production data |
| `/api/charging/config` | GET | Returns current charging mode |
| `/api/set_charger_status` | POST | Receives status updates from charger |
| `/api/twc/vehicle_connected` | GET | Returns TWC plug state |

### Endpoint Details

**GET `/api/envoy_data`** - Solar production data
```json
{
  "production_watts": 5200,
  "excess_watts": 3100
}
```

**GET `/api/charging/config`** - Current mode setting
```json
{
  "mode": "SOLAR"
}
```
Valid modes: `SOLAR` (charge from excess only), `MANUAL` (charge at max amps)

**POST `/api/set_charger_status`** - Status update from charger
The charger POSTs its current state every loop. Your dashboard can display this:
```json
{
  "mode": "SOLAR",
  "amps": 24,
  "target_amps": 26,
  "battery": 65,
  "battery_age_sec": 120,
  "excess_watts": 6200,
  "production_watts": 7100,
  "state": "Charging",
  "timestamp": "2025-01-24T14:30:00",
  "ble_fail_count": 0,
  "ble_backoff_remaining": 0,
  "grid_charge_warning_amps": null
}
```

**GET `/api/twc/vehicle_connected`** - TWC connection state
```json
{
  "connected": true,
  "data_age_seconds": 5
}
```

### Optional: Mode Control

To switch between SOLAR and MANUAL mode from a UI, implement:

**POST `/api/charging/mode`** - Set charging mode
```json
{"mode": "MANUAL"}
```
Response:
```json
{"status": "success", "new_mode": "MANUAL"}
```

This writes to a config file that `/api/charging/config` reads from.

### Optional: BLE Relay

If using a Pi Zero as a BLE relay (for improved range), the charger calls:

**POST `http://<relay-host>:5003/ble/command`**
```json
{"command": "charging-set-amps", "args": ["24"]}
```

## ⚠️ Disclaimer
Use at your own risk. This script interfaces directly with vehicle charging hardware and high-voltage systems.
