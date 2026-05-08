#!/usr/bin/env python3
"""
================================================================================
Solar Charger TWC Fork - v4.0.26-twc - Telemetry-only: per-loop voltage_v from envoy SSE (no decision changes)
Solar Charger TWC Fork - v4.0.25-twc - Telemetry-only: per-loop TWC actual amps + ble_amp_age (no decision changes)
Solar Charger TWC Fork - v4.0.24-twc - Truthful current_amps seed on session start (no-sun replug throttle-down)
Solar Charger TWC Fork - v4.0.23-twc - Charge-limit reset bugfixes (force= + calendar-exit + startup reconcile)
Solar Charger TWC Fork - v4.0.22-twc - 1Hz signal ring buffer (Option B plumbing)
Solar Charger TWC Fork - v4.0.21-twc - Stale Envoy data failsafe (charge at 48A during outage)
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

v4.0.27-twc - SOLAR-mode tightening: median-based decisions + 4 new gates
- FEATURE: SOLAR steady-state amp targeting now uses excess_median (60s 1Hz
  window from the v4.0.22 ring buffer) instead of excess_smooth (3-sample
  30s mean). Median is more truthful than smooth on broken-cloud chop —
  smooth lags the live signal by 30-60s on transient swings. excess_smooth
  is retained for fast-drop and for logs/dashboard.
- FEATURE: Fast-drop bypass. When max_import_5s >= 3000W AND excess_smooth
  < 0 (cliff confirmed in both 5s peak and 30s mean), drop to MIN_AMPS
  immediately, bypassing AMP_STABILITY_COUNT. Smooth (not median) is the
  cliff trigger because median trails by ~30-60s on a transient. Validated
  against May 7 2026 events at 08:58, 14:15, 18:12.
- FEATURE: TWC tracking gate on UPWARD steps only. If twc_actual_a is
  >TWC_TRACKING_TOLERANCE_A behind state.current_amps, hold instead of
  ramping further. Targets the May 4 14:09 + May 7 10:43 stuck-car class
  where cached_charging_state lies but TWC tells the truth (replay shows
  -10 BLE in the May 7 10:42-10:50 window alone).
- FEATURE: SSE staleness freeze + post-stale recovery counter. When
  envoy_age_max > SSE_STALE_THRESHOLD_S (30s), hold both directions. Need
  SSE_FRESH_RECOVERY_LOOPS (2) consecutive loops with age <
  SSE_FRESH_THRESHOLD_S (15s) before resuming UP-step ramp authority.
  Targets May 4 14:14:59 phantom +11kW single-sample greedy ramp.
- FEATURE: Voltage correction in calculate_target_amps. When voltage_v is
  in the 100-130V/phase sane range, divide by 2*voltage_v (real split-phase
  ~246V) instead of the assumed 240V. May 2026 telemetry shows ~2.5%
  upward bias from this — small but free.
- NEW STATE FIELD: ChargerState.fresh_recovery_count (int). Bumped each
  fresh loop, reset on staleness. Ramp authority is post_stale = (count <
  SSE_FRESH_RECOVERY_LOOPS).
- NEW CONSTANTS: FAST_DROP_IMPORT_W (3000W), SSE_STALE_THRESHOLD_S (30s),
  SSE_FRESH_THRESHOLD_S (15s), SSE_FRESH_RECOVERY_LOOPS (2),
  TWC_TRACKING_TOLERANCE_A (4A).
- API CHANGE: calculate_target_amps signature is (excess, baseline_amps,
  voltage_v=None) — old (excess, current_amps) calls still compatible
  because voltage_v defaults to None (=> divisor=240V, prior behavior).
- INVARIANTS PRESERVED: MAX_AMP_STEP=4, AMP_STABILITY_BAND=2, BLE_COOLDOWN
  unchanged. EMERGENCY/CALENDAR/MANUAL paths still read excess_smooth.
  Wife-Tesla-app guard at the stability block (current_amps==0 sentinel
  + non-positive excess) is preserved per project_tesla_app_workflow.md
  and the v4.0.24 overloaded-sentinel lesson — only the comparison signal
  flipped from excess_smooth to decision_excess so the guard lines up
  with the new basis.
- VALIDATION: replay_v4_0_27.py per-row harness. Against May 7 2026
  full-day Charging-state telemetry: 62 actual BLE -> 68 sim BLE
  (+6, ~10%). The +6 is small +2A increments where the more responsive
  median catches movement that excess_smooth's hysteresis filtered. The
  trade is the chase event: 13 BLE -> 3 BLE in the 10:42-10:50 stuck-car
  window. Three cliff events all caught at the right loop.
- KNOWN TRADE-OFF: Fast-drop on smooth<0 + mi5>=3000 over-corrects on
  moderate dips (May 7 14:15: actual 46->40, sim 46->6). Watching for
  this in May 9-15 daily-stats; tighten threshold in v4.0.28 if it shows
  up repeatedly.
- ROLLBACK: git revert <commit> && sudo podman build -t
  localhost/tesla-solar-control:latest . && sudo systemctl restart
  solar-charger.

v4.0.26-twc - Telemetry-only: per-loop voltage_v from envoy SSE
- FEATURE: Per-phase voltage now flows envoy_logger SSE -> dashboard
  /api/envoy_data -> SignalSample.voltage_v -> Charge: log line. The new
  `volt={voltage:.1f}V` field on the Charge: line captures grid voltage
  every loop. phase2_telemetry.py PAT_CHARGE extended (voltage_v column).
- RATIONALE: Real-time grid voltage is needed for the v4.0.27 SOLAR-mode
  amp-target tuning work (see SOLAR_TIGHTENING_PLAN.md). Plumbing it as
  pure telemetry first lets us collect a few days of data before any
  algorithmic change reads it.
- INVARIANTS PRESERVED: Zero changes to decision logic.
  calculate_target_amps still uses excess_smooth only; voltage_v is
  read into SignalSample but never consumed. envoy_logger falls back to
  None on parse failure (does not crash SSE loop). Dashboard returns
  voltage_v=null if envoy_logger has no value yet; SignalSample defaults
  to 0.0 in that case.

v4.0.25-twc - Telemetry-only: per-loop TWC actual amps + ble_amp_age
- FEATURE: New `Charge:` log line in the main per-loop block, immediately after
  the existing `Signal:` line. Captures `twc_actual_a`, `cmd_a`,
  `ble_amp_age_s`, and `charging_state` every loop. Pure observability —
  intended to feed the v4.0.25+ SOLAR-mode tightening work documented in
  SOLAR_TIGHTENING_PLAN.md (post-BLE settle window analysis specifically).
- FEATURE: New `state.last_ble_amp_command_t` field tracking only successful
  `charging-set-amps` BLE commands. Distinct from the existing
  `state.last_ble_time` (which counts ALL BLE: amps/start/stop/limit). The new
  field lets the post-event analysis bin loops as "fresh BLE / settling /
  settled" cleanly without conflating limit-set or start/stop BLE.
- INVARIANTS PRESERVED: Zero changes to any decision logic — `excess_smooth`
  still drives `calculate_target_amps`, AMP_STABILITY_COUNT still gates BLE,
  all mode-specific paths unchanged. The TWC poll on each loop is a localhost
  call (~5ms) and uses the existing `get_twc_current_amps()` helper which
  already has its own try/except. If TWC is unreachable the log line shows
  `twc=?` and the rest of the loop is unaffected.
- DEFERRED: Voltage capture from SSE was on the original wishlist but neither
  dashboard's `/api/envoy_data` nor envoy_logger's `/live` endpoint exposes
  voltage today. Plumbing it requires a cross-project change to envoy_logger.
  Not done in this point release; revisit if Phase-1-style per-phase voltage
  becomes necessary for tuning.

v4.0.24-twc - Truthful current_amps seed on session start (no-sun replug throttle-down)
- BUG: On a same-spot replug with no solar excess, the script let the car
  drink 48A from the grid until it hit the (newly v4.0.23-enforced) 80%
  in-car limit. Observed 2026-05-03: car charged 59% -> 80% in 90 min
  pulling ~10 kW from the grid because SOLAR's throttle-down BLE was
  silently suppressed.
- ROOT CAUSE: Conflict between two correct-in-isolation behaviors.
  v4.0.20 zeroes state.current_amps on session-start (to fix a stale-48A
  deadlock where SOLAR thought it was already at 48A in strong sun and
  never sent BLE). The pre-existing line ~1914 guard skips BLE when
  current_amps==0 + excess<=0 (to respect user-initiated app charges).
  Together they meant: every session-start with no sun -> "skip BLE" ->
  car keeps whatever amps the disconnect-edge had set (48A).
- FIX: Add state.disconnect_normalize_amps_succeeded flag. Set true when
  disconnect-edge or pending-retry successfully BLE-set the car to
  MAX_AMPS. Consumed on session-start: if true, seed current_amps=MAX_AMPS
  (truthful — we just put it there); else current_amps=0 (preserves the
  line ~1914 external-charge guard for Tesla app workflows).
- PRESERVES: v4.0.20 stale-48A protection still works — current_amps is
  now truthful (we set the car to 48A) instead of stale-from-last-session.
  Tesla app respect still works — when the user app-starts a charge while
  plugged in continuously (no session edge), no normalize ran, the flag
  stays false, current_amps stays 0, and line ~1914 hands off.

v4.0.23-twc - Charge-limit reset bugfixes (force= + calendar-exit + startup reconcile)
- BUG FIX (Critical): TWC disconnect-edge handler was structurally unable to
  send the paired set_charge_limit(80) BLE command. After set_charging_amps
  succeeded, ble_call set state.ble_command_this_loop=True, and the second
  ble_allowed() check at line ~1109 always returned False due to the
  one-per-loop guard. Result: on every TWC unplug, only the amp normalization
  fired; the charge-limit reset was silently dropped. Same dead-code bug in
  the on-reconnect retry handler. Fix: added force= parameter to ble_allowed/
  ble_call/set_charge_limit that bypasses the per-loop guard and inter-call
  cooldown (but still respects backoff). Disconnect-edge and reconnect-retry
  use force=True for the paired limit-set after sleeping 5s. New state field
  pending_disconnect_limit_reset tracks failures of just the limit so the
  reconnect path can retry it independently.
- BUG FIX: CALENDAR-exit reset only fired when state.last_charge_limit_set <
  DEFAULT_BATTERY_TARGET — i.e., only when calendar set a LOWER limit. With
  above-80 approval (cal_target up to 95%), exit needs to reset DOWN. Changed
  to '!= DEFAULT_BATTERY_TARGET' so it resets in either direction.
- FEATURE: Startup / state-loss reconciliation. When state.last_charge_limit_set
  is None (container restart, or a previous BLE attempt failed silently) and
  no calendar advisory is active, the SOLAR-path now asserts
  DEFAULT_BATTERY_TARGET as the baseline. Self-throttling via the cache
  (succeeds once, never re-sends). This closes the gap where a container
  rebuild during/after a calendar session could leave the car at a stale
  high limit forever.
- INVARIANTS PRESERVED: ble_allowed() still respects backoff for forced calls
  so a real BLE failure on the first call defers the second. All mode-specific
  BLE flows (MANUAL/CALENDAR/EMERGENCY/SOLAR stability) unchanged — they don't
  use force= and continue to obey the one-per-loop guard.
- DEFERRED FOLLOW-UPS:
  1. MANUAL "Charging complete - skipping BLE commands" path (battery >= 80%
     + state=Complete) early-bails without considering whether the limit is
     wrong. If a stale higher limit lives on the car when MANUAL is toggled
     and battery is already above target, MANUAL won't lower it. Consider
     letting MANUAL run the same limit-mismatch reconciliation Fix C does.
  2. pending_disconnect_limit_reset retry currently only runs on the TWC
     connect-edge (one shot). If the limit reset still fails there, the flag
     persists but isn't retried until the next connect edge. Fix C covers
     this in practice (because last_charge_limit_set stays None after a
     failed BLE), but the two flags duplicate intent. Consider unifying or
     having an independent per-loop retry path that doesn't rely on edges.
  3. Fix A uses force=True to send two BLE commands ~5 seconds apart in the
     same loop. The car accepted this in live testing on 2026-05-02. If the
     car ever rejects back-to-back BLE commands (e.g. firmware change), the
     fallback is to split disconnect-edge into two loop iterations — track
     pending_disconnect_limit_reset eagerly and let the next loop send it.

v4.0.22-twc - 1Hz signal ring buffer (Option B plumbing)
- FEATURE: Background thread polls localhost:8080/api/envoy_data at 1 Hz and
  fills a 60-second thread-safe ring buffer (SignalBuffer). The dashboard route
  is itself fed by envoy_logger.service's SSE stream (1 Hz), so per-tick
  freshness drops from ~30s to ~1-6s. NO additional load on the Envoy device:
  envoy_logger keeps a single persistent /stream/meter connection; all internal
  consumers (dashboard, this charger) read from in-memory state.
- REFACTOR: get_solar_data() now returns the latest buffer sample. Falls back to
  a synchronous HTTP call only on poller startup or extended buffer staleness
  (>SIGNAL_STALE_SEC), preserving prior behavior in the cold-start path.
- OBSERVABILITY: Per-loop log line shows buffer count, mean/median/p25 excess,
  max grid import in last 5s, and max envoy SSE age. These statistics are
  logged but do not yet influence charging decisions — that's a deferred
  follow-up (asymmetric ramp / fast-drop / median-based decisions / post-BLE
  verification) once we have a few days of telemetry to tune against.
- INVARIANTS PRESERVED: LOOP_INTERVAL=30, MAX_AMP_STEP=4, SMOOTH_WINDOW=3,
  AMP_STABILITY_BAND=2, BLE_COOLDOWN=12, all SOLAR/MANUAL/CALENDAR/EMERGENCY
  mode logic, all session/disconnect/wake-escalation paths from v4.0.16-v4.0.21
  are unchanged. This is plumbing only.

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

VERSION = "v4.0.27-twc"

import time
import subprocess
import requests
import os
import threading
from datetime import datetime
from collections import deque
from dataclasses import dataclass, field
from typing import Optional, Deque, Dict, Any, List, Tuple


# -------------------------------
# CONFIG (set TESLA_VIN and TESLA_EMAIL via environment)
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
    "http://localhost"  # Dashboard + TWC API base (--net=host => host localhost)
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
BLE_RELAY_HOST = os.getenv("BLE_RELAY_HOST", "192.168.1.100")
BLE_RELAY_PORT = int(os.getenv("BLE_RELAY_PORT", "5003"))
BLE_RELAY_URL = f"http://{BLE_RELAY_HOST}:{BLE_RELAY_PORT}"
BLE_RELAY_API_KEY = os.getenv("BLE_RELAY_API_KEY")
if BLE_RELAY_ENABLED and not BLE_RELAY_API_KEY:
    raise RuntimeError("BLE_RELAY_API_KEY must be set when BLE_RELAY_ENABLED=true")

TWC_CACHE_TTL = 15
TWC_STALE_THRESHOLD = 90
SOLAR_DATA_STALE_SEC = 600  # 10 minutes — triggers 48A failsafe in SOLAR mode during outage

# -------------------------------
# 1Hz SIGNAL BUFFER (v4.0.22 - Option B plumbing)
# -------------------------------
# Background thread polls PI2_SOLAR_URL at 1 Hz and fills a ring buffer.
# The dashboard endpoint is itself SSE-fed (envoy_logger.service holds the
# single /stream/meter connection on the network — see CLAUDE.md). Adding this
# in-process consumer adds ZERO additional load on the Envoy device; only
# loopback HTTP traffic to localhost:8080 is added.
SIGNAL_POLL_INTERVAL_SEC = 1.0   # 1 Hz polling cadence
SIGNAL_POLL_TIMEOUT = 4          # Localhost should respond instantly; tight timeout
SIGNAL_BUFFER_MAXLEN = 60        # Keep ~60 seconds of samples
SIGNAL_STALE_SEC = 30            # Buffer considered unusable if no fresh sample in this window
SIGNAL_LOG_QUIET_FAILURES = 30   # Only log every Nth consecutive poll failure to avoid log spam

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

# v4.0.27: SOLAR-mode decisions now use the 1Hz buffer signals (median for
# steady-state, excess_smooth for cliff detection) plus three gates layered
# over the existing stability/threshold logic. Validated against May 7 2026
# telemetry — replay harness in replay_v4_0_27.py.
FAST_DROP_IMPORT_W = 3000        # max_import_5s threshold to bypass stability count
SSE_STALE_THRESHOLD_S = 30       # envoy_age_max above this -> hold both directions
SSE_FRESH_THRESHOLD_S = 15       # consecutive samples below this rebuild ramp authority
SSE_FRESH_RECOVERY_LOOPS = 2     # fresh loops required before resuming UP steps
TWC_TRACKING_TOLERANCE_A = 4     # twc must be within this of cmd to ramp UP

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

    # v4.0.25: timestamp of the last *successful* charging-set-amps BLE command.
    # Distinct from last_ble_time which covers ALL BLE (start/stop/limit too).
    # Used only for telemetry (Charge: log line) — does not influence decisions.
    last_ble_amp_command_t: float = 0.0

    # v4.0.27: SSE-stale recovery counter. Increments by 1 each loop where
    # envoy_age_max < SSE_FRESH_THRESHOLD_S, decays to 0 the moment age
    # exceeds SSE_STALE_THRESHOLD_S. UP-step ramp authority requires
    # >= SSE_FRESH_RECOVERY_LOOPS to prevent greedy ramp on a single fresh
    # sample after a stale window (May 4 2026 14:14:59 phantom +11kW event).
    fresh_recovery_count: int = 0

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

    # --- v4.0.23: Independent limit-reset retry ---
    # Set when the disconnect-edge sent the amp normalization OK but the
    # follow-up set_charge_limit(80) failed (backoff). The next loop or the
    # reconnect path retries the limit independently of amps.
    pending_disconnect_limit_reset: bool = False

    # --- v4.0.24: Truthful current_amps seed on session start ---
    # Set true when the disconnect-edge (or pending retry) successfully
    # set the car to MAX_AMPS via BLE. Consumed on the next session-start
    # to seed state.current_amps = MAX_AMPS instead of zeroing it, so SOLAR
    # can throttle down a no-sun replug. If false at session-start (e.g.
    # disconnect-edge BLE failed, or wife started a charge via Tesla app
    # without us seeing a session edge), current_amps stays 0 and the
    # line ~1914 "external charge" guard respects the user's intent.
    disconnect_normalize_amps_succeeded: bool = False

    # --- v4.0.3: Dashboard warning flags ---
    grid_charge_warning_amps: Optional[float] = None
    relay_unreachable_streak: int = 0
    relay_unreachable_alert: bool = False

state = ChargerState()


# -------------------------------
# 1Hz SIGNAL BUFFER (v4.0.22 - Option B plumbing)
# -------------------------------
@dataclass
class SignalSample:
    """One sample from the 1Hz background poller."""
    t: float            # Wall clock when this sample was captured
    production_w: float
    excess_w: float
    consumption_w: float
    envoy_age_sec: float  # envoy_data_age_seconds reported by dashboard (SSE event age + cache age)
    voltage_v: float = 0.0  # v4.0.26: avg grid voltage from envoy SSE (telemetry only)


class SignalBuffer:
    """Thread-safe ring buffer of recent solar samples.

    Producer: signal_poller_loop() at ~1Hz.
    Consumer: main charger loop (get_solar_data, signal stats logging).

    All public methods take the lock and return immutable snapshots so callers
    never see the underlying deque.
    """

    def __init__(self, maxlen: int = SIGNAL_BUFFER_MAXLEN):
        self._buf: Deque[SignalSample] = deque(maxlen=maxlen)
        self._lock = threading.Lock()
        self._last_success_t: float = 0.0
        self._consecutive_failures: int = 0
        self._failures_total: int = 0

    def append(self, sample: SignalSample) -> None:
        with self._lock:
            self._buf.append(sample)
            self._last_success_t = sample.t
            self._consecutive_failures = 0

    def record_failure(self) -> int:
        """Returns the new consecutive-failure count (for log throttling)."""
        with self._lock:
            self._consecutive_failures += 1
            self._failures_total += 1
            return self._consecutive_failures

    def latest(self) -> Optional[SignalSample]:
        with self._lock:
            return self._buf[-1] if self._buf else None

    def snapshot(self) -> Tuple[List[SignalSample], float, int, int]:
        """Returns (samples_copy, last_success_t, consecutive_failures, failures_total)."""
        with self._lock:
            return (list(self._buf), self._last_success_t,
                    self._consecutive_failures, self._failures_total)


signal_buf = SignalBuffer()


def signal_poller_loop() -> None:
    """Background thread: poll PI2_SOLAR_URL at 1 Hz and append to signal_buf.

    No retry logic on failure — we just record it and try again next tick.
    The buffer's stale-detection in get_solar_data() handles fallback to a
    synchronous call if we drift too far behind.
    """
    log(f"Signal poller thread starting (interval={SIGNAL_POLL_INTERVAL_SEC}s, "
        f"buffer={SIGNAL_BUFFER_MAXLEN} samples)")
    while True:
        t0 = time.time()
        try:
            r = requests.get(PI2_SOLAR_URL, timeout=SIGNAL_POLL_TIMEOUT)
            r.raise_for_status()
            data = r.json()
            sample = SignalSample(
                t=time.time(),
                production_w=float(data.get('production_watts', 0) or 0),
                excess_w=float(data.get('excess_watts', 0) or 0),
                consumption_w=float(data.get('consumption_watts', 0) or 0),
                envoy_age_sec=float(data.get('envoy_data_age_seconds') or 0),
                voltage_v=float(data.get('voltage_v') or 0.0),
            )
            signal_buf.append(sample)
        except Exception as e:
            fails = signal_buf.record_failure()
            # Log first failure of a streak, then every Nth, to avoid log spam during outages
            if fails == 1 or fails % SIGNAL_LOG_QUIET_FAILURES == 0:
                log(f"Signal poller error (consecutive={fails}): {type(e).__name__}: {e}")

        elapsed = time.time() - t0
        sleep_for = max(0.0, SIGNAL_POLL_INTERVAL_SEC - elapsed)
        time.sleep(sleep_for)


def _percentile(sorted_vals: List[float], p: float) -> float:
    """Simple percentile (no numpy dep). p is in [0, 1]. Assumes sorted input."""
    if not sorted_vals:
        return 0.0
    idx = int(p * (len(sorted_vals) - 1))
    return sorted_vals[idx]


def get_signal_stats() -> Optional[Dict[str, Any]]:
    """Compute observability stats over the ring buffer.

    Returns None if buffer is empty or stale (caller logs nothing rather than
    misleading numbers). Logged each main loop but does NOT yet drive
    decisions — that's a deferred follow-up PR.
    """
    samples, last_t, fails, fails_total = signal_buf.snapshot()
    now = time.time()
    if not samples:
        return None

    age_sec = now - last_t
    if age_sec > SIGNAL_STALE_SEC:
        return {'stale': True, 'age_sec': age_sec, 'count': len(samples),
                'consecutive_failures': fails, 'failures_total': fails_total}

    excess_vals = sorted(s.excess_w for s in samples)
    prod_vals = [s.production_w for s in samples]
    n = len(samples)

    # Fast-drop signal: max grid import (= -excess_w) over the last 5 seconds.
    # Used for observability now; will drive fast-drop logic in a follow-up.
    recent_5s = [s for s in samples if (now - s.t) <= 5.0]
    max_import_5s = max((-s.excess_w for s in recent_5s), default=0.0)

    return {
        'stale': False,
        'count': n,
        'window_sec': now - samples[0].t,
        'age_sec': age_sec,
        'excess_mean': sum(excess_vals) / n,
        'excess_median': _percentile(excess_vals, 0.5),
        'excess_p25': _percentile(excess_vals, 0.25),
        'excess_p75': _percentile(excess_vals, 0.75),
        'production_mean': sum(prod_vals) / n,
        'max_import_5s': max_import_5s,
        'envoy_age_max': max(s.envoy_age_sec for s in samples),
        'consecutive_failures': fails,
        'failures_total': fails_total,
    }


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
    """Return the freshest solar sample.

    Primary path (v4.0.22+): read the most-recent sample from the 1Hz ring
    buffer populated by signal_poller_loop(). Steady-state freshness is
    ~1-2 seconds (poller cadence + dashboard cache + envoy_logger SSE event age).

    Fallback path: synchronous HTTP call to the dashboard. Used on poller
    cold-start (buffer empty) or extended buffer staleness (>SIGNAL_STALE_SEC,
    e.g. dashboard down for >30s). Preserves the legacy 30s-timeout behavior so
    the failure mode of this function is identical to v4.0.21 in the worst case.
    """
    sample = signal_buf.latest()
    if sample is not None:
        age = time.time() - sample.t
        if age <= SIGNAL_STALE_SEC:
            return {
                'production': sample.production_w,
                'excess': sample.excess_w,
                'data_age_seconds': sample.envoy_age_sec,
            }
        log(f"WARN get_solar_data: ring buffer stale ({age:.1f}s); "
            f"falling back to synchronous fetch")

    try:
        r = requests.get(PI2_SOLAR_URL, timeout=30)  # Verified: 30s timeout
        data = r.json()
        production = float(data.get('production_watts', 0) or 0)
        excess = float(data.get('excess_watts', 0) or 0)
        data_age = data.get('envoy_data_age_seconds')
        return {'production': production, 'excess': excess, 'data_age_seconds': data_age}
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
def ble_allowed(force=False):
    """Check if BLE command is allowed (cooldown + backoff + one per loop).

    force=True bypasses the one-per-loop guard and the inter-call cooldown,
    but the post-failure backoff still applies. Used by paired BLE flows
    (e.g. disconnect-edge "set 48A then set 80%") where the second call has
    already waited a few seconds and just needs to bypass the per-loop budget.
    Backoff is still respected so a real BLE failure on the first call still
    defers the second call.
    """
    now = time.time()
    if not force and state.ble_command_this_loop:
        return False
    if now < state.ble_backoff_until:
        return False
    if not force and (now - state.last_ble_time) < BLE_COOLDOWN:
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


def ble_call(cmd, val=None, domain='infotainment', force=False):
    """Execute a BLE command with gating and backoff.

    force=True bypasses the one-per-loop guard and the cooldown (but not the
    backoff). See ble_allowed() for rationale.
    """
    if not force and state.ble_command_this_loop:
        log(f"BLE >>> {cmd} skipped (already used BLE this loop)")
        return False

    if not ble_allowed(force=force):
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
                    f"⚠️ ALERT: BLE relay unreachable for "
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
def set_charge_limit(percent, force=False):
    """Set charge limit - uses cache to avoid redundant BLE calls.

    force=True bypasses the one-per-loop and cooldown gates (but not backoff)
    so paired flows like the TWC disconnect-edge can send amps + limit in the
    same loop. See ble_allowed() for force semantics.
    """
    if state.last_charge_limit_set == percent:
        return True
    if ble_call('charging-set-limit', percent, force=force):
        state.last_charge_limit_set = percent
        return True
    return False


def set_charging_amps(amps):
    """Set charging amps via BLE."""
    if ble_call('charging-set-amps', amps):
        state.current_amps = amps
        if amps > state.session_peak_amps:
            state.session_peak_amps = amps
        state.last_ble_amp_command_t = time.time()  # v4.0.25 telemetry
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
def calculate_target_amps(excess_watts, baseline_amps, voltage_v=None):
    """Calculate target amps by adding excess-based delta to a baseline.

    baseline_amps is normally state.current_amps (what we last commanded).
    Rate-limits increases to MAX_AMP_STEP per loop. Decreases are unlimited.

    voltage_v (v4.0.27): per-phase voltage from the 1Hz buffer. When a sane
    reading is available, divide by 2*voltage_v to use real split-phase
    voltage (~246V) instead of the 240V assumption — the May 2026 telemetry
    showed a consistent +2.5% bias in commanded amps from this.
    """
    if voltage_v is not None and 100 <= voltage_v <= 130:
        divisor = voltage_v * 2  # split-phase
    else:
        divisor = VOLTAGE        # fallback to 240V assumption
    delta = int(excess_watts / divisor)

    # Rate-limit increases only (decreases can be immediate to avoid grid import)
    if delta > MAX_AMP_STEP:
        delta = MAX_AMP_STEP

    target = baseline_amps + delta
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
    log(f"Signal buffer: 1Hz polling, {SIGNAL_BUFFER_MAXLEN}-sample window, "
        f"stale={SIGNAL_STALE_SEC}s")
    log("TWC FORK: Home detection via TWC only (no GPS fallback)")
    log("=" * 60)

    # Start 1Hz signal poller thread (v4.0.22 - Option B plumbing).
    # Daemon=True so it dies with the main thread on container shutdown.
    threading.Thread(target=signal_poller_loop, daemon=True, name="signal_poller").start()

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
                    state.disconnect_normalize_amps_succeeded = True
                    time.sleep(5)
                    # v4.0.23: force=True bypasses one-per-loop + cooldown so
                    # the limit-set actually fires after the amp-set in the
                    # same loop. Backoff still applies, so a real BLE failure
                    # on amps still defers the limit attempt.
                    if set_charge_limit(DEFAULT_BATTERY_TARGET, force=True):
                        log(f"  └─ Disconnect normalize complete: 48A + {DEFAULT_BATTERY_TARGET}%")
                    else:
                        state.pending_disconnect_limit_reset = True
                        log("  └─ Disconnect limit reset failed; will retry next loop")
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
            # v4.0.24: If disconnect-edge successfully normalized the car to
            # MAX_AMPS via BLE, seed current_amps with that truthful value so
            # SOLAR can throttle down on a no-sun replug. Otherwise zero it,
            # which keeps the line ~1914 "external charge" guard respecting
            # user-initiated app charges (wife's Tesla app workflow).
            if state.disconnect_normalize_amps_succeeded:
                state.current_amps = MAX_AMPS
                state.disconnect_normalize_amps_succeeded = False
                log(f"🔋 New session: seeding current_amps={MAX_AMPS}A (disconnect normalize was ours)")
            else:
                state.current_amps = 0
                log(f"🔋 New session: resetting current_amps=0 (no prior normalize — respect external charge)")
            log("📊 SESSION STARTED: tracking begins")
            log(f"🔋 New session: resetting BLE + emergency state")

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
                        # v4.0.24: pending-retry succeeded after session-start
                        # already zeroed current_amps. Seed it now so SOLAR
                        # throttle-down works on this session.
                        state.current_amps = MAX_AMPS
                        log(f"  └─ Pending normalize retry succeeded (current_amps seeded to {MAX_AMPS}A)")
                        time.sleep(5)
                        # v4.0.23: force=True so the paired limit-set actually
                        # fires (was dead-coded by ble_command_this_loop guard).
                        if set_charge_limit(DEFAULT_BATTERY_TARGET, force=True):
                            log(f"  └─ Pending limit reset succeeded ({DEFAULT_BATTERY_TARGET}%)")
                        else:
                            state.pending_disconnect_limit_reset = True
                            log("  └─ Pending limit reset still failed; will retry")
                    else:
                        log("  └─ Pending normalize retry failed")
                else:
                    log("  └─ Pending normalize retry gated")

                state.pending_disconnect_amp_normalization = False
                state.pending_disconnect_reason = None

            # v4.0.23: Independent limit-reset retry. Amps already normalized
            # in a prior loop, but the paired limit-set failed. Retry just the
            # limit (no force needed — fresh loop).
            elif state.pending_disconnect_limit_reset:
                log("🔁 Pending limit reset retry")
                if ble_allowed():
                    if set_charge_limit(DEFAULT_BATTERY_TARGET):
                        log(f"  └─ Pending limit reset succeeded ({DEFAULT_BATTERY_TARGET}%)")
                        state.pending_disconnect_limit_reset = False
                    else:
                        log("  └─ Pending limit reset still failed; will retry next loop")
                else:
                    log("  └─ Pending limit reset gated; will retry next loop")

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
            # v4.0.23: was '< DEFAULT_BATTERY_TARGET' which only handled the
            # case where calendar set a LOWER limit. With above-80 approval
            # (e.g. cal_target=95), the limit needs to be reset DOWN. Use !=
            # so we reset in either direction.
            if (state.last_charge_limit_set is not None
                    and state.last_charge_limit_set != DEFAULT_BATTERY_TARGET):
                log(f"CALENDAR exit: resetting charge limit "
                    f"{state.last_charge_limit_set}% -> {DEFAULT_BATTERY_TARGET}%")
                if ble_allowed():
                    set_charge_limit(DEFAULT_BATTERY_TARGET)
                else:
                    state.last_charge_limit_set = None  # Ensure retry

        # v4.0.23: Startup / state-loss reconciliation. If we don't know the
        # car's charge limit (e.g. container just restarted, or a previous
        # set_charge_limit failed silently), assert DEFAULT_BATTERY_TARGET as
        # the baseline. We only reach this point when no active CALENDAR is
        # driving the limit and we're not in MANUAL/EMERGENCY (those modes
        # 'continue' earlier in the loop), so SOLAR/NIGHT-path is the right
        # place to reconcile. The set_charge_limit cache prevents re-sending
        # once it succeeds.
        if (state.last_charge_limit_set is None
                and not calendar_active
                and ble_allowed()):
            log(f"Startup reconcile: charge limit unknown - asserting "
                f"{DEFAULT_BATTERY_TARGET}% baseline")
            set_charge_limit(DEFAULT_BATTERY_TARGET)

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

        # 1Hz buffer observability (v4.0.22). Stats only — does NOT yet drive
        # decisions. Used to validate buffer health and to gather data for
        # tuning the future asymmetric-ramp / fast-drop / median-based logic.
        sig_stats = get_signal_stats()
        if sig_stats is None:
            log("Signal: ring buffer empty (poller cold-start or extended outage)")
        elif sig_stats.get('stale'):
            log(f"Signal: ring buffer STALE age={sig_stats['age_sec']:.1f}s "
                f"count={sig_stats['count']} "
                f"fails_consec={sig_stats['consecutive_failures']} "
                f"fails_total={sig_stats['failures_total']}")
        else:
            log(f"Signal: n={sig_stats['count']} "
                f"window={sig_stats['window_sec']:.1f}s "
                f"age={sig_stats['age_sec']:.1f}s "
                f"excess(p25/med/mean/p75)="
                f"{sig_stats['excess_p25']:.0f}/"
                f"{sig_stats['excess_median']:.0f}/"
                f"{sig_stats['excess_mean']:.0f}/"
                f"{sig_stats['excess_p75']:.0f}W "
                f"max_import_5s={sig_stats['max_import_5s']:.0f}W "
                f"envoy_age_max={sig_stats['envoy_age_max']:.1f}s "
                f"fails_total={sig_stats['failures_total']}")

        # v4.0.25 telemetry: per-loop TWC actual amps + ble_amp_age.
        # Pure observability, fed into phase2_telemetry CSVs for tuning the
        # post-BLE settle window and TWC-vs-commanded ramp model. Does NOT
        # affect decisions in this release.
        twc_actual = get_twc_current_amps()
        if state.last_ble_amp_command_t > 0:
            ble_amp_age_str = f"{time.time() - state.last_ble_amp_command_t:.1f}s"
        else:
            ble_amp_age_str = "never"
        twc_str = f"{twc_actual:.1f}A" if twc_actual is not None else "?"
        # v4.0.26: voltage from latest signal sample (telemetry-only)
        latest_sample = signal_buf.latest()
        if latest_sample is not None and latest_sample.voltage_v > 0:
            volt_str = f"{latest_sample.voltage_v:.1f}V"
        else:
            volt_str = "?"
        log(f"Charge: twc_actual={twc_str} cmd={state.current_amps}A "
            f"ble_amp_age={ble_amp_age_str} "
            f"volt={volt_str} "
            f"state={state.cached_charging_state or '?'}")

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

        # Stale Envoy data failsafe: if solar signal has been unavailable for 10+ minutes,
        # charge at MAX_AMPS rather than holding stale excess values.
        # Only reachable in SOLAR mode — NIGHT mode continues before this point.
        data_age = solar.get('data_age_seconds')
        if data_age is not None and data_age > SOLAR_DATA_STALE_SEC:
            log(f"⚠️ SOLAR: Envoy data {data_age}s stale — no solar signal, failsafe {MAX_AMPS}A")
            if state.current_amps != MAX_AMPS:
                if ble_allowed():
                    set_charging_amps(MAX_AMPS)
            elif charging_state != 'Charging' and ble_allowed():
                start_charging()
            update_dashboard_status(mode, state.current_amps, MAX_AMPS, battery, 0, 0, charging_state or 'Unknown')
            log(f"Loop duration: {time.time() - loop_start_ts:.1f}s")
            time.sleep(LOOP_INTERVAL)
            continue

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

        # ============================================================
        # v4.0.27: median-based decisions, with three gates layered over
        # the existing stability/threshold logic.
        #   - decision_excess: 60-sample 1Hz median for steady-state ramp
        #   - excess_smooth retained as the fast-drop trigger basis
        #     (more responsive on transient cliffs than median)
        #   - voltage_v: per-phase reading from v4.0.26 plumbing
        # See replay_v4_0_27.py + SOLAR_TIGHTENING_PLAN.md.
        # ============================================================
        if sig_stats and not sig_stats.get('stale'):
            decision_excess = sig_stats['excess_median']
            sse_age = sig_stats['envoy_age_max']
            mi5 = sig_stats['max_import_5s']
        else:
            decision_excess = excess_smooth
            sse_age = 0.0
            mi5 = 0.0

        voltage_v = (latest_sample.voltage_v
                     if latest_sample is not None and latest_sample.voltage_v > 0
                     else None)

        # ---- Stale-data freshness counter ----
        if sse_age > SSE_STALE_THRESHOLD_S:
            state.fresh_recovery_count = 0
        elif sse_age < SSE_FRESH_THRESHOLD_S:
            state.fresh_recovery_count = min(
                state.fresh_recovery_count + 1, SSE_FRESH_RECOVERY_LOOPS + 1
            )
        sse_stale = sse_age > SSE_STALE_THRESHOLD_S
        post_stale = state.fresh_recovery_count < SSE_FRESH_RECOVERY_LOOPS

        # ---- Fast-drop on real cliff (excess_smooth, not median) ----
        # excess_smooth leads median on transients because the 60s median is
        # dragged up by older healthy samples for ~30-60s after a cloud edge.
        if (mi5 >= FAST_DROP_IMPORT_W and excess_smooth < 0 and not sse_stale
                and state.current_amps > MIN_AMPS and ble_allowed()):
            log(f"SOLAR: FAST-DROP mi5={mi5:.0f}W smooth={excess_smooth:.0f}W "
                f"-> {MIN_AMPS}A (bypassing stability count)")
            set_charging_amps(MIN_AMPS)
            update_dashboard_status(
                mode, state.current_amps, MIN_AMPS, battery,
                excess_smooth, prod_smooth, charging_state or 'Unknown'
            )
            log(f"Sleeping {LOOP_INTERVAL}s (mode={mode}, amps={state.current_amps})")
            log(f"Loop duration: {time.time() - loop_start_ts:.1f}s")
            time.sleep(LOOP_INTERVAL)
            continue

        raw_target = calculate_target_amps(decision_excess, state.current_amps, voltage_v)
        banded_target = (raw_target // AMP_STABILITY_BAND) * AMP_STABILITY_BAND
        banded_target = max(MIN_AMPS, banded_target)

        # ---- TWC tracking gate on UPWARD steps only ----
        # If the car visibly hasn't followed the last command, don't ramp
        # further. Catches stuck-car scenarios (May 4 14:09, May 7 10:43)
        # where cached charging_state lies but TWC tells the truth.
        if (banded_target > state.current_amps
                and twc_actual is not None
                and twc_actual < (state.current_amps - TWC_TRACKING_TOLERANCE_A)):
            log(f"SOLAR: TWC gate cmd={state.current_amps}A twc={twc_actual:.1f}A "
                f"(>{TWC_TRACKING_TOLERANCE_A}A behind) — holding")
            banded_target = state.current_amps

        # ---- Stale-data freeze + post-stale recovery gate ----
        if sse_stale:
            log(f"SOLAR: SSE stale (age={sse_age:.0f}s) — holding {state.current_amps}A")
            banded_target = state.current_amps
        elif banded_target > state.current_amps and post_stale:
            log(f"SOLAR: post-stale recovery ({state.fresh_recovery_count}/"
                f"{SSE_FRESH_RECOVERY_LOOPS} fresh) — holding {state.current_amps}A")
            banded_target = state.current_amps

        log(f"Target: {raw_target}A raw -> {banded_target}A banded "
            f"(current: {state.current_amps}A, basis: med={decision_excess:.0f}W "
            f"v={voltage_v if voltage_v else 'fallback-240V'})")

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
                # v4.0.27: switched from excess_smooth to decision_excess so
                # the wife-Tesla-app guard lines up with the new median basis.
                # current_amps==0 sentinel preserved (project_tesla_app_workflow).
                if decision_excess <= 0 and state.current_amps == 0:
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
