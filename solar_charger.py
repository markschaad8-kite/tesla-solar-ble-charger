#!/usr/bin/env python3
"""
================================================================================
Solar Charger — v4.0.1 - Restored explicit TWC edge semantics + session lifecycle guarantees
Stage 1 Structural Refactor + restored edge-case semantics from v3.6.8
================================================================================

WHY v4.0.0 EXISTS
-----------------
This release introduces a **Stage 1 refactor**:
- All mutable runtime globals are consolidated into a single `ChargerState` object
- Single-file architecture preserved
- Control flow, timing, BLE semantics, Tesla API usage, and logic are unchanged
- This refactor is structural only and intentionally conservative

RATIONALE
---------
This change reduces cognitive load, makes safety invariants easier to reason about,
and prepares the codebase for future feature work (e.g. SOLAR-mode wake escalation)
without increasing regression risk.

================================================================================
"""

VERSION = "v4.0.1"

import time
import math
import subprocess
import requests
import os
from datetime import datetime
from collections import deque
from dataclasses import dataclass, field
from typing import Optional, Deque, Dict, Any


# -------------------------------
# CONFIG (USER EDITABLE)
# -------------------------------
# --- PERSONAL VEHICLE DATA ---
VIN = "YOUR_VIN_HERE"               # <--- UPDATE THIS
TESLA_EMAIL = "your_email@example.com"  # <--- UPDATE THIS

# --- FILE PATHS (Container defaults) ---
KEY_FILE = "/app/private.pem"       # Path to your private key inside container
CACHE_FILE = "/app/cache.json"      # Path to your token cache inside container

# --- NETWORK CONFIG ---
# IP address of the device hosting the Solar API and TWC Monitor
LOCAL_SERVER_IP = "192.168.1.XXX"   # <--- UPDATE THIS

# URLs for local services
# Assumes Envoy/Solar data is on port 8080 and TWC Monitor on port 5002
SOLAR_DATA_URL = f"http://{LOCAL_SERVER_IP}:8080/api/envoy_data"
CONFIG_URL = f"http://{LOCAL_SERVER_IP}:8080/api/charging/config"
STATUS_URL = f"http://{LOCAL_SERVER_IP}:8080/api/set_charger_status"
TWC_MONITOR_URL = f"http://{LOCAL_SERVER_IP}:5002/api/twc/vehicle_connected"

# --- TWC SETTINGS ---
TWC_CACHE_TTL = 15
TWC_STALE_THRESHOLD = 90

# --- LOCATION (For Home Detection) ---
HOME_LAT = 0.0000                   # <--- UPDATE THIS (Latitude)
HOME_LON = 0.0000                   # <--- UPDATE THIS (Longitude)
HOME_RADIUS_MILES = 0.25

# --- CHARGING PARAMETERS ---
VOLTAGE = 240
MIN_SOLAR_PRODUCTION = 100
MIN_AMPS = 6
MAX_AMPS = 48                       # <-----UPDATE TO YOUR HOME CHARGER SPECS
BATTERY_EMERGENCY = 50              # Charge immediately if below this %
BATTERY_TARGET = 80                 # Normal daily limit

# --- TIMING & LOGIC ---
LOOP_INTERVAL = 30
STATUS_CHECK_INTERVAL = 300
CACHE_TTL = 600

AMP_CHANGE_THRESHOLD = 2
AMP_STABILITY_COUNT = 2
AMP_STABILITY_BAND = 3
SMOOTH_WINDOW = 4
SUSTAINED_NIGHT_SEC = 600           # Time to wait before entering NIGHT mode

# --- BLE GATING ---
BLE_COOLDOWN = 12
BLE_BACKOFF_INITIAL = 60
BLE_MAX_BACKOFF = 3600

# Wake escalation (MANUAL mode only)
WAKE_COOLDOWN_SEC = 900             # 15 minutes
BLE_FAILS_BEFORE_WAKE = 3

# Hybrid emergency fallback runtime
MAX_EMERGENCY_RUNTIME = 90 * 60     # 90 minutes

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
    cached_is_home: Optional[bool] = None
    cached_charging_state: Optional[str] = None
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

    # Wake escalation state (MANUAL only)
    manual_ble_fails: int = 0
    last_wake_attempt: float = 0.0

    # Emergency tracking
    emergency_start_ts: Optional[float] = None

    # Session tracking
    session_start_ts: Optional[float] = None
    session_peak_amps: int = 0

    # --- v4.0.1: Explicit TWC edge semantics ---
    pending_disconnect_amp_normalization: bool = False
    pending_disconnect_reason: Optional[str] = None


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
def get_distance_miles(lat1, lon1, lat2, lon2):
    R = 3958.8
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    return R * c


# -------------------------------
# TWC Integration
# -------------------------------
def get_twc_connected_safe():
    now = time.time()
    if now - state.twc_cache['ts'] < TWC_CACHE_TTL and state.twc_cache['value'] is not None:
        return state.twc_cache['value']
    try:
        r = requests.get(TWC_MONITOR_URL, timeout=2.0)
        r.raise_for_status()
        j = r.json()
        data_age = j.get('data_age_seconds')
        if data_age and data_age > TWC_STALE_THRESHOLD:
            log(f"TWC data stale ({data_age}s old) -> falling back to GPS")
            return None
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
                log(f"TWC monitor unreachable: {e} -> falling back to GPS")
            state.twc_cache['value'] = None
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
        r = requests.get(SOLAR_DATA_URL, timeout=30)  # Verified: 30s timeout
        data = r.json()
        production = float(data.get('production_watts', 0) or 0)
        excess = float(data.get('excess_watts', 0) or 0)
        return {'production': production, 'excess': excess}
    except Exception as e:
        log(f"ERROR get_solar_data: {e}")
        return None


def get_charging_config():
    try:
        r = requests.get(CONFIG_URL, timeout=4)
        return r.json().get('mode', 'SOLAR')
    except:
        return 'SOLAR'


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
            'ble_backoff_remaining': max(0, int(state.ble_backoff_until - time.time()))
        }
        requests.post(STATUS_URL, json=payload, timeout=3)
    except Exception as e:
        log(f"ERROR updating dashboard: {e}")


# -------------------------------
# Tesla status (cached + TTL)
# -------------------------------
def get_tesla_status():
    now = time.time()
    if (now - state.cached_ts) < CACHE_TTL:
        return state.cached_battery, state.cached_is_home, state.cached_charging_state
    try:
        import teslapy
        with teslapy.Tesla(TESLA_EMAIL, cache_file=CACHE_FILE) as tesla:
            vehicles = tesla.vehicle_list()
            if not vehicles:
                log("No vehicles found (teslapy)")
                return state.cached_battery, state.cached_is_home, state.cached_charging_state
            vehicle = vehicles[0]
            if vehicle['state'] != 'online':
                log(f"Vehicle {vehicle['state']} - using cache")
                return state.cached_battery, state.cached_is_home, state.cached_charging_state
            data = vehicle.get_vehicle_data()
            lat = data['drive_state'].get('latitude')
            lon = data['drive_state'].get('longitude')
            if lat and lon:
                is_home = get_distance_miles(HOME_LAT, HOME_LON, lat, lon) < HOME_RADIUS_MILES
            else:
                is_home = state.cached_is_home
            charge_state = data.get('charge_state', {})
            battery = charge_state.get('battery_level', state.cached_battery)
            charging = charge_state.get('charging_state', state.cached_charging_state)

            # Only update cache on successful fetch
            state.cached_battery = battery
            state.cached_is_home = is_home
            state.cached_charging_state = charging
            state.cached_ts = now
            state.last_status_check = now

            log(f"Tesla: Battery={battery}%, Home={is_home}, State={charging}")
            return battery, is_home, charging
    except Exception as e:
        log(f"Tesla status error: {e}")
        return state.cached_battery, state.cached_is_home, state.cached_charging_state


# -------------------------------
# Wake escalation (MANUAL only)
# -------------------------------
def wake_vehicle_safe():
    """
    Wake car via Tesla API with cooldown.
    Only called from MANUAL mode escalation.
    Returns True if wake was attempted, False if skipped/failed.
    """
    now = time.time()
    remaining = WAKE_COOLDOWN_SEC - (now - state.last_wake_attempt)
    if remaining > 0:
        log(f"Wake skipped (cooldown {int(remaining)}s remaining)")
        return False

    try:
        import teslapy
        with teslapy.Tesla(TESLA_EMAIL) as tesla:
            vehicles = tesla.vehicle_list()
            if not vehicles:
                log("Wake failed: no vehicles found")
                state.last_wake_attempt = now  # Set cooldown anyway
                return False

            vehicle = vehicles[0]
            log("MANUAL escalation: sending Tesla API wake...")
            vehicle.sync_wake_up()
            state.last_wake_attempt = now
            log("Wake request sent successfully")
            return True
    except Exception as e:
        log(f"Wake failed: {e}")
        state.last_wake_attempt = now  # Set cooldown to prevent spam on repeated failures
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
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        out = (r.stdout + r.stderr).lower()
        return r.returncode == 0, out
    except Exception as e:
        return False, str(e)


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
    except:
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
def calculate_target_amps(excess_watts):
    target = MIN_AMPS
    if excess_watts > 0:
        target += int(excess_watts / VOLTAGE)
    return min(target, MAX_AMPS)


# -------------------------------
# Main loop
# -------------------------------
def main():
    print(f"[STARTUP] SOLAR CHARGER VERSION: {VERSION}")
    print(f"[STARTUP] AUTH CACHE: {auth_cache_status(CACHE_FILE)}  (path={CACHE_FILE})")
    print(f"[STARTUP] KEY FILE EXISTS: {os.path.exists(KEY_FILE)}  (path={KEY_FILE})")

    log("=" * 60)
    log(f"SOLAR CHARGER {VERSION} (Stage 1 Refactor: state object)")
    log("=" * 60)
    log(f"TWC Monitor: {TWC_MONITOR_URL}")
    log(f"Loop interval: {LOOP_INTERVAL}s")
    log(f"BLE_COOLDOWN: {BLE_COOLDOWN}s, BLE_BACKOFF: {BLE_BACKOFF_INITIAL}s, MAX: {BLE_MAX_BACKOFF}s")
    log(f"Wake escalation: after {BLE_FAILS_BEFORE_WAKE} fails, cooldown {WAKE_COOLDOWN_SEC}s")
    log(f"Smoothing: {SMOOTH_WINDOW} samples, Stability: {AMP_STABILITY_COUNT} loops")
    log(f"TWC Disconnect: Auto-reset to {MAX_AMPS}A enabled")
    log(f"Emergency fallback runtime: {int(MAX_EMERGENCY_RUNTIME/60)} minutes")
    log(f"Emergency telemetry refresh: {EMERGENCY_STATUS_INTERVAL}s")
    log("=" * 60)

    # Initial Tesla status
    battery, is_home, charging_state = get_tesla_status()
    if is_home is None:
        is_home = False

    loop_count = 0

    while True:
        loop_start_ts = time.time()
        loop_count += 1
        state.ble_command_this_loop = False
        state.ble_attempted_this_loop = False
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

        if twc_state is None:
            log("TWC: Unreachable -> using GPS fallback")
            battery, is_home, charging_state = get_tesla_status()
            if not is_home:
                log("GPS: Not home -> AWAY mode")
                state.night_stop_sent = False
                state.manual_ble_fails = 0
                state.ble_fail_count = 0
                state.emergency_start_ts = None

                update_dashboard_status("AWAY", 0, 0, battery, 0, 0, 'Away')
                time.sleep(LOOP_INTERVAL)
                continue

        # Ensure fresh Tesla status when plugged in
        now_ts = time.time()
        if state.cached_battery is None or (now_ts - state.cached_ts) >= STATUS_CHECK_INTERVAL:
            battery, is_home, charging_state = get_tesla_status()

        # ========================================
        # 2) MANUAL MODE CHECK (before night!)
        # ========================================
        dashboard_mode = get_charging_config()

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

            # Get fresh battery if needed
            now_ts = time.time()
            if (now_ts - state.last_status_check) >= STATUS_CHECK_INTERVAL:
                battery, is_home, charging_state = get_tesla_status()
                battery = state.cached_battery or 50
                charging_state = state.cached_charging_state

            log(f"MODE: MANUAL - Charging at MAX to {BATTERY_TARGET}%")

            ble_succeeded = False
            if state.current_amps != MAX_AMPS:
                ble_succeeded = set_charging_amps(MAX_AMPS)
            elif charging_state != 'Charging' and ble_allowed():
                ble_succeeded = start_charging()
            elif state.last_charge_limit_set != BATTERY_TARGET and ble_allowed():
                ble_succeeded = set_charge_limit(BATTERY_TARGET)
            else:
                ble_succeeded = True

            if ble_succeeded:
                state.manual_ble_fails = 0
            elif state.ble_attempted_this_loop:
                state.manual_ble_fails += 1
                log(f"MANUAL BLE fail streak: {state.manual_ble_fails}")

            if twc_state is True and state.manual_ble_fails >= BLE_FAILS_BEFORE_WAKE:
                log(f"MANUAL: BLE failed {state.manual_ble_fails}x while connected - escalating to API wake")
                wake_vehicle_safe()
                log("MANUAL wake escalation attempted; resetting BLE failure counters")
                state.manual_ble_fails = 0
                state.ble_fail_count = 0

            solar = get_solar_data()
            if solar:
                update_dashboard_status(mode, state.current_amps, MAX_AMPS, battery, solar['excess'], solar['production'], charging_state or 'Charging')
            else:
                update_dashboard_status(mode, state.current_amps, MAX_AMPS, battery, 0, 0, charging_state or 'Charging')

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

            log(f"MODE: EMERGENCY - Battery {battery}% < {BATTERY_EMERGENCY}% (elapsed {int(elapsed)}s, remaining {int(remaining)}s)")

            if (time.time() - state.cached_ts) >= EMERGENCY_STATUS_INTERVAL:
                log("EMERGENCY: forcing fresh Tesla status check")
                battery, is_home, charging_state = get_tesla_status()
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

                        if state.current_amps == MAX_AMPS and state.cached_charging_state == 'Charging' and twc_amps < (MAX_AMPS - 5):
                            log(f"⚠️ EMERGENCY: TWC shows {twc_amps:.1f}A but expected ~{MAX_AMPS}A. Will re-assert 48A/start on next allowed loop.")

                        if twc_amps is not None and twc_amps < (MAX_AMPS - 5):
                            if ble_allowed() and not state.ble_command_this_loop:
                                set_charging_amps(MAX_AMPS)
                            elif not ble_allowed():
                                log("EMERGENCY: TWC amps low but BLE gated; will retry next loop")

                    solar = get_solar_data()
                    if solar:
                        update_dashboard_status(mode, state.current_amps, MAX_AMPS, battery, solar['excess'], solar['production'], 'Charging')
                    else:
                        update_dashboard_status(mode, state.current_amps, MAX_AMPS, battery, 0, 0, 'Charging')

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
        log(f"Solar: {production:.0f}W prod, {excess:.0f}W excess (smoothed: {prod_smooth:.0f}W / {excess_smooth:.0f}W)")

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
                    log("Night mode: idle (charging already stopped)")

                twc_amps = get_twc_current_amps()
                if twc_amps is not None and twc_amps > 0.5:
                    log(f"⚠️ Night mode: TWC shows {twc_amps:.1f}A still flowing - retrying stop")
                    state.night_stop_sent = False

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
        # 5) PERIODIC TESLA STATUS
        # ========================================
        if (now_ts - state.last_status_check) >= STATUS_CHECK_INTERVAL:
            battery, is_home, charging_state = get_tesla_status()

        battery = state.cached_battery or 50
        charging_state = state.cached_charging_state

        # ========================================
        # 7) SOLAR MODE
        # ========================================
        mode = 'SOLAR'

        raw_target = calculate_target_amps(excess_smooth)
        banded_target = (raw_target // AMP_STABILITY_BAND) * AMP_STABILITY_BAND
        banded_target = max(MIN_AMPS, banded_target)
        log(f"Target: {raw_target}A raw -> {banded_target}A banded (current: {state.current_amps}A)")

        state.amp_target_history.append(banded_target)

        if len(state.amp_target_history) >= AMP_STABILITY_COUNT and all(a == banded_target for a in state.amp_target_history):
            if abs(banded_target - state.current_amps) >= AMP_CHANGE_THRESHOLD:
                if excess_smooth <= 0 and state.current_amps == 0:
                    log(f"Stable target {banded_target}A but no solar excess - skipping BLE")
                else:
                    log(f"Stable target {banded_target}A differs by {abs(banded_target - state.current_amps)}A - adjusting")
                    if state.current_amps != banded_target:
                        set_charging_amps(banded_target)
                    elif charging_state != 'Charging' and ble_allowed():
                        start_charging()
                    elif state.last_charge_limit_set != BATTERY_TARGET and ble_allowed():
                        set_charge_limit(BATTERY_TARGET)
                    else:
                        log(f"Stable at {state.current_amps}A, target {banded_target}A within threshold")
            else:
                log(f"Stable at {state.current_amps}A, target {banded_target}A within threshold")
        else:
            log(f"Building stability: {len(state.amp_target_history)}/{AMP_STABILITY_COUNT} -> {list(state.amp_target_history)}")

        if state.current_amps > 0 and charging_state != 'Charging' and ble_allowed():
            log("Car not charging but amps > 0 -> starting charging")
            start_charging()

        if state.current_amps > 0 and charging_state == 'Charging':
            twc_amps = get_twc_current_amps()
            if twc_amps is not None and abs(twc_amps - state.current_amps) > 5:
                log(f"⚠️ SOLAR: TWC shows {twc_amps:.1f}A but expected ~{state.current_amps}A (drift detected)")

        # ========================================
        # 8) UPDATE DASHBOARD
        # ========================================
        update_dashboard_status(mode, state.current_amps, banded_target, battery, excess_smooth, prod_smooth, charging_state or 'Unknown')

        log(f"Sleeping {LOOP_INTERVAL}s (mode={mode}, amps={state.current_amps})")
        log(f"Loop duration: {time.time() - loop_start_ts:.1f}s")
        time.sleep(LOOP_INTERVAL)


if __name__ == "__main__":
    main()
