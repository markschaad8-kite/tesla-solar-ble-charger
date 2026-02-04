#!/usr/bin/env python3
"""
BLE Relay Service for Tesla Solar Control

Runs on Pi Zero 2 W to relay BLE commands from Pi 5 to Tesla vehicle.
Exposes a simple HTTP API that executes tesla-control commands.
"""

import os
import subprocess
import time
import json
from datetime import datetime
from flask import Flask, request, jsonify

# =============================================================================
# Configuration
# =============================================================================

# Load from environment or use defaults
VIN = os.environ.get('TESLA_VIN', 'YOUR_VIN_HERE')
KEY_FILE = os.environ.get('KEY_FILE', '/home/pi/pi-zero-ble-relay/private.pem')
TESLA_CONTROL_PATH = os.environ.get('TESLA_CONTROL_PATH', '/usr/local/bin/tesla-control')
PORT = int(os.environ.get('RELAY_PORT', '5003'))
BLE_TIMEOUT = int(os.environ.get('BLE_TIMEOUT', '45'))  # seconds

# Optional API key for security (set in config.env)
API_KEY = os.environ.get('API_KEY', '')

# =============================================================================
# Stats tracking
# =============================================================================

stats = {
    'start_time': time.time(),
    'commands_sent': 0,
    'commands_succeeded': 0,
    'commands_failed': 0,
    'last_command': None,
    'last_command_time': None,
    'last_command_success': None,
}

# =============================================================================
# Flask App
# =============================================================================

app = Flask(__name__)


def check_api_key():
    """Validate API key if configured."""
    if not API_KEY:
        return True  # No auth required

    provided_key = request.headers.get('X-API-Key', '')
    return provided_key == API_KEY


def run_tesla_control(command, args=None, domain='infotainment'):
    """
    Execute a tesla-control BLE command.

    Args:
        command: The tesla-control command (e.g., 'charging-set-amps')
        args: List of arguments (e.g., ['20'])
        domain: BLE domain ('infotainment' or 'vcsec')

    Returns:
        tuple: (success: bool, output: str, duration: float)
    """
    if args is None:
        args = []

    cmd = [
        TESLA_CONTROL_PATH,
        '-ble',
        '-domain', domain,
        '-key-file', KEY_FILE,
        '-vin', VIN,
        command
    ] + [str(a) for a in args]

    start_time = time.time()

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=BLE_TIMEOUT
        )
        duration = time.time() - start_time
        output = (result.stdout + result.stderr).strip()
        success = result.returncode == 0

        return success, output, duration

    except subprocess.TimeoutExpired:
        duration = time.time() - start_time
        return False, f"Command timed out after {BLE_TIMEOUT}s", duration

    except Exception as e:
        duration = time.time() - start_time
        return False, f"Error: {str(e)}", duration


def check_bluetooth():
    """Check if Bluetooth adapter is available."""
    try:
        result = subprocess.run(
            ['hciconfig', 'hci0'],
            capture_output=True,
            text=True,
            timeout=5
        )
        return 'UP RUNNING' in result.stdout
    except:
        return False


def check_tesla_control():
    """Check if tesla-control binary exists."""
    return os.path.isfile(TESLA_CONTROL_PATH)


# =============================================================================
# API Endpoints
# =============================================================================

@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint."""
    return jsonify({
        'status': 'ok',
        'bluetooth': check_bluetooth(),
        'tesla_control': check_tesla_control(),
    })


@app.route('/status', methods=['GET'])
def status():
    """Detailed status endpoint."""
    return jsonify({
        'uptime': int(time.time() - stats['start_time']),
        'commands_sent': stats['commands_sent'],
        'commands_succeeded': stats['commands_succeeded'],
        'commands_failed': stats['commands_failed'],
        'last_command': stats['last_command'],
        'last_command_time': stats['last_command_time'],
        'last_command_success': stats['last_command_success'],
        'config': {
            'vin': VIN[-6:],  # Only show last 6 chars for privacy
            'key_file': KEY_FILE,
            'ble_timeout': BLE_TIMEOUT,
        }
    })


@app.route('/ble/command', methods=['POST'])
def ble_command():
    """
    Execute a BLE command.

    Request body:
    {
        "command": "charging-set-amps",
        "args": ["20"],
        "domain": "infotainment"  // optional, defaults to "infotainment"
    }
    """
    # Check API key if configured
    if not check_api_key():
        return jsonify({'error': 'Unauthorized'}), 401

    # Parse request
    data = request.get_json()
    if not data:
        return jsonify({'error': 'JSON body required'}), 400

    command = data.get('command')
    if not command:
        return jsonify({'error': 'command field required'}), 400

    args = data.get('args', [])
    domain = data.get('domain', 'infotainment')

    # Log the request
    cmd_str = f"{command} {' '.join(str(a) for a in args)}".strip()
    print(f"[{datetime.now().strftime('%H:%M:%S')}] BLE command: {cmd_str} (domain={domain})")

    # Execute the command
    success, output, duration = run_tesla_control(command, args, domain)

    # Update stats
    stats['commands_sent'] += 1
    if success:
        stats['commands_succeeded'] += 1
    else:
        stats['commands_failed'] += 1
    stats['last_command'] = cmd_str
    stats['last_command_time'] = datetime.now().isoformat()
    stats['last_command_success'] = success

    # Log result
    status_str = "OK" if success else "FAILED"
    print(f"[{datetime.now().strftime('%H:%M:%S')}] BLE result: {status_str} ({duration:.1f}s)")
    if not success:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] BLE error: {output[:200]}")

    return jsonify({
        'success': success,
        'output': output,
        'duration': round(duration, 2),
        'error': None if success else output,
    })


@app.route('/ble/wake', methods=['POST'])
def ble_wake():
    """
    Convenience endpoint to wake the vehicle.
    Tries BLE first, which often wakes the car as a side effect.
    """
    if not check_api_key():
        return jsonify({'error': 'Unauthorized'}), 401

    print(f"[{datetime.now().strftime('%H:%M:%S')}] Wake request received")

    # Try a simple BLE command that might wake the car
    success, output, duration = run_tesla_control('ping')

    return jsonify({
        'success': success,
        'output': output,
        'duration': round(duration, 2),
    })


# =============================================================================
# Startup
# =============================================================================

def ensure_bluetooth_up():
    """Ensure Bluetooth adapter is up on startup."""
    try:
        subprocess.run(['sudo', 'hciconfig', 'hci0', 'up'],
                      capture_output=True, timeout=5)
        print("Bluetooth adapter initialized")
    except Exception as e:
        print(f"Warning: Could not initialize Bluetooth: {e}")


if __name__ == '__main__':
    print("=" * 60)
    print("Tesla BLE Relay Service")
    print("=" * 60)
    print(f"VIN: ...{VIN[-6:]}")
    print(f"Key file: {KEY_FILE}")
    print(f"Port: {PORT}")
    print(f"BLE timeout: {BLE_TIMEOUT}s")
    print(f"API key: {'configured' if API_KEY else 'disabled'}")
    print("=" * 60)

    # Check prerequisites
    if not check_tesla_control():
        print(f"ERROR: tesla-control not found at {TESLA_CONTROL_PATH}")
        print("Run setup.sh or install manually")
        exit(1)

    if not os.path.isfile(KEY_FILE):
        print(f"ERROR: Key file not found at {KEY_FILE}")
        print("Copy private.pem from Pi 5")
        exit(1)

    # Initialize Bluetooth
    ensure_bluetooth_up()

    if not check_bluetooth():
        print("WARNING: Bluetooth adapter may not be available")

    print(f"\nStarting server on port {PORT}...")
    print(f"Test with: curl http://localhost:{PORT}/health")
    print()

    # Run Flask (use waitress in production for better performance)
    try:
        from waitress import serve
        serve(app, host='0.0.0.0', port=PORT)
    except ImportError:
        # Fall back to Flask dev server
        app.run(host='0.0.0.0', port=PORT, threaded=True)
