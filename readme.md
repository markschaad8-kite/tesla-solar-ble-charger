# Tesla Solar Charger (BLE + TWC Edition) - v4.0.16-twc

Automated Tesla charging control running on Raspberry Pi. Adjusts charging amperage in real-time based on solar excess using local Bluetooth (BLE) control via a Pi Zero relay. No cloud dependency for day-to-day operation.

## Core Features

* **Solar Tracking:** Monitors Enphase Envoy data to adjust vehicle charging amps (1A increments) to match solar export. 3-sample moving average smoothing prevents cloud-cover flapping.
* **BLE-First Control:** Uses `tesla-control` (Bluetooth Low Energy) for all commands via a Pi Zero 2 W relay. Faster than the HTTP API, avoids waking the car unnecessarily, and the relay can be positioned near the vehicle independently.
* **TWC Home Detection:** Polls the Tesla Wall Connector locally to detect plug state. TWC connection is the sole authority for "at home" status (no GPS geofencing).
* **Calendar-Aware Charging (v4.0.16):** Reads Google Calendar for upcoming trips with locations. An AI assessment determines round-trip distance and recommends a battery target (80-95%). Smart timing calculates when to start charging based on departure time minus estimated charge duration.
* **80% Approval Gate (v4.0.16):** When calendar targets exceed 80%, charging pauses at 80% and waits for user approval via the dashboard (battery health protection). Auto-approves if less than 2 hours before the event.
* **Preconditioning Detection (v4.0.11):** Detects when the vehicle is preconditioning (climate prep) and skips amp adjustments to avoid interfering with the vehicle's thermal management.
* **Emergency Mode:** If battery drops below 50%, overrides all other modes and charges at full speed (48A). Monitors progress and continues past 90-minute fallback if battery is still rising.
* **Smart Disconnect:** Automatically resets the car to 48A when unplugged, so plugging back in resumes at max rate. Handles BLE cooldown edge cases with pending normalization.
* **Zero-Grid Drain:** Night mode automatically stops charging when solar production drops below 100W for 10 minutes.
* **Solar Takeover (v4.0.8):** Dashboard button to force solar control when external charging is detected.
* **Wake Escalation:** After 3 BLE failures, escalates to Tesla API wake. Separate cooldown tracking for MANUAL, SOLAR, and CALENDAR modes. Fast-wake path for MANUAL mode (~30s vs ~3min).

## Charging Modes

| Mode | Priority | Trigger | Behavior |
|------|----------|---------|----------|
| **EMERGENCY** | Highest | Battery < 50% | Charge at 48A until 80%. Continues past 90-min timeout if battery still rising. |
| **CALENDAR** | High | Active trip advisory | Charge at 48A to advisory target. Pauses at 80% if target > 80% (approval gate). |
| **CALENDAR_WAITING** | - | Advisory active, before charge_after time | Shows countdown on dashboard, falls through to SOLAR. |
| **MANUAL** | Medium | User-enabled via dashboard | Charge at configured amps regardless of solar. Wake escalation after 3 BLE fails. |
| **SOLAR** | Normal | Excess solar > 100W | Adjusts amps to match solar excess (6-48A). Hysteresis prevents micro-adjustments. |
| **NIGHT_STOP** | Low | Solar < 100W for 10 min | Stops charging, resumes at sunrise. |
| **AWAY** | - | TWC disconnected | Idle, waiting for vehicle to return home. |

## Architecture

```
Pi 5 (main controller)              Pi Zero 2 W (BLE relay)
┌─────────────────────────┐         ┌──────────────────────┐
│ solar_charger_twc.py    │  HTTP   │ ble_relay.py (:5003) │
│                         │────────>│                      │
│ Reads: localhost:8080   │         │ Executes:            │
│   (solar data, config)  │         │   tesla-control BLE  │
│ Reads: localhost:5002   │         │                      │  BLE
│   (TWC status)          │         │                      │─────> Tesla
│                         │         │ API key auth         │
│ Podman container        │         │ Flask/Waitress       │
└─────────────────────────┘         └──────────────────────┘
```

**Key design decisions:**
- Two-Pi design: control logic on Pi 5, BLE proximity on Pi Zero
- All solar/TWC data flows through localhost dashboard APIs (single Envoy consumer)
- BLE relay authenticates via X-API-Key header
- Container runs with `--net=host` so localhost = host

## Requirements

* **Raspberry Pi 5** (or 3/4) as main controller
* **Pi Zero 2 W** as BLE relay (positioned near vehicle)
* **Tesla Wall Connector** (Gen 2/3, on local network)
* **Enphase Envoy** (or compatible solar gateway with local API)
* **Dashboard service** providing the API endpoints below
* `tesla-control` binary (Tesla vehicle-command Go SDK)
* Tesla auth token (`cache.json`) and BLE private key (`private.pem`)

## Setup

1. Update the `CONFIG` section in `solar_charger_twc.py` with your VIN and email.
2. Place `private.pem` and `cache.json` in the application directory.
3. Configure the BLE relay on Pi Zero (see `pi-zero-ble-relay/`).
4. Set `BLE_RELAY_API_KEY` environment variable (or update the default in code).
5. Deploy via Podman/Docker + systemd.

## Dashboard API Contract

The charger expects a dashboard to provide these HTTP endpoints. Implement using Flask, Home Assistant, Node-RED, or any web framework.

### Required Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/envoy_data` | GET | Solar production data |
| `/api/charging/config` | GET | Charging mode, flags, and calendar advisory |
| `/api/set_charger_status` | POST | Receives telemetry from charger |
| `/api/twc/vehicle_connected` | GET | TWC plug state (port 5002) |

### Endpoint Details

**GET `/api/envoy_data`** - Solar production data
```json
{
  "production_watts": 5200,
  "excess_watts": 3100
}
```

**GET `/api/charging/config`** - Mode, flags, and calendar advisory
```json
{
  "mode": "SOLAR",
  "solar_takeover_requested": false,
  "precondition_inhibit_until": 0,
  "calendar_advisory": {
    "active": true,
    "event_title": "Trip to Boston",
    "battery_target": 90,
    "friendly_message": "120 mile round trip — charging to 90% recommended",
    "above_80_approved": false,
    "charge_after": 1770590000.0,
    "charge_after_iso": "2026-02-08T14:00:00",
    "expires_at": 1770606000.0,
    "dismissed": false
  }
}
```

**POST `/api/set_charger_status`** - Telemetry from charger
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
  "timestamp": "2026-02-08T14:30:00",
  "ble_fail_count": 0,
  "ble_backoff_remaining": 0,
  "grid_charge_warning_amps": null,
  "calendar_reason": null
}
```

**GET `/api/twc/vehicle_connected`** - TWC connection state
```json
{
  "connected": true,
  "data_age_seconds": 5
}
```

### Optional Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/charging/solar_takeover` | POST | Request solar control of external charging |
| `/api/charging/clear_takeover` | POST | Clear takeover flag (called by charger) |
| `/api/calendar/approve_above_80` | POST | Approve charging above 80% (calendar gate) |
| `/api/calendar/dismiss` | POST | Stop calendar charge plan |

### BLE Relay

The charger sends commands to the Pi Zero relay via HTTP:

**POST `http://<relay-host>:5003/ble/command`**
```json
{"command": "charging-set-amps", "args": ["24"], "domain": "infotainment"}
```
Headers: `X-API-Key: <your-api-key>`

See `pi-zero-ble-relay/` for relay setup and documentation.

## Version History

| Version | Highlights |
|---------|-----------|
| **v4.0.16-twc** | Calendar-aware charging, smart charge timing, 80% approval gate, calendar wake escalation |
| **v4.0.15-twc** | BLE relay API key auth, SOLAR_API_BASE fix, emergency battery-unknown safety |
| **v4.0.14-twc** | TWC stale data polling optimization |
| **v4.0.13-twc** | Wake cache consistency fix, auth cache structure fix |
| **v4.0.12-twc** | Relay payload fix, state reset helpers refactor |
| **v4.0.11-twc** | Preconditioning detection (skip amp adjustments during precond) |
| **v4.0.10-twc** | TWC-only home detection (GPS geofencing removed) |
| **v3.6.9** | Emergency mode TWC verification and reassert |
| **v3.6.8** | AWAY night tracking, BLE alert dashboard |
| **v3.6.7** | Emergency exit fix, battery age indicator, session summaries |

## Disclaimer

Use at your own risk. This script interfaces directly with vehicle charging hardware and high-voltage systems.
