# Changes Required on Pi 5

After setting up the Pi Zero BLE relay, you need to modify `solar_charger.py` on the
Pi 5 to send BLE commands through the relay instead of running them locally.

## Configuration

Add these to your Pi 5's `.env` or as environment variables:

```bash
# Pi Zero BLE Relay configuration
BLE_RELAY_HOST=tesla-ble-relay.local  # or IP address like 192.168.x.y
BLE_RELAY_PORT=5003
BLE_RELAY_ENABLED=true
```

## Code Changes

### Option A: Minimal Changes (Recommended)

Replace the `run_tesla_control` function in `solar_charger.py` with a version that
calls the relay when enabled:

```python
# Add near the top with other imports
import requests

# Add configuration (near other config vars)
BLE_RELAY_ENABLED = os.environ.get('BLE_RELAY_ENABLED', 'false').lower() == 'true'
BLE_RELAY_HOST = os.environ.get('BLE_RELAY_HOST', 'tesla-ble-relay.local')
BLE_RELAY_PORT = int(os.environ.get('BLE_RELAY_PORT', '5003'))
BLE_RELAY_URL = f"http://{BLE_RELAY_HOST}:{BLE_RELAY_PORT}"

def run_tesla_control(cmd):
    """
    Execute tesla-control command, either locally or via BLE relay.
    """
    if BLE_RELAY_ENABLED:
        return run_tesla_control_via_relay(cmd)
    else:
        return run_tesla_control_local(cmd)


def run_tesla_control_local(cmd):
    """Original local execution."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        out = (r.stdout + r.stderr).lower()
        return r.returncode == 0, out
    except Exception as e:
        return False, str(e)


def run_tesla_control_via_relay(cmd):
    """
    Execute tesla-control via Pi Zero BLE relay.

    The cmd list looks like:
    ['tesla-control', '-ble', '-key-file', '/app/private.pem', '-vin', 'XXX', 'charging-set-amps', '20']

    We extract the command and args, send to relay.
    """
    try:
        # Parse the command list to extract the actual command and args
        # Skip the tesla-control binary and standard flags
        # Find the command (first arg that doesn't start with -)
        command = None
        args = []
        skip_next = False

        for i, part in enumerate(cmd):
            if skip_next:
                skip_next = False
                continue

            # Skip the binary name
            if part == 'tesla-control' or part.endswith('tesla-control'):
                continue

            # Skip flags and their values
            if part in ['-ble', '-debug']:
                continue
            if part in ['-key-file', '-vin', '-key-name']:
                skip_next = True  # Skip the next value too
                continue

            # This must be the command or an arg
            if command is None:
                command = part
            else:
                args.append(part)

        if not command:
            return False, "Could not parse command from cmd list"

        # Send to relay
        response = requests.post(
            f"{BLE_RELAY_URL}/ble/command",
            json={'command': command, 'args': args},
            timeout=60  # Allow for BLE timeout + network
        )

        data = response.json()
        success = data.get('success', False)
        output = data.get('output', '')

        # Log relay usage
        log(f"BLE relay: {command} {' '.join(args)} -> {'OK' if success else 'FAILED'} ({data.get('duration', 0):.1f}s)")

        return success, output.lower()

    except requests.exceptions.Timeout:
        return False, "relay timeout"
    except requests.exceptions.ConnectionError:
        return False, "relay connection failed"
    except Exception as e:
        return False, f"relay error: {str(e)}"
```

### Option B: Environment-Based Toggle

If you want to easily switch between local and relay modes, you can use an
environment variable:

```bash
# In .env file
BLE_RELAY_ENABLED=true   # Use relay
BLE_RELAY_ENABLED=false  # Use local BLE (original behavior)
```

## Testing

1. First, test the relay directly from Pi 5:
   ```bash
   curl http://tesla-ble-relay.local:5003/health
   ```

2. Then test a BLE command:
   ```bash
   curl -X POST http://tesla-ble-relay.local:5003/ble/command \
     -H "Content-Type: application/json" \
     -d '{"command": "charging-set-amps", "args": ["16"]}'
   ```

3. Update solar_charger.py with the changes above

4. Rebuild the container:
   ```bash
   cd ~/tesla-solar-control
   sudo podman build -t localhost/tesla-solar-control:latest .
   sudo systemctl restart solar-charger
   ```

5. Monitor logs:
   ```bash
   journalctl -u solar-charger -f
   ```

   You should see:
   ```
   BLE relay: charging-set-amps 20 -> OK (15.2s)
   ```

## Rollback

To disable the relay and go back to local BLE:

```bash
# Set in .env
BLE_RELAY_ENABLED=false

# Rebuild container
sudo podman build -t localhost/tesla-solar-control:latest .
sudo systemctl restart solar-charger
```

## Network Considerations

- The relay adds ~50-100ms of network latency per command
- If the Pi Zero becomes unreachable, commands will fail with "relay connection failed"
- Consider adding retry logic or fallback to local BLE if relay fails

## Monitoring

You can check relay stats from Pi 5:
```bash
curl http://tesla-ble-relay.local:5003/status
```

This shows:
- Total commands sent
- Success/failure counts
- Last command and result
