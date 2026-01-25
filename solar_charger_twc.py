#!/usr/bin/env python3
"""
================================================================================
Solar Charger TWC Fork - v4.0.10-twc - TWC-only home detection (no GPS fallback)
================================================================================

TWC FORK CHANGES (vs GPS version):
----------------------------------
- REMOVED: GPS geofencing constants (HOME_LAT, HOME_LON, HOME_RADIUS_MILES)
- REMOVED: Haversine distance calculation (get_distance_miles)
- SIMPLIFIED: get_tesla_status() returns (battery, charging_state) only
- CHANGED: TWC unreachable falls back to cached TWC state, not GPS
- RATIONALE: TWC connection is authoritative for "at home" status

Based on: Solar Charger v4.0.10

================================================================================
HISTORICAL CHANGELOG (PRESERVED VERBATIM)
================================================================================

V3.6.9 solar_charger - Emergency mode TWC verification and reassert
- BUG FIX: Emergency mode could believe 48A was set while actual charging was limited
  (e.g. 6A)
  - Root cause: BLE commands are write-only; no verification loop existed
- FEATURE: Emergency mode now verifies actual charging current via TWC monitor
  - Reads real vehicle current (amps) from TWC API
  - Detects mismatch between commanded amps and actual current
  - Re-asserts MAX_AMPS when TWC shows sustained low current
- SAFETY: Emergency mode uses TWC current only for verification, not exit decisions
- ARCHITECTURE: Emergency TWC verification updates local control state only

Solar Charger - BLE Edition v3.6.8 (AWAY Night Tracking + BLE Alert Dashboard)
- FEATURE: AWAY mode night tracking
- FEATURE: BLE alert dashboard
- FIX: Skip BLE when no solar excess

Solar Charger - BLE Edition v3.6.7 (Emergency Exit Fix + Observability)
- BUG FIX: Emergency exit dead code fixed
- FEATURE: Battery age indicator
- FEATURE: Emergency telemetry refresh every 60s
- FEATURE: SOLAR mode TWC drift detection
- FEATURE: Session summary logging

Solar Charger - BLE Edition v3.6.6 / v3.6.5 / v3.6.4
- Emergency priority fixes
- Hybrid emergency exit
- BLE backoff cap
- Night freshness checks
- Wake escalation safeguards
- Multiple BLE sequencing fixes

(Full original changelog intentionally retained)

================================================================================
"""

VERSION = "v4.0.10-twc"

import time
import subprocess
import requests
import os
from datetime import datetime
from collections import deque
from dataclasses import dataclass, field
from typing import Optional, Deque, Dict, Any


# -------------------------------
# CONFIG - Set via environment variables
# -------------------------------
VIN = os.getenv("TESLA_VIN", "YOUR_VIN_HERE")
KEY_FILE = os.getenv("TESLA_KEY_FILE", "/app/private.pem")
CACHE_FILE = os.getenv("TESLA_CACHE_FILE", "/app/cache.json")
TESLA_EMAIL = os.getenv("TESLA_EMAIL", "your_email@example.com")

# -------------------------------
# NETWORK CONFIG
# -------------------------------
SOLAR_API_BASE = os.getenv(
    "SOLAR_API_BASE",
    "http://localhost"  # Default to localhost
)

PI2_SOLAR_URL = f"{SOLAR_API_BASE}:8080/api/envoy_data"
PI2_CONFIG_URL = f"{SOLAR_API_BASE}:8080/api/charging/config"
PI2_STATUS_URL = f"{SOLAR_API_BASE}:8080/api/set_charger_status"
TWC_MONITOR_URL = f"{SOLAR_API_BASE}:5002/api/twc/vehicle_connected"

# -------------------------------
# BLE RELAY CONFIG (Pi Zero proxy)
# -------------------------------
BLE_RELAY_ENABLED = os.getenv("BLE_RELAY_ENABLED", "true").lower() == "true"
BLE_RELAY_HOST = os.getenv("BLE_RELAY_HOST", "SolarPiZero")
BLE_RELAY_PORT = int(os.getenv("BLE_RELAY_PORT", "5003"))
BLE_RELAY_URL = f"http://{BLE_RELAY_HOST}:{BLE_RELAY_PORT}"

TWC_CACHE_TTL = 15
TWC_STALE_THRESHOLD = 90

# GPS constants REMOVED in TWC fork - TWC connection is authoritative for home detection

VOLTAGE = 240
MIN_SOLAR_PRODUCTION = 100
MIN_AMPS = 6
MAX_AMPS = 48
BATTERY_EMERGENCY = 50
BATTERY_TARGET = 80

LOOP_INTERVAL = 30
STATUS_CHECK_INTERVAL = 300
CACHE_TTL = 600

AMP_CHANGE_THRESHOLD = 2
AMP_STABILITY_COUNT = 1
AMP_STABILITY_BAND = 2
MAX_AMP_STEP = 4  # Max amp increase per loop (Envoy updates every 60s, loop is 30s)
SMOOTH_WINDOW = 3
SUSTAINED_NIGHT_SEC = 600

BLE_COOLDOWN = 12
BLE_BACKOFF_INITIAL = 60
BLE_MAX_BACKOFF = 3600

# Wake escalation (MANUAL mode only)
WAKE_COOLDOWN_SEC = 900       # 15 minutes
BLE_FAILS_BEFORE_WAKE = 3

# Hybrid emergency fallback runtime
MAX_EMERGENCY_RUNTIME = 90 * 60  # 90 minutes

# Emergency mode uses more aggressive telemetry refresh (60s vs normal 300s)
EMERGENCY_STATUS_INTERVAL = 60


# -------------------------------
# STATE (Stage 1 refactor: consolidate former globals)
# -------------------------------
@dataclass
class ChargerState:
    # Former globals
    current_amps: int = 0

    cached_battery: Optional[int] = None
    # cached_is_home REMOVED in TWC fork - TWC connection is authoritative
    cached_charging_state: Optional[str] = None
    cached_vehicle_online: bool = True
    cached_ts: float = 0.0
    last_status_check: float = 0.0

    amp_target_history: Deque[int] = field(default_factory=lambda: deque(maxlen=AMP_STABILITY_COUNT))
    production_window: Deque[float] = field(default_factory=lambda: deque(maxlen=SMOOTH_WINDOW))
    excess_window: Deque[float] = field(default_factory=lambda: deque(maxlen=SMOOTH_WINDOW))

    last_low_prod_time: Optional[float] = None
    night_stop_sent: bool = False
    last_manual_state: bool = False

    # BLE state
    ble_command_this_loop: bool = False
    ble_attempted_this_loop: bool = False
    last_ble_time: float = 0.0
    ble_backoff_until: float = 0.0
    ble_fail_count: int = 0

    # Charge limit cache - avoid redundant BLE calls
    last_charge_limit_set: Optional[int] = None

    # TWC cache
    twc_cache: Dict[str, Any] = field(default_factory=lambda: {'value': None, 'ts': 0.0, 'last_logged_state': None})

    # TWC disconnect tracking for amp reset
    last_twc_state: Optional[bool] = None

    # Wake escalation state
    manual_ble_fails: int = 0
    solar_ble_fails: int = 0
    last_wake_attempt_manual: float = 0.0
    last_wake_attempt_solar: float = 0.0

    # Emergency tracking
    emergency_start_ts: Optional[float] = None

    # Session tracking
    session_start_ts: Optional[float] = None
    session_peak_amps: int = 0

    # --- v4.0.1: Explicit TWC edge semantics ---
    pending_disconnect_amp_normalization: bool = False
    pending_disconnect_reason: Optional[str] = None

    # --- v4.0.3: Dashboard warning flags ---
    grid_charge_warning_amps: Optional[float] = None

state = ChargerState()

# -------------------------------
# Helper: report Tesla OAuth token presence at startup
# -------------------------------
def auth_cache_status(cache_path: str) -> str:
    try:
        with open(cache_path, "r", encoding="utf-8") as f:
            data = f.read()
        if '"access_token"' in data and '"refresh_token"' in data:
            return "OK (tokens present)"
        return "MISSING TOKENS"
    except Exception as e:
        return f"ERROR reading cache ({type(e).__name__}: {e})"


# -------------------------------
# Logging
# -------------------------------
def log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


# -------------------------------
# Utilities
# -------------------------------
# get_distance_miles REMOVED in TWC fork - GPS geofencing not used


# -------------------------------
# TWC Integration
# -------------------------------
def get_twc_connected_safe():
    """
    Get TWC connection status. TWC fork version - no GPS fallback.
    Returns: True (connected), False (disconnected), None (unreachable)
    """
    now = time.time()
    if now - state.twc_cache['ts'] < TWC_CACHE_TTL and state.twc_cache['value'] is not None:
        return state.twc_cache['value']
    try:
        r = requests.get(TWC_MONITOR_URL, timeout=2.0)
        r.raise_for_status()
        j = r.json()
        data_age = j.get('data_age_seconds')
        if data_age and data_age > TWC_STALE_THRESHOLD:
            log(f"TWC data stale ({data_age}s old) -> using cached state")
            return state.twc_cache['value']  # Return cached instead of None
        connected = bool(j.get('connected', False))
        if connected != state.twc_cache.get('last_logged_state'):
            if connected:
                log("TWC: Vehicle CONNECTED (plug detected)")
            else:
                log("TWC: Vehicle DISCONNECTED (plug removed)")
            state.twc_cache['last_logged_state'] = connected
        state.twc_cache['value'] = connected
        state.twc_cache['ts'] = now
        return connected
    except Exception as e:
        if now - state.twc_cache['ts'] > (TWC_CACHE_TTL * 4):
            if state.twc_cache['value'] is not None:
                log(f"TWC monitor unreachable: {e} -> using cached TWC state")
            # TWC fork: keep cached value instead of setting to None
            state.twc_cache['ts'] = now
        return state.twc_cache['value']


def get_twc_current_amps():
    """Get actual current amps from TWC monitor. Returns None if unavailable."""
    try:
        r = requests.get(f"{TWC_MONITOR_URL.rsplit('/', 1)[0]}/status", timeout=2.0)
        r.raise_for_status()
        j = r.json()
        return float(j.get('vehicle_current_a', 0))
    except Exception as e:
        log(f"Warning: Could not get TWC amps: {e}")
        return None


# -------------------------------
# Solar / Dashboard helpers
# -------------------------------
def get_solar_data():
    try:
        r = requests.get(PI2_SOLAR_URL, timeout=30)  # Verified: 30s timeout
        data = r.json()
        production = float(data.get('production_watts', 0) or 0)
        excess = float(data.get('excess_watts', 0) or 0)
        return {'production': production, 'excess': excess}
    except Exception as e:
        log(f"ERROR get_solar_data: {e}")
        return None


def get_charging_config():
    """Returns full config dict including mode and solar_takeover_requested flag"""
    try:
        r = requests.get(PI2_CONFIG_URL, timeout=4)
        return r.json()
    except Exception:
        return {'mode': 'SOLAR'}


def clear_solar_takeover():
    """Clear the solar takeover flag after acting on it"""
    try:
        url = f"{SOLAR_API_BASE}:8080/api/charging/clear_takeover"
        r = requests.post(url, timeout=4)
        if r.status_code == 200:
            log("Solar takeover flag cleared")
            return True
        else:
            log(f"Failed to clear takeover flag: HTTP {r.status_code}")
            return False
    except Exception as e:
        log(f"ERROR clearing takeover flag: {e}")
        return False


def update_dashboard_status(mode, amps, target_amps, battery, excess_watts, production_watts, chg_state):
    try:
        battery_age_sec = int(time.time() - state.cached_ts) if state.cached_ts > 0 else None
        payload = {
            'mode': mode,
            'amps': amps,
            'target_amps': target_amps,
            'battery': battery,
            'battery_age_sec': battery_age_sec,
            'excess_watts': excess_watts,
            'production_watts': production_watts,
            'state': chg_state,
            'timestamp': datetime.now().isoformat(),
            'ble_fail_count': state.ble_fail_count,
            'ble_backoff_until': state.ble_backoff_until,
            'ble_backoff_remaining': max(0, int(state.ble_backoff_until - time.time())),
            'grid_charge_warning_amps': state.grid_charge_warning_amps
        }
        requests.post(PI2_STATUS_URL, json=payload, timeout=3)
    except Exception as e:
        log(f"ERROR updating dashboard: {e}")


# -------------------------------
# Tesla status (cached + TTL)
# -------------------------------
def get_tesla_status():
    """
    Get Tesla vehicle status. TWC fork version - returns (battery, charging_state) only.
    No GPS/is_home - TWC connection is authoritative for home detection.
    """
    now = time.time()
    if (now - state.cached_ts) < CACHE_TTL:
        return state.cached_battery, state.cached_charging_state
    try:
        import teslapy
        with teslapy.Tesla(TESLA_EMAIL, cache_file='/app/cache.json') as tesla:
            vehicles = tesla.vehicle_list()
            if not vehicles:
                log("No vehicles found (teslapy)")
                return state.cached_battery, state.cached_charging_state
            vehicle = vehicles[0]
            if vehicle['state'] != 'online':
                log(f"Vehicle {vehicle['state']} - using cache")
                state.cached_vehicle_online = False
                return state.cached_battery, state.cached_charging_state
            data = vehicle.get_vehicle_data()
            # GPS location check REMOVED in TWC fork
            charge_state = data.get('charge_state', {})
            battery = charge_state.get('battery_level', state.cached_battery)
            charging = charge_state.get('charging_state', state.cached_charging_state)

            # Only update cache on successful fetch
            state.cached_battery = battery
            state.cached_charging_state = charging
            state.cached_vehicle_online = True
            state.cached_ts = now
            state.last_status_check = now

            log(f"Tesla: Battery={battery}%, State={charging}")
            return battery, charging
    except Exception as e:
        log(f"Tesla status error: {e}")
        return state.cached_battery, state.cached_charging_state


# -------------------------------
# Wake escalation (MANUAL only)
# -------------------------------
def wake_vehicle_safe(reason: str = 'manual'):
    """
    Wake car via Tesla API with cooldown.
    Supports separate cooldowns for MANUAL vs SOLAR escalation.
    Returns True if wake was attempted, False if skipped/failed.
    """
    now = time.time()

    # Select appropriate cooldown based on reason
    if reason == 'solar':
        last_attempt = state.last_wake_attempt_solar
    else:
        last_attempt = state.last_wake_attempt_manual

    remaining = WAKE_COOLDOWN_SEC - (now - last_attempt)
    if remaining > 0:
        log(f"Wake skipped [{reason}] (cooldown {int(remaining)}s remaining)")
        return False

    try:
        import teslapy
        with teslapy.Tesla(TESLA_EMAIL) as tesla:
            vehicles = tesla.vehicle_list()
            if not vehicles:
                log(f"Wake failed [{reason}]: no vehicles found")
                # Set cooldown for this reason
                if reason == 'solar':
                    state.last_wake_attempt_solar = now
                else:
                    state.last_wake_attempt_manual = now
                return False

            vehicle = vehicles[0]
            log(f"Escalation [{reason}]: sending Tesla API wake...")
            vehicle.sync_wake_up()

            # Set cooldown for this reason
            if reason == 'solar':
                state.last_wake_attempt_solar = now
            else:
                state.last_wake_attempt_manual = now

            log("Wake request sent successfully")
            return True
    except Exception as e:
        log(f"Wake failed [{reason}]: {e}")
        # Set cooldown for this reason
        if reason == 'solar':
            state.last_wake_attempt_solar = now
        else:
            state.last_wake_attempt_manual = now
        return False

# -------------------------------
# BLE helpers
# -------------------------------
def ble_allowed():
    """Check if BLE command is allowed (cooldown + backoff + one per loop)."""
    now = time.time()
    if state.ble_command_this_loop:
        return False
    if now < state.ble_backoff_until:
        return False
    if (now - state.last_ble_time) < BLE_COOLDOWN:
        return False
    return True


def run_tesla_control(cmd):
    """Execute tesla-control command, either via BLE relay or locally."""
    if BLE_RELAY_ENABLED:
        return run_tesla_control_via_relay(cmd)
    else:
        return run_tesla_control_local(cmd)


def run_tesla_control_local(cmd):
    """Original local BLE execution (fallback if relay disabled)."""
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
        command = None
        args = []
        skip_next = False

        for part in cmd:
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
            return False, "could not parse command from cmd list"

        # Send to relay
        response = requests.post(
            f"{BLE_RELAY_URL}/ble/command",
            json={'command': command, 'args': args},
            timeout=60  # Allow for BLE timeout + network
        )

        data = response.json()
        success = data.get('success', False)
        output = data.get('output', '')
        duration = data.get('duration', 0)

        # Log relay usage
        log(
            f"BLE relay: {command} {' '.join(str(a) for a in args)} "
            f"-> {'OK' if success else 'FAILED'} ({duration:.1f}s)"
        )

        return success, output.lower()

    except requests.exceptions.Timeout:
        return False, "relay timeout"
    except requests.exceptions.ConnectionError:
        return False, "relay connection failed - pi zero unreachable"
    except Exception as e:
        return False, f"relay error: {str(e)}"


def log_ble_failure_context():
    """Log diagnostic info to help debug BLE failures"""
    log(f"  └─ BLE fail count: {state.ble_fail_count}")
    log(f"  └─ MANUAL BLE fails: {state.manual_ble_fails}")

    if time.time() < state.ble_backoff_until:
        log(f"  └─ BLE backoff: {int(state.ble_backoff_until - time.time())}s remaining")
    else:
        log("  └─ No BLE backoff active")

    # Check if bluetooth adapter is up
    try:
        result = subprocess.run(['hciconfig'], capture_output=True, text=True, timeout=2)
        if result.returncode != 0:
            log("  └─ WARNING: Bluetooth adapter may be down")
    except Exception:
        pass


def ble_call(cmd, val=None, domain='infotainment'):
    """Execute a BLE command with gating and backoff."""
    if state.ble_command_this_loop:
        log(f"BLE >>> {cmd} skipped (already used BLE this loop)")
        return False

    if not ble_allowed():
        remaining = max(0, state.ble_backoff_until - time.time())
        if remaining > 0:
            log(f"BLE >>> {cmd} gated (backoff {remaining:.0f}s remaining)")
        else:
            log(f"BLE >>> {cmd} gated (cooldown)")
        return False

    # Only set to True if we're actually going to attempt BLE
    state.ble_attempted_this_loop = True

    args = ["tesla-control", "-domain", domain, "-ble", "-vin", VIN, "-key-file", KEY_FILE, cmd]
    if val is not None:
        args.append(str(val))

    log(f"BLE >>> {cmd} {val if val else ''} ({domain})")
    ok, out = run_tesla_control(args)

    state.ble_command_this_loop = True
    state.last_ble_time = time.time()

    # Check for BLE connection errors BEFORE checking for generic "already" pattern
    if "already connected to the maximum" in out:
        log("BLE >>> Too many BLE connections")
        log_ble_failure_context()
        state.ble_fail_count += 1
        backoff_time = BLE_BACKOFF_INITIAL * min(state.ble_fail_count, 4)
        backoff_time = min(backoff_time, BLE_MAX_BACKOFF)
        state.ble_backoff_until = time.time() + backoff_time
        return False

    if ok or "already" in out or "is_charging" in out or "not_charging" in out:
        log("BLE >>> OK")
        state.ble_fail_count = 0
        return True

    # Handle failures
    state.ble_fail_count += 1
    backoff_time = BLE_BACKOFF_INITIAL * min(state.ble_fail_count, 4)
    backoff_time = min(backoff_time, BLE_MAX_BACKOFF)

    if "maximum number of ble" in out or "too many ble" in out:
        log("BLE >>> Too many BLE connections")
        log_ble_failure_context()
        state.ble_backoff_until = time.time() + backoff_time
    elif "context deadline" in out or "not in bluetooth range" in out:
        log("BLE >>> Car not in range or timeout")
        log_ble_failure_context()
        state.ble_backoff_until = time.time() + 30
    else:
        log(f"BLE >>> FAILED: {out[:120]}")
        log_ble_failure_context()
        state.ble_backoff_until = time.time() + backoff_time

    return False


# -------------------------------
# High-level BLE actions
# -------------------------------
def set_charge_limit(percent):
    """Set charge limit - uses cache to avoid redundant BLE calls."""
    if state.last_charge_limit_set == percent:
        return True
    if ble_call('charging-set-limit', percent):
        state.last_charge_limit_set = percent
        return True
    return False


def set_charging_amps(amps):
    """Set charging amps via BLE."""
    if ble_call('charging-set-amps', amps):
        state.current_amps = amps
        if amps > state.session_peak_amps:
            state.session_peak_amps = amps
        return True
    return False


def start_charging():
    """Start charging via BLE. Updates cached state to prevent spam."""
    if ble_call('charging-start'):
        state.cached_charging_state = 'Charging'  # SYNC LOCAL STATE
        return True
    return False


def stop_charging():
    """Stop charging via BLE. Updates cached state to prevent spam."""
    if ble_call('charging-stop'):
        state.current_amps = 0
        state.cached_charging_state = 'Stopped'  # SYNC LOCAL STATE
        return True
    return False


# -------------------------------
# Charging logic
# -------------------------------
def calculate_target_amps(excess_watts, current_amps):
    """Calculate target amps by adding excess-based delta to current charging.

    Rate-limits increases to MAX_AMP_STEP per loop to allow measurements to catch up.
    Decreases are not rate-limited to quickly reduce grid imports.
    """
    delta = int(excess_watts / VOLTAGE)

    # Rate-limit increases only (decreases can be immediate to avoid grid import)
    if delta > MAX_AMP_STEP:
        delta = MAX_AMP_STEP

    target = current_amps + delta
    return max(MIN_AMPS, min(target, MAX_AMPS))


# -------------------------------
# Main loop
# -------------------------------
def main():
    print(f"[STARTUP] SOLAR CHARGER VERSION: {VERSION}")
    print(f"[STARTUP] AUTH CACHE: {auth_cache_status(CACHE_FILE)}  (path={CACHE_FILE})")
    print(f"[STARTUP] KEY FILE EXISTS: {os.path.exists(KEY_FILE)}  (path={KEY_FILE})")

    log("=" * 60)
    log(f"SOLAR CHARGER {VERSION} (TWC Fork: no GPS fallback)")
    log("=" * 60)
    log(f"SOLAR_API_BASE resolved to: {SOLAR_API_BASE}")
    log(f"Solar API: {PI2_SOLAR_URL}")
    log(f"TWC Monitor API: {TWC_MONITOR_URL}")
    log(f"Loop interval: {LOOP_INTERVAL}s")
    log(f"BLE_COOLDOWN: {BLE_COOLDOWN}s, BLE_BACKOFF: {BLE_BACKOFF_INITIAL}s, MAX: {BLE_MAX_BACKOFF}s")
    log(f"Wake escalation: after {BLE_FAILS_BEFORE_WAKE} fails, cooldown {WAKE_COOLDOWN_SEC}s")
    log(f"Smoothing: {SMOOTH_WINDOW} samples, Stability: {AMP_STABILITY_COUNT} loops")
    log(f"TWC Disconnect: Auto-reset to {MAX_AMPS}A enabled")
    log(f"Emergency fallback runtime: {int(MAX_EMERGENCY_RUNTIME/60)} minutes")
    log(f"Emergency telemetry refresh: {EMERGENCY_STATUS_INTERVAL}s")
    log("TWC FORK: Home detection via TWC only (no GPS fallback)")
    log("=" * 60)

    # Initial Tesla status (TWC fork: 2-tuple return)
    battery, charging_state = get_tesla_status()

    # Sync current_amps from TWC if car is already charging (cold start recovery)
    if charging_state == 'Charging':
        twc_amps = get_twc_current_amps()
        if twc_amps is not None and twc_amps >= MIN_AMPS:
            state.current_amps = int(twc_amps)
            log(f"Cold start: synced current_amps from TWC = {state.current_amps}A")

    loop_count = 0

    while True:
        loop_start_ts = time.time()
        loop_count += 1
        state.ble_command_this_loop = False
        state.ble_attempted_this_loop = False
        state.grid_charge_warning_amps = None  # Reset each loop, set if detected
        mode = "UNKNOWN"
        log(f"\n--- Loop {loop_count} ---")

        # ========================================
        # 1) TWC CONNECTION CHECK
        # ========================================
        twc_state = get_twc_connected_safe()

        if state.last_twc_state is True and twc_state is False:
            # --- SESSION END ---
            if state.session_start_ts is not None:
                session_duration = time.time() - state.session_start_ts
                log(f"📊 SESSION ENDED: {int(session_duration/60)}min, peak {state.session_peak_amps}A")

            state.session_start_ts = None
            state.session_peak_amps = 0

            log(f"🔌 TWC DISCONNECT EDGE - normalize amps to {MAX_AMPS}A (destination-friendly)")

            if ble_allowed():
                ok = set_charging_amps(MAX_AMPS)
                if not ok:
                    state.pending_disconnect_amp_normalization = True
                    state.pending_disconnect_reason = "BLE attempt failed on disconnect edge"
                    log("  └─ Disconnect normalize failed; will retry once on next connect")
            else:
                state.pending_disconnect_amp_normalization = True
                state.pending_disconnect_reason = "BLE gated on disconnect edge"
                log("  └─ Disconnect normalize gated; will retry once on next connect")

            # Session-scoped resets (3.6.8 parity)
            state.manual_ble_fails = 0
            state.ble_fail_count = 0
            state.ble_backoff_until = 0.0
            state.emergency_start_ts = None

        if state.last_twc_state is False and twc_state is True:
            state.session_start_ts = time.time()
            state.session_peak_amps = 0
            log("📊 SESSION STARTED: tracking begins")
            log(f"🔋 New session: resetting BLE + emergency state")

            # One-time retry of disconnect normalization if needed
            if state.pending_disconnect_amp_normalization:
                log(f"🔁 Pending disconnect normalize retry ({state.pending_disconnect_reason})")
                if ble_allowed():
                    ok = set_charging_amps(MAX_AMPS)
                    if ok:
                        log("  └─ Pending normalize retry succeeded")
                    else:
                        log("  └─ Pending normalize retry failed")
                else:
                    log("  └─ Pending normalize retry gated")

                state.pending_disconnect_amp_normalization = False
                state.pending_disconnect_reason = None

        state.last_twc_state = twc_state

        if twc_state is False:
            log("TWC: Not connected -> AWAY mode")
            state.night_stop_sent = False
            state.manual_ble_fails = 0
            state.ble_fail_count = 0
            state.emergency_start_ts = None

            # Track night mode even while away
            solar = get_solar_data()
            prod_smooth = 0
            excess_val = 0
            if solar:
                production = solar['production']
                excess_val = solar.get('excess', 0)
                state.production_window.append(production)
                prod_smooth = sum(state.production_window) / len(state.production_window)
                now_ts = time.time()
                if prod_smooth < MIN_SOLAR_PRODUCTION:
                    if state.last_low_prod_time is None:
                        state.last_low_prod_time = now_ts
                        log(f"AWAY: Low production detected, night timer started")
                    else:
                        elapsed = now_ts - state.last_low_prod_time
                        if elapsed >= SUSTAINED_NIGHT_SEC:
                            log(f"AWAY: Night mode ready (low prod for {int(elapsed)}s)")
                        else:
                            log(f"AWAY: Night timer {int(elapsed)}s / {SUSTAINED_NIGHT_SEC}s")
                else:
                    if state.last_low_prod_time is not None:
                        log("AWAY: Production recovered, night timer reset")
                    state.last_low_prod_time = None

            update_dashboard_status("AWAY", 0, 0, state.cached_battery, excess_val, prod_smooth, 'Disconnected')
            time.sleep(LOOP_INTERVAL)
            continue

        # TWC fork: If TWC unreachable (None), use cached state instead of GPS fallback
        if twc_state is None:
            log("TWC: Unreachable -> using cached TWC state")
            twc_state = state.twc_cache.get('value')
            if twc_state is None:
                log("TWC: No cached state available -> AWAY mode (safe default)")
                state.night_stop_sent = False
                state.manual_ble_fails = 0
                state.ble_fail_count = 0
                state.emergency_start_ts = None

                update_dashboard_status("AWAY", 0, 0, state.cached_battery, 0, 0, 'TWC Unreachable')
                time.sleep(LOOP_INTERVAL)
                continue
            elif twc_state is False:
                # Cached state was disconnected - treat as AWAY mode
                log("TWC: Cached state was disconnected -> AWAY mode")
                state.night_stop_sent = False
                state.manual_ble_fails = 0
                state.ble_fail_count = 0
                state.emergency_start_ts = None

                update_dashboard_status("AWAY", 0, 0, state.cached_battery, 0, 0, 'Disconnected (cached)')
                time.sleep(LOOP_INTERVAL)
                continue
            else:
                log("TWC: Using cached state: connected")
                # Continue with cached connected state

        # Ensure fresh Tesla status when plugged in (TWC fork: 2-tuple return)
        now_ts = time.time()
        if state.cached_battery is None or (now_ts - state.cached_ts) >= STATUS_CHECK_INTERVAL:
            battery, charging_state = get_tesla_status()

        # ========================================
        # 2) MANUAL MODE CHECK (before night!)
        # ========================================
        dashboard_config = get_charging_config()
        dashboard_mode = dashboard_config.get('mode', 'SOLAR')

        # ========================================
        # 2a) SOLAR TAKEOVER CHECK
        # ========================================
        # If user requested solar takeover via dashboard button, immediately take control
        if dashboard_config.get('solar_takeover_requested', False):
            log("☀️ SOLAR TAKEOVER: User requested solar control via dashboard")
            # Send BLE command to set minimum amps - this kicks us into control mode
            if set_charging_amps(MIN_AMPS):
                log(f"☀️ SOLAR TAKEOVER: Set to {MIN_AMPS}A - script now controlling")
                clear_solar_takeover()  # Clear the flag
                state.grid_charge_warning_amps = None  # Clear the warning
            else:
                log("☀️ SOLAR TAKEOVER: BLE command failed - will retry next loop")
            # Continue with normal loop - script will now track solar

        if dashboard_mode == 'MANUAL':
            if not state.last_manual_state:
                log("MODE: MANUAL activated - overriding night/solar mode")
                state.last_manual_state = True
                state.last_charge_limit_set = None
                state.manual_ble_fails = 0

            mode = 'MANUAL'
            state.night_stop_sent = False

            # Reset emergency tracking if manual is activated
            state.emergency_start_ts = None

            # Get fresh battery if needed (TWC fork: 2-tuple return)
            now_ts = time.time()
            if (now_ts - state.last_status_check) >= STATUS_CHECK_INTERVAL:
                battery, charging_state = get_tesla_status()
            battery = state.cached_battery or 50
            charging_state = state.cached_charging_state

            log(f"MODE: MANUAL - Charging at MAX to {BATTERY_TARGET}%")

            # Skip BLE commands if charging is complete (car reached target)
            if charging_state == 'Complete':
                log("MANUAL: Charging complete - skipping BLE commands")
                ble_succeeded = True
            elif state.current_amps != MAX_AMPS:
                ble_succeeded = set_charging_amps(MAX_AMPS)
            elif charging_state != 'Charging' and ble_allowed():
                ble_succeeded = start_charging()
            else:
                ble_succeeded = True

            if ble_succeeded:
                state.manual_ble_fails = 0
            elif state.ble_attempted_this_loop:
                state.manual_ble_fails += 1
                log(f"MANUAL BLE fail streak: {state.manual_ble_fails}")

                # Fast wake: first fail + vehicle asleep = wake immediately and retry
                if state.manual_ble_fails == 1 and not state.cached_vehicle_online:
                    log("MANUAL: Vehicle asleep -> immediate wake + retry")
                    if wake_vehicle_safe('manual'):
                        time.sleep(20)  # Wait for car to fully wake (BLE takes longer than API)
                        state.ble_command_this_loop = False
                        state.ble_backoff_until = 0
                        if set_charging_amps(MAX_AMPS):
                            state.manual_ble_fails = 0

            if twc_state is True and state.manual_ble_fails >= BLE_FAILS_BEFORE_WAKE:
                log(f"MANUAL: BLE failed {state.manual_ble_fails}x while connected - escalating to API wake")
                wake_vehicle_safe('manual')
                log("MANUAL wake escalation attempted; resetting BLE failure counters")
                state.manual_ble_fails = 0
                state.ble_fail_count = 0

            solar = get_solar_data()
            if solar:
                update_dashboard_status(
                    mode, state.current_amps, MAX_AMPS, battery,
                    solar['excess'], solar['production'], charging_state or 'Charging'
                )
            else:
                update_dashboard_status(
                    mode, state.current_amps, MAX_AMPS, battery,
                    0, 0, charging_state or 'Charging'
                )

            log(f"Loop duration: {time.time() - loop_start_ts:.1f}s")
            time.sleep(LOOP_INTERVAL)
            continue
        else:
            if state.last_manual_state:
                log("MODE: MANUAL deactivated - returning to SOLAR mode")
                state.last_manual_state = False
                state.manual_ble_fails = 0

        # =====================================================================
        # 2.5) EMERGENCY OVERRIDE (Correct Priority + Hybrid Exit)
        # =====================================================================
        battery = state.cached_battery or 50
        charging_state = state.cached_charging_state

        if battery is not None and battery < BATTERY_EMERGENCY:
            mode = 'EMERGENCY'

            if state.emergency_start_ts is None:
                state.emergency_start_ts = time.time()
                log("EMERGENCY: entered (tracking start time)")

            elapsed = time.time() - state.emergency_start_ts
            remaining = max(0, MAX_EMERGENCY_RUNTIME - elapsed)

            log(
                f"MODE: EMERGENCY - Battery {battery}% < {BATTERY_EMERGENCY}% "
                f"(elapsed {int(elapsed)}s, remaining {int(remaining)}s)"
            )

            # TWC fork: 2-tuple return
            if (time.time() - state.cached_ts) >= EMERGENCY_STATUS_INTERVAL:
                log("EMERGENCY: forcing fresh Tesla status check")
                battery, charging_state = get_tesla_status()
                battery = state.cached_battery or 50
                charging_state = state.cached_charging_state

                if battery >= BATTERY_EMERGENCY:
                    log(f"EMERGENCY: battery recovered to {battery}% (>= {BATTERY_EMERGENCY}%) -> exiting emergency")
                    state.emergency_start_ts = None

            if state.emergency_start_ts is not None:
                if elapsed >= MAX_EMERGENCY_RUNTIME:
                    log("EMERGENCY: fallback runtime reached -> exiting emergency (conservative)")
                    state.emergency_start_ts = None
                else:
                    if state.current_amps != MAX_AMPS:
                        if ble_allowed():
                            set_charging_amps(MAX_AMPS)
                        else:
                            log("EMERGENCY: need MAX amps but BLE gated; will retry next loop")
                    elif charging_state != 'Charging':
                        if ble_allowed():
                            start_charging()
                        else:
                            log("EMERGENCY: need to start charging but BLE gated; will retry next loop")
                    elif state.last_charge_limit_set != BATTERY_TARGET:
                        if ble_allowed():
                            set_charge_limit(BATTERY_TARGET)
                        else:
                            log("EMERGENCY: need to set limit but BLE gated; will retry next loop")

                    # EMERGENCY verify actual current via TWC (v3.6.9 behavior)
                    twc_amps = get_twc_current_amps()

                    if twc_amps is not None:
                        if twc_amps >= 1 and state.cached_charging_state != 'Charging':
                            charging_state = 'Charging'

                        if (state.current_amps == MAX_AMPS
                                and state.cached_charging_state == 'Charging'
                                and twc_amps < (MAX_AMPS - 5)):
                            log(
                                f"⚠️ EMERGENCY: TWC shows {twc_amps:.1f}A but expected ~{MAX_AMPS}A. "
                                f"Will re-assert 48A/start on next allowed loop."
                            )

                    if twc_amps is not None and twc_amps < (MAX_AMPS - 5):
                        if ble_allowed() and not state.ble_command_this_loop:
                            set_charging_amps(MAX_AMPS)
                        elif not ble_allowed():
                            log("EMERGENCY: TWC amps low but BLE gated; will retry next loop")

                    solar = get_solar_data()
                    if solar:
                        update_dashboard_status(
                            mode, state.current_amps, MAX_AMPS, battery,
                            solar['excess'], solar['production'], 'Charging'
                        )
                    else:
                        update_dashboard_status(
                            mode, state.current_amps, MAX_AMPS, battery,
                            0, 0, 'Charging'
                        )

                    log(f"Loop duration: {time.time() - loop_start_ts:.1f}s")
                    time.sleep(LOOP_INTERVAL)
                    continue
        else:
            state.emergency_start_ts = None

        # ========================================
        # 3) GET SOLAR DATA & SMOOTH
        # ========================================
        solar = get_solar_data()
        if solar is None:
            log(f"Sleeping {LOOP_INTERVAL}s (mode={mode}, amps={state.current_amps})")
            time.sleep(LOOP_INTERVAL)
            continue

        production = solar['production']
        excess = solar['excess']
        state.production_window.append(production)
        state.excess_window.append(excess)
        prod_smooth = sum(state.production_window) / len(state.production_window)
        excess_smooth = sum(state.excess_window) / len(state.excess_window)
        log(
            f"Solar: {production:.0f}W prod, {excess:.0f}W excess "
            f"(smoothed: {prod_smooth:.0f}W / {excess_smooth:.0f}W)"
        )

        # ========================================
        # 4) NIGHT DETECTION (with freshness check)
        # ========================================
        now_ts = time.time()
        if prod_smooth < MIN_SOLAR_PRODUCTION:
            if state.last_low_prod_time is None:
                state.last_low_prod_time = now_ts
                log(f"Low production detected, starting {SUSTAINED_NIGHT_SEC}s timer...")
            elif (now_ts - state.last_low_prod_time) >= SUSTAINED_NIGHT_SEC:
                mode = 'NIGHT'

                if not state.night_stop_sent:
                    log(f"Night mode: production below {MIN_SOLAR_PRODUCTION}W for {SUSTAINED_NIGHT_SEC}s")

                    # ESCAPE HATCH 1: TWC shows no current = not charging = done
                    twc_amps = get_twc_current_amps()
                    if twc_amps is not None and twc_amps < 0.5:
                        log(f"Night stop: TWC shows {twc_amps:.1f}A (no current) - marking complete")
                        state.night_stop_sent = True

                    # ESCAPE HATCH 2: Already at 0A = not charging = done
                    elif state.current_amps == 0:
                        log("Night stop: Already at 0A - marking complete")
                        state.night_stop_sent = True

                    # ESCAPE HATCH 3: Fresh API data says not charging = done
                    else:
                        state_age = now_ts - state.last_status_check if state.last_status_check else 9999
                        charging_state_fresh = state_age < STATUS_CHECK_INTERVAL * 1.5

                        if charging_state_fresh and state.cached_charging_state != 'Charging':
                            log("Night stop: car already not charging (fresh data)")
                            state.night_stop_sent = True
                        elif ble_allowed():
                            if stop_charging():
                                log("Night stop: BLE stop succeeded")
                                state.night_stop_sent = True
                            else:
                                log("Night stop: BLE stop failed; will retry next loop")
                        else:
                            log("Night stop: BLE not allowed; will retry next loop")
                else:
                    # Only check for drift if we thought we were charging
                    if state.current_amps > 0:
                        twc_amps = get_twc_current_amps()
                        if twc_amps is not None and twc_amps > 0.5:
                            log(f"⚠️ Night mode: TWC shows {twc_amps:.1f}A still flowing - retrying stop")
                            state.night_stop_sent = False
                        else:
                            log("Night mode: idle (charging stopped)")
                    else:
                        log("Night mode: idle (not charging)")

                update_dashboard_status(mode, 0, 0, state.cached_battery, excess_smooth, prod_smooth, 'Stopped')
                time.sleep(LOOP_INTERVAL)
                continue
            else:
                remaining = SUSTAINED_NIGHT_SEC - (now_ts - state.last_low_prod_time)
                log(f"Low production: {remaining:.0f}s until night mode")
        else:
            if state.last_low_prod_time is not None:
                log("Production recovered, resetting night timer")
            state.last_low_prod_time = None
            state.night_stop_sent = False

        # ========================================
        # 5) PERIODIC TESLA STATUS (TWC fork: 2-tuple return)
        # ========================================
        if (now_ts - state.last_status_check) >= STATUS_CHECK_INTERVAL:
            battery, charging_state = get_tesla_status()

        battery = state.cached_battery or 50
        charging_state = state.cached_charging_state

        # ========================================
        # 7) SOLAR MODE
        # ========================================
        mode = 'SOLAR'

        # [NEW] High Solar Wake-Up
        # If we have strong sustained solar excess but the car is not charging,
        # and BLE is currently blocked, the car may be in deep sleep.
        # Wake once (cooldown protected) to allow BLE charging.
        # [NEW] High Solar Wake-Up
        # SOLAR WAKE — must run before any BLE
        if (
            excess_smooth > 500 and
            charging_state != 'Charging' and
            twc_state is True and
            state.ble_fail_count >= 2
        ):
            if wake_vehicle_safe('solar'):
                log(
                    f"WAKE_SOLAR excess_smooth={int(excess_smooth)}W "
                    f"battery={battery}% charging_state={charging_state} "
                    f"ble_fails={state.ble_fail_count}"
                )
                log("SOLAR: Wake sent, skipping BLE this loop")
                time.sleep(LOOP_INTERVAL)
                continue

        raw_target = calculate_target_amps(excess_smooth, state.current_amps)
        banded_target = (raw_target // AMP_STABILITY_BAND) * AMP_STABILITY_BAND
        banded_target = max(MIN_AMPS, banded_target)
        log(f"Target: {raw_target}A raw -> {banded_target}A banded (current: {state.current_amps}A)")

        state.amp_target_history.append(banded_target)

        if (len(state.amp_target_history) >= AMP_STABILITY_COUNT
                and all(a == banded_target for a in state.amp_target_history)):
            if abs(banded_target - state.current_amps) >= AMP_CHANGE_THRESHOLD:
                if excess_smooth <= 0 and state.current_amps == 0:
                    twc_amps = get_twc_current_amps()
                    # Only warn if TWC shows significantly more than MIN_AMPS
                    # If TWC shows ~6A, that's expected for solar mode with no excess
                    if twc_amps is not None and twc_amps > (MIN_AMPS + 3):
                        log(f"⚠️ WARNING: TWC shows {twc_amps:.1f}A but script not controlling - external charge?")
                        state.grid_charge_warning_amps = twc_amps
                    else:
                        state.grid_charge_warning_amps = None
                        if twc_amps is not None and twc_amps > 1.0:
                            # TWC at low amps (~6A) - sync state to match
                            log(f"TWC shows {twc_amps:.1f}A (near MIN_AMPS) - syncing state")
                            state.current_amps = MIN_AMPS
                    log(f"Stable target {banded_target}A but no solar excess - skipping BLE")
                else:
                    log(
                        f"Stable target {banded_target}A differs by "
                        f"{abs(banded_target - state.current_amps)}A - adjusting"
                    )
                    if state.current_amps != banded_target:
                        set_charging_amps(banded_target)
                    elif charging_state != 'Charging' and ble_allowed():
                        start_charging()
                    elif state.last_charge_limit_set != BATTERY_TARGET and ble_allowed():
                        set_charge_limit(BATTERY_TARGET)
            else:
                log(f"Stable at {state.current_amps}A, target {banded_target}A within threshold")
        else:
            log(
                f"Building stability: {len(state.amp_target_history)}/"
                f"{AMP_STABILITY_COUNT} -> {list(state.amp_target_history)}"
            )

        if state.current_amps > 0 and charging_state not in ('Charging', 'Complete') and ble_allowed():
            log("Car not charging but amps > 0 -> starting charging")
            start_charging()

        if state.current_amps > 0 and charging_state == 'Charging':
            twc_amps = get_twc_current_amps()
            if twc_amps is not None and abs(twc_amps - state.current_amps) > 5:
                log(f"⚠️ SOLAR: TWC shows {twc_amps:.1f}A but expected ~{state.current_amps}A (drift detected)")

        # ========================================
        # 8) UPDATE DASHBOARD
        # ========================================
        update_dashboard_status(
            mode, state.current_amps, banded_target, battery,
            excess_smooth, prod_smooth, charging_state or 'Unknown'
        )

        log(f"Sleeping {LOOP_INTERVAL}s (mode={mode}, amps={state.current_amps})")
        log(f"Loop duration: {time.time() - loop_start_ts:.1f}s")
        time.sleep(LOOP_INTERVAL)


if __name__ == "__main__":
    main()
