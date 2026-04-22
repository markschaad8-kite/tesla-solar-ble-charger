# Tesla Solar Charger (BLE + TWC Edition)

Controls Tesla charging based on solar excess. Runs on a Raspberry Pi 5 in a Podman container; BLE commands go through a Pi Zero 2 W relay positioned near the vehicle. No cloud dependency for day-to-day operation.

## What it does

- Tracks Enphase solar data and adjusts charging amps (6–48A) to consume available excess. 3-sample moving average prevents cloud-flapping.
- Uses `tesla-control` over BLE through a Pi Zero relay — lower latency than the Tesla API, avoids waking the car unnecessarily, and the relay can be positioned independently for better range.
- Detects home/away via Tesla Wall Connector plug state. No GPS geofencing.
- Reads Google Calendar for upcoming trips. An AI assessment estimates round-trip distance and recommends a battery target (50–95%); timing is calculated from departure minus estimated charge time so it doesn't start charging 24 hours early.
- Trips targeting above 80% pause at 80% for dashboard approval. Auto-approves if departure is under 2 hours out.
- When battery drops below 50%, charges at full speed (48A) regardless of solar. Continues past the 90-minute fallback if battery is still rising.
- Stops charging when solar drops below 100W for 10 minutes. Resumes at sunrise.
- After 3 consecutive BLE failures, escalates to a Tesla API wake. Each mode tracks its own cooldown separately.
- Resets the car to 48A on unplug so the next session starts at max rate.
- Resets amp tracking on each new plug-in so SOLAR always ramps from the minimum rather than inheriting a stale value.

## Charging Modes

| Mode | Priority | Trigger | Behavior |
|------|----------|---------|----------|
| **EMERGENCY** | Highest | Battery < 50% | Charge at 48A until 50%. Continues past 90-min timeout if battery still rising. |
| **CALENDAR** | High | Active trip advisory | Charge at 48A to advisory target. Pauses at 80% if target > 80% (approval gate). |
| **CALENDAR_WAITING** | - | Advisory active, before charge_after time | Shows countdown on dashboard, falls through to SOLAR. |
| **MANUAL** | Medium | User-enabled via dashboard | Charge at 48A to 80% regardless of solar. Wake escalation after 3 BLE fails. |
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

- Two-Pi design: control logic on Pi 5, BLE proximity on Pi Zero
- All solar/TWC data flows through localhost dashboard APIs (single Envoy consumer)
- BLE relay authenticates via X-API-Key header
- Container runs with `--net=host` so localhost = host

## Requirements

- Raspberry Pi 5 (or 3B/4) as main controller
- Pi Zero 2 W as BLE relay, placed near the vehicle
- Tesla Wall Connector (Gen 2/3) on the local network
- Enphase Envoy (or compatible solar gateway with a local API)
- A dashboard service providing the endpoints below
- `tesla-control` binary from the Tesla vehicle-command SDK
- Tesla auth token (`cache.json`) and BLE private key (`private.pem`)

## Setup

1. Set `TESLA_VIN` and `TESLA_EMAIL` environment variables (or edit the constants in `solar_charger_twc.py`).
2. Place `private.pem` and `cache.json` in the working directory.
3. Configure the BLE relay on the Pi Zero (see `pi-zero-ble-relay/`).
4. Set `BLE_RELAY_API_KEY` to match the relay's configured key.
5. Build the container and deploy via systemd.

## Dashboard API Contract

The charger expects a dashboard to expose these HTTP endpoints.

### Required Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/envoy_data` | GET | Solar production data |
| `/api/charging/config` | GET | Charging mode, flags, and calendar advisory |
| `/api/set_charger_status` | POST | Receives telemetry from charger |
| `/api/twc/vehicle_connected` | GET | TWC plug state (port 5002) |

### Endpoint Details

**GET `/api/envoy_data`**
```json
{
  "production_watts": 5200,
  "excess_watts": 3100
}
```

**GET `/api/charging/config`**
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

**POST `/api/set_charger_status`** — telemetry from charger
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

**GET `/api/twc/vehicle_connected`**
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

Commands go to the Pi Zero relay via HTTP POST:

**POST `http://<relay-host>:5003/ble/command`**
```json
{"command": "charging-set-amps", "args": ["24"], "domain": "infotainment"}
```
Headers: `X-API-Key: <your-api-key>`

See `pi-zero-ble-relay/` for relay setup.

## Version History

| Version | Highlights |
|---------|-----------|
| **v4.0.20-twc** | Reset current_amps on session start (stale-48A deadlock fix); relay unreachable streak alerting |
| **v4.0.19-twc** | Suppress BLE and high-solar wake when car is Complete at target in SOLAR |
| **v4.0.18-twc** | Fix 5 EMERGENCY bugs: fallthrough to NIGHT, stale amps on exit, cached_battery stale on connect, night_stop persisting into EMERGENCY, missing wake escalation |
| **v4.0.17-twc** | Fix EMERGENCY fallthrough to SOLAR after 90-min timeout reset (missing `continue`) |
| **v4.0.16-twc** | Calendar-aware charging, smart charge timing, 80% approval gate |
| **v4.0.15-twc** | BLE relay API key auth, SOLAR_API_BASE fix, emergency battery-unknown safety |
| **v4.0.14-twc** | TWC stale data polling optimization |
| **v4.0.13-twc** | Wake cache consistency fix, auth cache structure fix |
| **v4.0.12-twc** | Relay payload fix, state reset helpers refactor |
| **v4.0.11-twc** | Preconditioning detection |
| **v4.0.10-twc** | TWC-only home detection (GPS geofencing removed) |
| **v3.6.9** | Emergency mode TWC verification and reassert |
| **v3.6.8** | AWAY night tracking, BLE alert dashboard |
| **v3.6.7** | Emergency exit fix, battery age indicator, session summaries |
