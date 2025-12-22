# Tesla Solar Charger (BLE + TWC Edition) - v4.0.1

Automated Tesla charging control script running on Raspberry Pi. This system adjusts charging amperage in real-time based on solar excess, using local Bluetooth (BLE) control to avoid Tesla API rate limits and wake issues.

## ⚡ Core Features (v4.0.1)

* **Solar Tracking:** Monitors Enphase Envoy data to adjust vehicle charging amps (1A increments) to match solar export.
* **BLE-First Control:** Uses `tesla-control` (Bluetooth Low Energy) for all commands (Start/Stop/Set Amps). This is faster than the HTTP API and prevents "waking" the car unnecessarily.
* **TWC Integration:** Polls the Tesla Wall Connector (Gen 2/3) API locally to detect "Plugged In" state instantly.
* **Smart Disconnect (v4.0.1):** Automatically resets the car to **MAX_AMPS (48A)** when unplugged.
    * *Edge Case Handling:* If BLE is on cooldown when you unplug, the system flags a "pending normalization" and forces the reset immediately upon the next connection.
* **Zero-Grid Drain:** "Night Mode" automatically stops charging when solar production drops below 100W for 10 minutes.
* **Emergency Mode:** If battery drops below 50%, the system overrides solar rules and charges at full speed (48A) until the target is reached.

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

## ⚠️ Disclaimer
Use at your own risk. This script interfaces directly with vehicle charging hardware and high-voltage systems.
