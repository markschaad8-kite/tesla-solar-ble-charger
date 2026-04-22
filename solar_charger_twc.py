#!/usr/bin/env python3
"""
================================================================================
Solar Charger TWC Fork - v4.0.20-twc - Reset current_amps on session start (stale-48A fix)
Solar Charger TWC Fork - v4.0.19-twc - Suppress BLE when car complete at target in SOLAR
Solar Charger TWC Fork - v4.0.18-twc - Fix EMERGENCY exit/night/wake/session bugs
Solar Charger TWC Fork - v4.0.17-twc - Fix EMERGENCY fallthrough to SOLAR after 90min reset
Solar Charger TWC Fork - v4.0.16-twc - Smart calendar timing + 80% approval gate
Solar Charger TWC Fork - v4.0.15-twc - Code review fixes + BLE relay auth
Solar Charger TWC Fork - v4.0.14-twc - TWC stale data polling optimization
Solar Charger TWC Fork - v4.0.11-twc - Preconditioning detection (skip amp adjustments during precond)
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

v4.0.20-twc - Reset current_amps on session start (stale-48A fix)
- BUG FIX: Disconnect normalization set current_amps=48, which survived into the next
  session. If SOLAR calculated target=48 (strong sun), it saw "stable" and never sent
  a BLE command — leaving the car at its own default (e.g. 16A) for the entire session
  until solar fluctuation broke the deadlock.
- FIX: Reset current_amps=0 on SESSION STARTED (TWC connect edge), matching the pattern
  already used by EMERGENCY exit (line 1130) and CALENDAR exit (line 1380). SOLAR now
  always re-establishes explicit control from 6A upward on each new charge session.
- TRADE-OFF: ~5.5 min ramp-up from 6A→48A on plug-in during strong solar (11 loops at
  MAX_AMP_STEP=4). Excess solar is exported during ramp — not wasted, just not used for
  charging until SOLAR catches up.

v4.0.19-twc - Suppress BLE when car complete at target in SOLAR mode
- BUG FIX: SOLAR mode was sending amp-adjustment BLE commands and high-solar wake
  after car reached 80% ("Complete"), keeping the car awake unnecessarily.
- Added guard before high-solar wake: skip wake if Complete at/above target.
- Added guard inside stability block: skip set_charging_amps/set_charge_limit/
  start_charging if Complete at/above target. Resets current_amps to 0 (no BLE —
  purely in-memory) so next session starts with a clean baseline.
- Lines 1551-1560 (restart-charging if Complete below target) and disconnect
  normalization (48A reset on unplug) are unaffected.

v4.0.18-twc - Fix EMERGENCY exit/night/wake/session bugs (5 bugs fixed)
- BUG FIX (Critical): Battery recovery exit from EMERGENCY now issues `continue` to
  restart the loop instead of falling through to NIGHT mode. Observed twice in logs
  (Mar 03 15:53, Mar 04 07:56) — NIGHT-stop fired and halted charging while battery
  was 47-50%.
- BUG FIX: state.current_amps not reset on EMERGENCY exit caused SOLAR to immediately
  drop amps (48A -> 28A -> 6A) on the first post-EMERGENCY loop. Now resets to 0 on
  all EMERGENCY exit paths (matching CALENDAR exit pattern).
- BUG FIX: state.cached_battery not reset on new session connect — first loop could
  run SOLAR with the pre-session battery level, missing EMERGENCY detection for one
  full 30s loop (observed Mar 05 07:48).
- BUG FIX: night_stop_sent not cleared on EMERGENCY entry — if NIGHT fired before
  EMERGENCY resolved, night mode persisted after recovery and suppressed charging
  until sunrise.
- FEATURE: EMERGENCY wake escalation — after BLE_FAILS_BEFORE_WAKE consecutive BLE
  failures, escalates to API wake (matching MANUAL/CALENDAR behavior).

v4.0.17-twc - Fix EMERGENCY fallthrough to SOLAR after 90min reset
- BUG FIX: When EMERGENCY mode hit the 90-min timeout with battery still rising,
  it logged "continuing" and reset the timer but was missing a `continue` statement.
  This caused the loop to fall through into SOLAR logic for one iteration, sending
  a reduced SOLAR amp command instead of staying at 48A.

v4.0.16-twc - Smart calendar timing + 80% approval gate
- FEATURE: charge_after timing — CALENDAR mode waits until calculated start time
  instead of charging immediately when advisory is written. Falls through to SOLAR
  while waiting. All-day events assume 7 AM departure.
- FEATURE: 80% approval gate — targets >80% pause at 80% and wait for user approval
  via dashboard button. Auto-approves if <2 hours before event.
- FEATURE: CALENDAR_WAITING mode — visible on dashboard while waiting for charge_after
- REFACTOR: calendar_checker.py gains calculate_charge_after() and approve_above_80()

v4.0.15-twc - Code review fixes + BLE relay auth
- FIX: SOLAR_API_BASE default changed from old Pi 2 IP to http://localhost
- FIX: Emergency mode no longer defaults unknown battery to 50 (threshold boundary).
  Unknown battery (None) now skips emergency check entirely; inside emergency,
  unknown battery keeps charging as a safety measure.
- FIX: BLE relay now receives and uses -domain flag for tesla-control commands
- SECURITY: BLE relay API key authentication enabled. Charger sends X-API-Key header;
  relay rejects unauthenticated requests.
- REFACTOR: Duplicate BLE backoff calculation extracted to calculate_ble_backoff()
- FIX: TWC status URL now uses explicit TWC_STATUS_URL constant instead of string split
- FIX: Bare except: in relay check_bluetooth() narrowed to except Exception:
- CLEANUP: Backup/legacy files moved to backups/ subdirectory
- DOCS: CLAUDE.md updated to reflect v4.0.14-twc architecture (BLE relay, TWC fork,
  correct constants, Podman commands, removed GPS references)

v4.0.14-twc - TWC stale data polling optimization
- FIX: TWC stale data now updates cache timestamp to prevent repeated API calls
  during upstream lag events. Respects 15s cache TTL instead of polling every loop,
  reducing unnecessary load on TWC monitor during degraded conditions.

v4.0.13-twc - Wake cache consistency + auth cache structure fix
- BUG FIX: wake_vehicle_safe() now uses the same cache file path as get_tesla_status()
  to prevent silent auth failures during API wake attempts. Both functions now
  consistently use CACHE_FILE (/app/cache.json) for teslapy authentication.
- BUG FIX: auth_cache_status() now correctly checks the teslapy cache structure
  (nested under email -> sso -> tokens) instead of looking for tokens at root level.

v4.0.12-twc - Relay payload fix + reset helpers refactor
- BUG FIX: BLE relay was sending "-domain" as the command instead of the actual
  command (e.g., "charging-set-amps"). Fixed by passing structured payload directly
  to relay instead of parsing the arg list.
- REFACTOR: Consolidated repeated state reset patterns into two helper functions:
  - reset_away_mode_state(): For AWAY mode entries
  - reset_session_state(): For session boundaries (clears BLE backoff too)
- IMPROVEMENT: auth_cache_status() now uses proper JSON parsing instead of
  substring matching for more robust token validation.

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

VERSION = "v4.0.20-twc"

import time
import subprocess
import requests
import os
from datetime import datetime
from collections import deque
from dataclasses import dataclass, field
from typing import Optional, Deque, Dict, Any


# -------------------------------
# CONFIG (unchanged)
# -------------------------------
VIN = os.getenv("TESLA_VIN", "")
KEY_FILE = "/app/private.pem"
CACHE_FILE = "/app/cache.json"
TESLA_EMAIL = os.getenv("TESLA_EMAIL", "")

# -------------------------------
# NETWORK CONFIG (Stage 1 migration prep)
# -------------------------------
SOLAR_API_BASE = os.getenv(
    "SOLAR_API_BASE",
    "http://localhost"  # All services on pinasi (Pi 5) since Dec 2025 migration
)

PI2_SOLAR_URL = f"{SOLAR_API_BASE}:8080/api/envoy_data"
PI2_CONFIG_URL = f"{SOLAR_API_BASE}:8080/api/charging/config"
PI2_STATUS_URL = f"{SOLAR_API_BASE}:8080/api/set_charger_status"
TWC_MONITOR_URL = f"{SOLAR_API_BASE}:5002/api/twc/vehicle_connected"
TWC_STATUS_URL = f"{SOLAR_API_BASE}:5002/api/twc/status"

# -------------------------------
# BLE RELAY CONFIG (Pi Zero proxy)
# -------------------------------
BLE_RELAY_ENABLED = os.getenv("BLE_RELAY_ENABLED", "true").lower() == "true"
BLE_RELAY_HOST = os.getenv("BLE_RELAY_HOST", "SolarPiZero")
BLE_RELAY_PORT = int(os.getenv("BLE_RELAY_PORT", "5003"))
BLE_RELAY_URL = f"http://{BLE_RELAY_HOST}:{BLE_RELAY_PORT}"
BLE_RELAY_API_KEY = os.getenv("BLE_RELAY_API_KEY", "")

TWC_CACHE_TTL = 15
TWC_STALE_THRESHOLD = 90

# GPS constants REMOVED in TWC fork - TWC connection is authoritative for home detection

VOLTAGE = 240
MIN_SOLAR_PRODUCTION = 100
MIN_AMPS = 6
MAX_AMPS = 48
BATTERY_EMERGENCY = 50
DEFAULT_BATTERY_TARGET = 80

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
RELAY_UNREACHABLE_ALERT_THRESHOLD = 3

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
    cached_is_preconditioning: bool = False
    cached_vehicle_online: bool = True
    cached_ts: float = 0.0
    last_status_check: float = 0.0

    amp_target_history: Deque[int] = field(default_factory=lambda: deque(maxlen=AMP_STABILITY_COUNT))
    production_window: Deque[float] = field(default_factory=lambda: deque(maxlen=SMOOTH_WINDOW))
    excess_window: Deque[float] = field(default_factory=lambda: deque(maxlen=SMOOTH_WINDOW))

    last_low_prod_time: Optional[float] = None
    night_stop_sent: bool = False
    last_manual_state: bool = False
    last_calendar_mode: bool = False
    calendar_reason: Optional[str] = None

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
    calendar_ble_fails: int = 0
    last_wake_attempt_manual: float = 0.0
    last_wake_attempt_solar: float = 0.0
    last_wake_attempt_calendar: float = 0.0

    # Emergency tracking
    emergency_start_ts: Optional[float] = None
    emergency_start_battery: Optional[int] = None

    # Session tracking
    session_start_ts: Optional[float] = None
    session_peak_amps: int = 0

    # --- v4.0.1: Explicit TWC edge semantics ---
    pending_disconnect_amp_normalization: bool = False
    pending_disconnect_reason: Optional[str] = None

    # --- v4.0.3: Dashboard warning flags ---
    grid_charge_warning_amps: Optional[float] = None
    relay_unreachable_streak: int = 0
    relay_unreachable_alert: bool = False

state = ChargerState()

# -------------------------------
# Helper: report Tesla OAuth token presence at startup
# -------------------------------
def auth_cache_status(cache_path: str) -> str:
    try:
        import json
        with open(cache_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        # teslapy cache structure: {email: {url: ..., sso: {access_token, refresh_token, ...}}}
        for email, email_data in data.items():
            if isinstance(email_data, dict):
                sso = email_data.get('sso', {})
                if 'access_token' in sso and 'refresh_token' in sso:
                    return "OK (tokens present)"
        return "MISSING TOKENS"
    except json.JSONDecodeError as e:
        return f"ERROR: cache file is not valid JSON ({e})"
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


def reset_away_mode_state():
    """Reset state flags when entering AWAY mode or safe-default fallback.
    Used on: TWC disconnected, TWC unreachable with no/disconnected cache."""
    state.night_stop_sent = False
    state.manual_ble_fails = 0
    state.ble_fail_count = 0
    state.emergency_start_ts = None
    state.emergency_start_battery = None


def reset_session_state():
    """Reset BLE + emergency state on session boundary (disconnect edge).
    Clears backoff in addition to the flags reset_away_mode_state clears,
    because a new physical session means the BLE backoff context is stale."""
    state.manual_ble_fails = 0
    state.ble_fail_count = 0
    state.ble_backoff_until = 0.0
    state.emergency_start_ts = None


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
            state.twc_cache['ts'] = now  # Update timestamp to prevent spam during stale periods
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
        r = requests.get(TWC_STATUS_URL, timeout=2.0)
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


def is_precondition_inhibit_active(config: dict) -> bool:
    """Check if dashboard precondition inhibit flag is still active (30 min window)"""
    inhibit_ts = config.get('precondition_inhibit_until', 0)
    return time.time() < inhibit_ts


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
            'grid_charge_warning_amps': state.grid_charge_warning_amps,
            'relay_unreachable_streak': state.relay_unreachable_streak,
            'relay_unreachable_alert': state.relay_unreachable_alert,
            'is_preconditioning': state.cached_is_preconditioning,
            'calendar_reason': state.calendar_reason
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
        with teslapy.Tesla(TESLA_EMAIL, cache_file=CACHE_FILE) as tesla:
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

            # Fetch preconditioning status from climate_state
            climate_state = data.get('climate_state', {})
            is_preconditioning = climate_state.get('is_preconditioning', False)

            # Only update cache on successful fetch
            state.cached_battery = battery
            state.cached_charging_state = charging
            state.cached_is_preconditioning = is_preconditioning
            state.cached_vehicle_online = True
            state.cached_ts = now
            state.last_status_check = now

            log(f"Tesla: Battery={battery}%, State={charging}, Precond={is_preconditioning}")
            return battery, charging
    except Exception as e:
        log(f"Tesla status error: {e}")
        return state.cached_battery, state.cached_charging_state


# -------------------------------
# Wake escalation (MANUAL only)
# -------------------------------
def _set_wake_cooldown(reason: str, now: float):
    """Set wake cooldown timestamp for the given reason."""
    if reason == 'solar':
        state.last_wake_attempt_solar = now
    elif reason == 'calendar':
        state.last_wake_attempt_calendar = now
    else:
        state.last_wake_attempt_manual = now


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
    elif reason == 'calendar':
        last_attempt = state.last_wake_attempt_calendar
    else:
        last_attempt = state.last_wake_attempt_manual

    remaining = WAKE_COOLDOWN_SEC - (now - last_attempt)
    if remaining > 0:
        log(f"Wake skipped [{reason}] (cooldown {int(remaining)}s remaining)")
        return False

    try:
        import teslapy
        with teslapy.Tesla(TESLA_EMAIL, cache_file=CACHE_FILE) as tesla:
            vehicles = tesla.vehicle_list()
            if not vehicles:
                log(f"Wake failed [{reason}]: no vehicles found")
                _set_wake_cooldown(reason, now)
                return False

            vehicle = vehicles[0]
            log(f"Escalation [{reason}]: sending Tesla API wake...")
            vehicle.sync_wake_up()

            _set_wake_cooldown(reason, now)

            log("Wake request sent successfully")
            return True
    except Exception as e:
        log(f"Wake failed [{reason}]: {e}")
        _set_wake_cooldown(reason, now)
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


def run_tesla_control(cmd, relay_command=None, relay_args=None, relay_domain='infotainment'):
    """Execute tesla-control command, either via BLE relay or locally.
    When relay is enabled, relay_command/relay_args/relay_domain are used directly
    instead of parsing the cmd list."""
    if BLE_RELAY_ENABLED:
        return run_tesla_control_via_relay(relay_command, relay_args, relay_domain)
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


def run_tesla_control_via_relay(command, args, domain='infotainment'):
    """
    Execute tesla-control via Pi Zero BLE relay.
    Receives the command, args, and domain directly — no parsing needed.
    """
    try:
        if not command:
            return False, "no command provided for relay"

        if args is None:
            args = []

        # Send to relay with domain for proper flag placement
        headers = {}
        if BLE_RELAY_API_KEY:
            headers['X-API-Key'] = BLE_RELAY_API_KEY
        response = requests.post(
            f"{BLE_RELAY_URL}/ble/command",
            json={'command': command, 'args': args, 'domain': domain},
            headers=headers,
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


def calculate_ble_backoff():
    """Calculate BLE backoff time based on current fail count."""
    backoff_time = BLE_BACKOFF_INITIAL * min(state.ble_fail_count, 4)
    return min(backoff_time, BLE_MAX_BACKOFF)


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

    # Build local subprocess args (used only if relay is disabled)
    local_args = ["tesla-control", "-domain", domain, "-ble", "-vin", VIN, "-key-file", KEY_FILE, cmd]
    if val is not None:
        local_args.append(str(val))

    # Build relay payload directly — avoids parsing the arg list back apart
    # Include domain so relay can place -domain flag correctly
    relay_args = [str(val)] if val is not None else []

    log(f"BLE >>> {cmd} {val if val else ''} ({domain})")
    ok, out = run_tesla_control(local_args, relay_command=cmd, relay_args=relay_args, relay_domain=domain)

    state.ble_command_this_loop = True
    state.last_ble_time = time.time()

    # Check for BLE connection errors BEFORE checking for generic "already" pattern
    if "already connected to the maximum" in out:
        log("BLE >>> Too many BLE connections")
        log_ble_failure_context()
        state.ble_fail_count += 1
        state.ble_backoff_until = time.time() + calculate_ble_backoff()
        return False

    if ok or "already" in out or "is_charging" in out or "not_charging" in out:
        log("BLE >>> OK")
        state.ble_fail_count = 0
        state.relay_unreachable_streak = 0
        state.relay_unreachable_alert = False
        return True

    # Handle failures
    state.ble_fail_count += 1

    if "maximum number of ble" in out or "too many ble" in out:
        log("BLE >>> Too many BLE connections")
        log_ble_failure_context()
        state.ble_backoff_until = time.time() + calculate_ble_backoff()
    elif "context deadline" in out or "not in bluetooth range" in out:
        log("BLE >>> Car not in range or timeout")
        log_ble_failure_context()
        state.ble_backoff_until = time.time() + 30  # Short backoff: car just out of range
    else:
        log(f"BLE >>> FAILED: {out[:120]}")
        log_ble_failure_context()
        state.ble_backoff_until = time.time() + calculate_ble_backoff()

    if "relay connection failed - pi zero unreachable" in out:
        state.relay_unreachable_streak += 1
        if state.relay_unreachable_streak >= RELAY_UNREACHABLE_ALERT_THRESHOLD:
            if not state.relay_unreachable_alert:
                log(
                    f"ALERT: BLE relay unreachable for "
                    f"{state.relay_unreachable_streak} consecutive attempts"
                )
            state.relay_unreachable_alert = True
    else:
        state.relay_unreachable_streak = 0
        state.relay_unreachable_alert = False

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

            log(f"🔌 TWC DISCONNECT EDGE - normalize amps to {MAX_AMPS}A + limit to {DEFAULT_BATTERY_TARGET}%")

            if ble_allowed():
                ok = set_charging_amps(MAX_AMPS)
                if ok:
                    time.sleep(5)
                    if ble_allowed():
                        set_charge_limit(DEFAULT_BATTERY_TARGET)
                else:
                    state.pending_disconnect_amp_normalization = True
                    state.pending_disconnect_reason = "BLE attempt failed on disconnect edge"
                    log("  └─ Disconnect normalize failed; will retry once on next connect")
            else:
                state.pending_disconnect_amp_normalization = True
                state.pending_disconnect_reason = "BLE gated on disconnect edge"
                log("  └─ Disconnect normalize gated; will retry once on next connect")

            # Session-scoped resets (3.6.8 parity)
            reset_session_state()

        if state.last_twc_state is False and twc_state is True:
            state.session_start_ts = time.time()
            state.session_peak_amps = 0
            state.current_amps = 0  # Force SOLAR to recalculate from scratch (not from stale disconnect value)
            log("📊 SESSION STARTED: tracking begins")
            log(f"🔋 New session: resetting BLE + emergency state + current_amps")

            # Invalidate stale Tesla status — new session needs fresh data
            state.cached_ts = 0.0
            state.cached_charging_state = None
            state.cached_battery = None  # Reset so EMERGENCY check uses fresh battery, not pre-session value
            log("  └─ Invalidated Tesla cache (forces fresh API query)")

            # One-time retry of disconnect normalization if needed
            if state.pending_disconnect_amp_normalization:
                log(f"🔁 Pending disconnect normalize retry ({state.pending_disconnect_reason})")
                if ble_allowed():
                    ok = set_charging_amps(MAX_AMPS)
                    if ok:
                        log("  └─ Pending normalize retry succeeded")
                        time.sleep(5)
                        if ble_allowed():
                            set_charge_limit(DEFAULT_BATTERY_TARGET)
                    else:
                        log("  └─ Pending normalize retry failed")
                else:
                    log("  └─ Pending normalize retry gated")

                state.pending_disconnect_amp_normalization = False
                state.pending_disconnect_reason = None

        state.last_twc_state = twc_state

        if twc_state is False:
            log("TWC: Not connected -> AWAY mode")
            reset_away_mode_state()

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
                reset_away_mode_state()

                update_dashboard_status("AWAY", 0, 0, state.cached_battery, 0, 0, 'TWC Unreachable')
                time.sleep(LOOP_INTERVAL)
                continue
            elif twc_state is False:
                # Cached state was disconnected - treat as AWAY mode
                log("TWC: Cached state was disconnected -> AWAY mode")
                reset_away_mode_state()

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
            battery = state.cached_battery
            charging_state = state.cached_charging_state

            log(f"MODE: MANUAL - Charging at MAX to {DEFAULT_BATTERY_TARGET}%")

            # Skip BLE commands if charging is genuinely complete (at/above target)
            if charging_state == 'Complete' and battery is not None and battery >= DEFAULT_BATTERY_TARGET:
                log("MANUAL: Charging complete - skipping BLE commands")
                ble_succeeded = True
            elif charging_state == 'Complete':
                # Car hit a lower charge limit (e.g. from CALENDAR) — raise it
                log(f"MANUAL: Car Complete at {battery}% but target is "
                    f"{DEFAULT_BATTERY_TARGET}% — raising limit")
                if ble_allowed():
                    ble_succeeded = set_charge_limit(DEFAULT_BATTERY_TARGET)
                else:
                    ble_succeeded = False
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
        battery = state.cached_battery
        charging_state = state.cached_charging_state

        if battery is not None and battery < BATTERY_EMERGENCY:
            mode = 'EMERGENCY'

            if state.emergency_start_ts is None:
                state.emergency_start_ts = time.time()
                state.emergency_start_battery = battery
                state.night_stop_sent = False  # Clear night flag so NIGHT doesn't suppress charging
                log(f"EMERGENCY: entered at {battery}% (tracking start time)")

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
                battery = state.cached_battery
                charging_state = state.cached_charging_state

                if battery is not None and battery >= BATTERY_EMERGENCY:
                    log(f"EMERGENCY: battery recovered to {battery}% (>= {BATTERY_EMERGENCY}%) -> exiting emergency")
                    state.emergency_start_ts = None
                    state.emergency_start_battery = None
                    state.current_amps = 0  # Force SOLAR to recalculate from scratch (not from 48A baseline)
                    continue  # Restart loop — don't fall through to NIGHT/CALENDAR

            if state.emergency_start_ts is not None:
                if elapsed >= MAX_EMERGENCY_RUNTIME:
                    if battery is not None and state.emergency_start_battery is not None and battery > state.emergency_start_battery:
                        log(f"EMERGENCY: 90min elapsed but battery rising ({state.emergency_start_battery}% -> {battery}%) — continuing")
                        state.emergency_start_ts = time.time()
                        state.emergency_start_battery = battery
                        continue
                    else:
                        log("EMERGENCY: 90min elapsed and battery not rising -> exiting (conservative)")
                        state.emergency_start_ts = None
                        state.emergency_start_battery = None
                        state.current_amps = 0  # Force SOLAR to recalculate from scratch (not from 48A baseline)
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
                    elif state.last_charge_limit_set != DEFAULT_BATTERY_TARGET:
                        if ble_allowed():
                            set_charge_limit(DEFAULT_BATTERY_TARGET)
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

                    # Wake escalation: escalate to API wake after repeated BLE failures
                    if twc_state is True and state.ble_fail_count >= BLE_FAILS_BEFORE_WAKE:
                        log(f"EMERGENCY: BLE failed {state.ble_fail_count}x while connected — escalating to API wake")
                        wake_vehicle_safe('emergency')
                        log("EMERGENCY wake escalation attempted; resetting BLE failure counters")
                        state.ble_fail_count = 0
                        state.ble_backoff_until = 0

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

        # =====================================================================
        # 2.7) CALENDAR MODE CHECK (between EMERGENCY and NIGHT)
        # =====================================================================
        calendar_advisory = dashboard_config.get('calendar_advisory')
        was_in_calendar = state.last_calendar_mode

        calendar_active = (
            calendar_advisory
            and calendar_advisory.get('active')
            and not calendar_advisory.get('dismissed')
            and time.time() < calendar_advisory.get('expires_at', 0)
        )

        if calendar_active:
            cal_target = calendar_advisory.get('battery_target', DEFAULT_BATTERY_TARGET)

            # Step A: charge_after timing gate
            charge_after = calendar_advisory.get('charge_after')
            if charge_after and time.time() < charge_after:
                hours_left = (charge_after - time.time()) / 3600
                # Only show CALENDAR_WAITING within 1 hour of charge time
                # Before that, just run as SOLAR (advisory banner is visible anyway)
                if hours_left <= 1.0:
                    mode = 'CALENDAR_WAITING'
                    state.calendar_reason = calendar_advisory.get('friendly_message')
                    if not state.last_calendar_mode:
                        log(f"CALENDAR_WAITING: {calendar_advisory.get('friendly_message', 'Trip detected')}")
                        state.last_calendar_mode = True
                    log(f"CALENDAR_WAITING: {hours_left:.1f}h until charging starts — running SOLAR")
                # Fall through to SOLAR mode below (don't continue)
            elif battery is None:
                # Battery unknown — need to wake car to get status
                mode = 'CALENDAR'
                if not state.last_calendar_mode:
                    log(f"CALENDAR: {calendar_advisory.get('friendly_message', 'Trip detected')}")
                    log(f"CALENDAR: Battery unknown — waking vehicle to get status")
                    state.last_calendar_mode = True
                    state.calendar_reason = calendar_advisory.get('friendly_message')
                state.calendar_ble_fails += 1
                if state.calendar_ble_fails >= BLE_FAILS_BEFORE_WAKE:
                    log(f"CALENDAR: Battery unknown + {state.calendar_ble_fails} BLE fails — escalating to API wake")
                    wake_vehicle_safe('calendar')
                    state.calendar_ble_fails = 0
                # Fall through — will retry next loop once vehicle responds
            elif battery < cal_target:
                # Step B: 80% approval gate
                above_80_approved = calendar_advisory.get('above_80_approved', False)
                effective_target = cal_target

                if cal_target > 80 and not above_80_approved:
                    # Auto-approve if <2 hours before event
                    event_start_iso = calendar_advisory.get('event_start_iso', '')
                    try:
                        event_ts = datetime.fromisoformat(
                            event_start_iso.replace("Z", "+00:00")
                        ).timestamp()
                    except Exception:
                        event_ts = calendar_advisory.get('expires_at', 0)
                    hours_to_event = (event_ts - time.time()) / 3600

                    if hours_to_event < 2:
                        log(f"CALENDAR: Auto-approving above-80% ({hours_to_event:.1f}h to event)")
                        above_80_approved = True
                        # Persist auto-approval so dashboard sees it
                        try:
                            cfg_path = f"{SOLAR_API_BASE}:8080/api/calendar/approve_above_80"
                            requests.post(cfg_path, json={}, timeout=3)
                        except Exception:
                            pass  # Best-effort; charger will keep re-approving

                    if not above_80_approved:
                        effective_target = 80

                if battery < effective_target:
                    mode = 'CALENDAR'

                    if not state.last_calendar_mode:
                        log(f"CALENDAR: {calendar_advisory.get('friendly_message', 'Trip detected')}")
                        log(f"CALENDAR: Charging to {effective_target}% (current: {battery}%)")
                        state.last_calendar_mode = True
                        state.calendar_reason = calendar_advisory.get('friendly_message')
                        state.last_charge_limit_set = None  # Force charge limit update

                    # Set charge limit to effective target
                    if state.last_charge_limit_set != effective_target:
                        if ble_allowed():
                            set_charge_limit(effective_target)
                        else:
                            log("CALENDAR: need to set limit but BLE gated; will retry next loop")

                    # Charge at maximum amps (same pattern as MANUAL/EMERGENCY)
                    if state.current_amps != MAX_AMPS:
                        if ble_allowed():
                            set_charging_amps(MAX_AMPS)
                        else:
                            log("CALENDAR: need MAX amps but BLE gated; will retry next loop")
                    elif charging_state != 'Charging':
                        if ble_allowed():
                            start_charging()
                        else:
                            log("CALENDAR: need to start charging but BLE gated; will retry next loop")

                    # Wake escalation (same pattern as MANUAL mode)
                    ble_succeeded = state.ble_command_this_loop and state.ble_fail_count == 0
                    if ble_succeeded:
                        state.calendar_ble_fails = 0
                    elif state.ble_attempted_this_loop:
                        state.calendar_ble_fails += 1
                        log(f"CALENDAR BLE fail streak: {state.calendar_ble_fails}")

                        # Fast wake: first fail + vehicle asleep = wake immediately
                        if state.calendar_ble_fails == 1 and not state.cached_vehicle_online:
                            log("CALENDAR: Vehicle asleep -> immediate wake + retry")
                            if wake_vehicle_safe('calendar'):
                                time.sleep(20)
                                state.ble_command_this_loop = False
                                state.ble_backoff_until = 0
                                if set_charge_limit(effective_target):
                                    state.calendar_ble_fails = 0

                    if twc_state is True and state.calendar_ble_fails >= BLE_FAILS_BEFORE_WAKE:
                        log(f"CALENDAR: BLE failed {state.calendar_ble_fails}x while connected - escalating to API wake")
                        wake_vehicle_safe('calendar')
                        log("CALENDAR wake escalation attempted; resetting BLE failure counters")
                        state.calendar_ble_fails = 0
                        state.ble_fail_count = 0

                    solar = get_solar_data()
                    excess_val = solar['excess'] if solar else 0
                    prod_val = solar['production'] if solar else 0
                    update_dashboard_status(
                        mode, state.current_amps, MAX_AMPS, battery,
                        excess_val, prod_val, charging_state or 'Charging'
                    )

                    log(f"Loop duration: {time.time() - loop_start_ts:.1f}s")
                    time.sleep(LOOP_INTERVAL)
                    continue
                elif effective_target < cal_target:
                    # Paused at 80%, waiting for user approval
                    mode = 'CALENDAR'
                    state.calendar_reason = f"Paused at 80% — approve charging to {cal_target}%"
                    log(f"CALENDAR: Paused at 80% — awaiting approval to charge to {cal_target}%")
                    solar = get_solar_data()
                    excess_val = solar['excess'] if solar else 0
                    prod_val = solar['production'] if solar else 0
                    update_dashboard_status(
                        mode, 0, cal_target, battery,
                        excess_val, prod_val, 'Stopped'
                    )
                    # Fall through to SOLAR mode
                else:
                    # Battery at/above full target -- fall through to SOLAR
                    if state.last_calendar_mode:
                        log(f"CALENDAR: Battery {battery}% >= {cal_target}% target -- returning to SOLAR")
                        state.last_calendar_mode = False
                        state.calendar_reason = None
            else:
                # Battery already at/above target -- fall through to SOLAR
                if state.last_calendar_mode:
                    log(f"CALENDAR: Battery {battery}% >= {cal_target}% target -- returning to SOLAR")
                    state.last_calendar_mode = False
                    state.calendar_reason = None
        else:
            if state.last_calendar_mode:
                log("CALENDAR: Advisory expired or dismissed -- returning to SOLAR")
                state.last_calendar_mode = False
                state.calendar_reason = None

        # If we just exited CALENDAR mode, reset for SOLAR charging
        if was_in_calendar and not state.last_calendar_mode:
            state.current_amps = 0  # Force SOLAR to recalculate from scratch
            if (state.last_charge_limit_set is not None
                    and state.last_charge_limit_set < DEFAULT_BATTERY_TARGET):
                log(f"CALENDAR exit: resetting charge limit "
                    f"{state.last_charge_limit_set}% -> {DEFAULT_BATTERY_TARGET}%")
                if ble_allowed():
                    set_charge_limit(DEFAULT_BATTERY_TARGET)
                else:
                    state.last_charge_limit_set = None  # Ensure retry

        # If car is Complete below target, reset stale amps and raise charge limit
        if (charging_state == 'Complete'
                and battery is not None
                and battery < DEFAULT_BATTERY_TARGET):
            if state.current_amps > 0:
                log(f"Car Complete at {battery}% but current_amps was "
                    f"{state.current_amps} — resetting to 0")
                state.current_amps = 0
            if ((state.last_charge_limit_set is None
                    or state.last_charge_limit_set < DEFAULT_BATTERY_TARGET)
                    and ble_allowed()):
                log(f"SOLAR: Raising charge limit to {DEFAULT_BATTERY_TARGET}% "
                    f"(car Complete at {battery}%)")
                set_charge_limit(DEFAULT_BATTERY_TARGET)

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

        battery = state.cached_battery
        charging_state = state.cached_charging_state

        # ========================================
        # 7) SOLAR MODE
        # ========================================
        if mode not in ('CALENDAR_WAITING',):
            mode = 'SOLAR'

        # [NEW] High Solar Wake-Up
        # If we have strong sustained solar excess but the car is not charging,
        # and BLE is currently blocked, the car may be in deep sleep.
        # Wake once (cooldown protected) to allow BLE charging.
        # [NEW] High Solar Wake-Up
        # SOLAR WAKE — must run before any BLE
        # Skip wake if car is already complete at/above target — nothing to charge
        car_complete_at_target = (
            charging_state == 'Complete'
            and battery is not None
            and battery >= DEFAULT_BATTERY_TARGET
        )
        if (
            not car_complete_at_target and
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
            if car_complete_at_target:
                # Car has reached its charge target — no BLE needed.
                # Reset current_amps so next session starts from a clean baseline.
                if state.current_amps != 0:
                    log(f"SOLAR: Car complete at {battery}% — suppressing BLE, resetting current_amps "
                        f"{state.current_amps}A -> 0")
                    state.current_amps = 0
                else:
                    log(f"SOLAR: Car complete at {battery}% — suppressing BLE")
            elif abs(banded_target - state.current_amps) >= AMP_CHANGE_THRESHOLD:
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
                    # Check preconditioning inhibit (auto-detect OR dashboard flag)
                    precond_active = state.cached_is_preconditioning
                    inhibit_active = is_precondition_inhibit_active(dashboard_config)

                    if precond_active or inhibit_active:
                        reason = "API detected" if precond_active else "dashboard inhibit"
                        log(f"⏸️  Preconditioning active ({reason}) - skipping amp adjustment (target was {banded_target}A)")
                    else:
                        log(
                            f"Stable target {banded_target}A differs by "
                            f"{abs(banded_target - state.current_amps)}A - adjusting"
                        )
                        if state.current_amps != banded_target:
                            set_charging_amps(banded_target)
                        elif charging_state != 'Charging' and ble_allowed():
                            start_charging()
                        elif state.last_charge_limit_set != DEFAULT_BATTERY_TARGET and ble_allowed():
                            set_charge_limit(DEFAULT_BATTERY_TARGET)
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

        # If car is Complete below target with limit already raised, restart
        if (charging_state == 'Complete'
                and battery is not None
                and battery < DEFAULT_BATTERY_TARGET
                and state.last_charge_limit_set is not None
                and state.last_charge_limit_set >= DEFAULT_BATTERY_TARGET
                and ble_allowed()):
            log(f"SOLAR: Car Complete at {battery}% — restarting "
                f"(limit is {state.last_charge_limit_set}%)")
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
