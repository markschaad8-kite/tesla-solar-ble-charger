# Pi Zero 2 W - BLE Relay for Tesla Solar Control

This sets up a Pi Zero 2 W as a BLE proxy to send commands to a Tesla vehicle.
The main solar_charger.py continues running on the Pi 5, but BLE commands are
relayed through this Pi Zero which should be placed closer to the vehicle.

## Hardware Requirements

- Raspberry Pi Zero 2 W (has WiFi + Bluetooth 4.2)
- MicroSD card (8GB+ recommended)
- Power supply (micro USB, 5V 2.5A)
- Place within ~15-20 feet of the Tesla

## Network Architecture

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

## Setup Instructions

### Step 1: Flash Raspberry Pi OS Lite

1. Download Raspberry Pi Imager
2. Select "Raspberry Pi OS Lite (64-bit)" - no desktop needed
3. Click gear icon for advanced options:
   - Set hostname: `tesla-ble-relay`
   - Enable SSH with password authentication
   - Set username: `pi` (or your preference)
   - Set password
   - Configure WiFi (same network as Pi 5)
   - Set locale/timezone
4. Flash to SD card and boot the Pi Zero 2

### Step 2: Initial Pi Zero Setup

SSH into the Pi Zero:
```bash
ssh pi@tesla-ble-relay.local
# or use IP address if hostname doesn't resolve
```

Update the system:
```bash
sudo apt update && sudo apt upgrade -y
```

### Step 3: Copy This Folder to Pi Zero

From your Pi 5, copy this entire folder:
```bash
scp -r /path/to/pi-zero-ble-relay pi@tesla-ble-relay.local:~/
```

### Step 4: Run the Setup Script

On the Pi Zero:
```bash
cd ~/pi-zero-ble-relay
chmod +x setup.sh
./setup.sh
```

This script will:
- Install Python dependencies
- Install Go and build tesla-control
- Set up the systemd service

**Note:** Building tesla-control on Pi Zero 2 takes ~10-15 minutes due to limited CPU.

### Step 5: Copy Tesla Credentials

From your Pi 5, copy the private key:
```bash
scp /path/to/your/private.pem pi@tesla-ble-relay.local:~/pi-zero-ble-relay/
```

Set permissions on Pi Zero:
```bash
chmod 600 ~/pi-zero-ble-relay/private.pem
```

### Step 6: Configure and Start the Service

Copy and edit the config:
```bash
cp ~/pi-zero-ble-relay/config.env.example ~/pi-zero-ble-relay/config.env
nano ~/pi-zero-ble-relay/config.env
# Set your TESLA_VIN and any other settings
```

Start the service:
```bash
sudo systemctl enable ble-relay
sudo systemctl start ble-relay
```

Check status:
```bash
sudo systemctl status ble-relay
journalctl -u ble-relay -f
```

### Step 7: Test the Relay

From the Pi 5, test the relay:
```bash
# Replace IP with your Pi Zero's IP
curl -X POST http://tesla-ble-relay.local:5003/ble/command \
  -H "Content-Type: application/json" \
  -d '{"command": "charging-set-amps", "args": ["16"]}'
```

Expected response:
```json
{"success": true, "output": "...", "duration": 12.5}
```

### Step 8: Update Pi 5 solar_charger.py

See `PI5_CHANGES.md` for the code changes needed on the Pi 5 to use this relay.

---

## API Reference

### POST /ble/command

Execute a tesla-control BLE command.

**Request:**
```json
{
  "command": "charging-set-amps",
  "args": ["20"],
  "domain": "infotainment"
}
```

Note: `domain` is optional and defaults to `"infotainment"`. Use `"vcsec"` for lock/unlock commands.

**Response:**
```json
{
  "success": true,
  "output": "Command output...",
  "duration": 15.2,
  "error": null
}
```

### GET /health

Health check endpoint.

**Response:**
```json
{
  "status": "ok",
  "bluetooth": true,
  "tesla_control": true
}
```

### GET /status

Detailed status.

**Response:**
```json
{
  "uptime": 3600,
  "commands_sent": 42,
  "commands_failed": 3,
  "last_command": "charging-set-amps 20",
  "last_command_time": "2025-01-16T12:00:00Z"
}
```

---

## Troubleshooting

### BLE still failing on Pi Zero

Check Bluetooth is up:
```bash
hciconfig hci0 up
hcitool dev
```

Reset Bluetooth:
```bash
sudo systemctl restart bluetooth
sudo hciconfig hci0 reset
```

### tesla-control not found

Verify it's installed:
```bash
which tesla-control
# Should show: /usr/local/bin/tesla-control
```

If not, rebuild:
```bash
cd ~/vehicle-command
go build -o /usr/local/bin/tesla-control ./cmd/tesla-control
```

### Network connectivity

Test from Pi 5:
```bash
ping tesla-ble-relay.local
curl http://tesla-ble-relay.local:5003/health
```

### View logs

```bash
journalctl -u ble-relay -f
```

---

## Security Notes

- The relay runs on port 5003 with no authentication
- Only expose on your local network (not internet)
- The private.pem key is sensitive - protect it
- Consider adding API key authentication if needed (see ble_relay.py comments)
