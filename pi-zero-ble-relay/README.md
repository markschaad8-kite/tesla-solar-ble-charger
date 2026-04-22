# Pi Zero 2 W - BLE Relay

Runs `ble_relay.py` on a Pi Zero 2 W to proxy BLE commands from the main controller to the Tesla. The Pi Zero is placed near the vehicle for better BLE range; the Pi 5 handles all the control logic.

```
[Pi 5 @ 192.168.x.x]                      [Pi Zero 2 @ 192.168.x.y]
┌─────────────────────┐                   ┌─────────────────────────┐
│  solar_charger.py   │  HTTP :5003       │    ble_relay.py         │
│                     │ ───────────────>  │                         │
│  POST /ble/command  │                   │  tesla-control -ble     │
│                     │ <───────────────  │          │              │
│  {success, output}  │                   │          │ BLE          │
└─────────────────────┘                   │          ▼              │
                                          │    [Tesla Vehicle]      │
                                          └─────────────────────────┘
```

## Hardware

- Raspberry Pi Zero 2 W (has WiFi + BT 4.2)
- Place within ~15–20 feet of the Tesla

## Setup

Flash Raspberry Pi OS Lite (64-bit), enable SSH, set your hostname/WiFi in Raspberry Pi Imager. Then:

```bash
# Copy relay files to Pi Zero
scp -r /path/to/pi-zero-ble-relay pi@tesla-ble-relay.local:~/

# On the Pi Zero
cd ~/pi-zero-ble-relay
chmod +x setup.sh
./setup.sh
```

`setup.sh` installs Python deps, builds `tesla-control` from source (~10 min on Pi Zero), and installs the systemd service.

Copy credentials from Pi 5:
```bash
scp /path/to/your/private.pem pi@tesla-ble-relay.local:~/pi-zero-ble-relay/
```

Configure and start:
```bash
cp ~/pi-zero-ble-relay/config.env.example ~/pi-zero-ble-relay/config.env
nano ~/pi-zero-ble-relay/config.env   # set TESLA_VIN and API key
sudo systemctl enable --now ble-relay
```

Test from the Pi 5:
```bash
curl -X POST http://tesla-ble-relay.local:5003/ble/command \
  -H "Content-Type: application/json" \
  -H "X-API-Key: <your-key>" \
  -d '{"command": "charging-set-amps", "args": ["16"]}'
```

## API

### POST /ble/command

```json
{
  "command": "charging-set-amps",
  "args": ["20"],
  "domain": "infotainment"
}
```

`domain` defaults to `"infotainment"`. Use `"vcsec"` for lock/unlock commands.

```json
{
  "success": true,
  "output": "...",
  "duration": 15.2,
  "error": null
}
```

### GET /health

```json
{"status": "ok", "bluetooth": true, "tesla_control": true}
```

### GET /status

```json
{
  "uptime": 3600,
  "commands_sent": 42,
  "commands_failed": 3,
  "last_command": "charging-set-amps 20",
  "last_command_time": "2025-01-16T12:00:00Z"
}
```

## Troubleshooting

BLE failing:
```bash
hciconfig hci0 up
sudo systemctl restart bluetooth
```

`tesla-control` not found:
```bash
cd ~/vehicle-command
go build -o /usr/local/bin/tesla-control ./cmd/tesla-control
```

Logs:
```bash
journalctl -u ble-relay -f
```
