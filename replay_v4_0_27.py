#!/usr/bin/env python3
"""v4.0.27 SOLAR-mode decision replay harness.

Reads a phase2_telemetry CSV (charger_YYYY-MM-DD.csv) and re-evaluates each
row through the proposed v4.0.27 gates:

  - median-based decisions (excess_median replaces excess_smooth)
  - fast-drop on max_import_5s >= 3000W AND excess_smooth < 0
    (smooth chosen over median because median lags transients — see
    08:58 + 18:12 May 7 events; median is used for steady-state decisions
    where its 60s window suppresses noise)
  - TWC tracking gate on UPWARD steps only
  - SSE stale freeze (envoy_age_max > 30s)
  - post-stale recovery counter (need 2 fresh loops < 15s before resuming UP)
  - per-phase voltage correction in calculate_target_amps

Per-row independent evaluation: at each loop the harness uses the live
`cmd_a` value (state.current_amps as observed) and asks, given the row's
median/mi5/age/twc/voltage signals, what v4.0.27 would have done. It does
NOT simulate the full alternate timeline — once the simulation diverges
from the live run, downstream signals would too. This harness's metric
is "count of BLE commands the v4.0.27 logic would have suppressed or
added at the moment they were considered," which is well-defined.

The fresh_recovery_count IS carried across rows (it's the only piece of
v4.0.27 state that depends on history rather than just the current row).
"""

import argparse
import csv
from dataclasses import dataclass

# Constants mirror the proposed v4.0.27 values in solar_charger_twc.py
MIN_AMPS = 6
MAX_AMPS = 48
VOLTAGE = 240
AMP_STABILITY_BAND = 2
AMP_CHANGE_THRESHOLD = 2
MAX_AMP_STEP = 4

FAST_DROP_IMPORT_W = 3000
SSE_STALE_THRESHOLD_S = 30
SSE_FRESH_THRESHOLD_S = 15
SSE_FRESH_RECOVERY_LOOPS = 2
TWC_TRACKING_TOLERANCE_A = 4


def calculate_target_amps(excess_w, baseline_a, voltage_v):
    if voltage_v is not None and 100 <= voltage_v <= 130:
        divisor = voltage_v * 2
    else:
        divisor = VOLTAGE
    delta = int(excess_w / divisor)
    if delta > MAX_AMP_STEP:
        delta = MAX_AMP_STEP
    target = baseline_a + delta
    return max(MIN_AMPS, min(target, MAX_AMPS))


@dataclass
class ReplayState:
    fresh_recovery_count: int = 0


def fnum(s, default=None):
    try:
        return float(s) if s not in (None, '') else default
    except (ValueError, TypeError):
        return default


def inum(s, default=None):
    try:
        return int(s) if s not in (None, '') else default
    except (ValueError, TypeError):
        return default


def decide(row, current_amps, st):
    """Return (action, amps, reason) for a single row.

    action ∈ {'issue', 'hold'}.
    """
    median = fnum(row['excess_median'], 0.0)
    smooth = fnum(row['excess_smooth_w'], 0.0)
    mi5 = fnum(row['max_import_5s'], 0.0)
    age = fnum(row['envoy_age_max'], 0.0)
    voltage_v = fnum(row['voltage_v'])
    twc = fnum(row['twc_actual_a'])

    # Update fresh_recovery_count BEFORE making the decision (matches
    # proposed code order).
    if age is not None and age > SSE_STALE_THRESHOLD_S:
        st.fresh_recovery_count = 0
    elif age is not None and age < SSE_FRESH_THRESHOLD_S:
        st.fresh_recovery_count = min(
            st.fresh_recovery_count + 1, SSE_FRESH_RECOVERY_LOOPS + 1
        )

    sse_stale = age is not None and age > SSE_STALE_THRESHOLD_S
    post_stale = st.fresh_recovery_count < SSE_FRESH_RECOVERY_LOOPS

    # Fast-drop short-circuits the regular decision path.
    # Uses excess_smooth (3-sample 30s) — it leads median on transient cliffs
    # because the 60s median is dragged up by older healthy samples for
    # ~30-60s after a cloud edge. Median is still used below for steady-state
    # ramp decisions, where the 60s window suppresses noise.
    if (mi5 is not None and mi5 >= FAST_DROP_IMPORT_W
            and smooth is not None and smooth < 0
            and not sse_stale):
        if current_amps > MIN_AMPS:
            return ('issue', MIN_AMPS,
                    f'fast-drop(mi5={mi5:.0f},smooth={smooth:.0f})')
        return ('hold', None, f'fast-drop signal but cmd already {current_amps}A')

    v_for_calc = voltage_v if (voltage_v is not None and voltage_v > 0) else None
    raw = calculate_target_amps(median, current_amps, v_for_calc)
    banded = max(MIN_AMPS, (raw // AMP_STABILITY_BAND) * AMP_STABILITY_BAND)

    gates = []

    # TWC tracking gate — UP-step only
    if (banded > current_amps
            and twc is not None
            and twc < (current_amps - TWC_TRACKING_TOLERANCE_A)):
        gates.append(f'twc-gate(twc={twc:.1f},cmd={current_amps})')
        banded = current_amps

    if sse_stale:
        gates.append(f'sse-stale(age={age:.0f}s)')
        banded = current_amps
    elif banded > current_amps and post_stale:
        gates.append(f'post-stale({st.fresh_recovery_count}/{SSE_FRESH_RECOVERY_LOOPS})')
        banded = current_amps

    reason = ' / '.join(gates) if gates else f'med={median:.0f}W'
    if abs(banded - current_amps) >= AMP_CHANGE_THRESHOLD:
        return ('issue', banded, reason)
    return ('hold', None, reason + ' (within threshold)')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('csv', help='phase2_telemetry CSV')
    ap.add_argument('--charging-only', action='store_true',
                    help='Restrict to rows where charging_state == Charging')
    ap.add_argument('--window', metavar='HH:MM-HH:MM',
                    help='Restrict by time-of-day window (HH:MM:SS-HH:MM:SS allowed)')
    ap.add_argument('--verbose', '-v', action='store_true')
    args = ap.parse_args()

    win_start = win_end = None
    if args.window:
        a, b = args.window.split('-')
        win_start, win_end = a.strip(), b.strip()

    st = ReplayState()
    actual_ble = sim_ble = 0
    same = different = suppressed = added = 0
    rows = 0
    examples = {'suppressed': [], 'added': [], 'different': []}

    with open(args.csv) as f:
        for row in csv.DictReader(f):
            ts = row['ts']
            hms = ts[11:19]
            if win_start and hms < win_start:
                continue
            if win_end and hms > win_end:
                continue
            if args.charging_only and row.get('charging_state') != 'Charging':
                continue

            cmd = inum(row.get('cmd_a'))
            if cmd is None:
                continue
            rows += 1

            actual_was_ble = (row.get('ble_cmd') == 'charging-set-amps')
            actual_arg = inum(row.get('ble_arg'))

            action, sim_amps, reason = decide(row, cmd, st)
            sim_was_ble = (action == 'issue')

            if actual_was_ble:
                actual_ble += 1
            if sim_was_ble:
                sim_ble += 1

            if actual_was_ble and sim_was_ble:
                if actual_arg == sim_amps:
                    same += 1
                else:
                    different += 1
                    if len(examples['different']) < 15:
                        examples['different'].append(
                            (ts, cmd, actual_arg, sim_amps, reason))
            elif actual_was_ble and not sim_was_ble:
                suppressed += 1
                if len(examples['suppressed']) < 25:
                    examples['suppressed'].append(
                        (ts, cmd, actual_arg, reason))
            elif sim_was_ble and not actual_was_ble:
                added += 1
                if len(examples['added']) < 15:
                    examples['added'].append((ts, cmd, sim_amps, reason))

            if args.verbose and (actual_was_ble or sim_was_ble):
                a_tag = f'BLE→{actual_arg}A' if actual_was_ble else '  hold  '
                s_tag = f'BLE→{sim_amps}A' if sim_was_ble else '  hold  '
                print(f'  {ts}  cmd={cmd:>2}A  actual:{a_tag:<10} '
                      f'sim:{s_tag:<10}  {reason}')

    print()
    print(f'Rows processed: {rows}')
    print(f'Actual  BLE charging-set-amps: {actual_ble}')
    print(f'v4.0.27 BLE charging-set-amps: {sim_ble}  '
          f'(net {sim_ble - actual_ble:+d})')
    print(f'  same amp:                          {same}')
    print(f'  different amp (both issued):       {different}')
    print(f'  suppressed (actual yes, sim no):   {suppressed}')
    print(f'  added (sim yes, actual no):        {added}')

    if examples['suppressed']:
        print('\nSuppressed (gate would have blocked):')
        for ts, cmd, arg, reason in examples['suppressed']:
            print(f'  {ts}  cmd={cmd:>2}A actual→{arg}A   {reason}')
    if examples['added']:
        print('\nAdded (v4.0.27 would issue BLE, actual did not):')
        for ts, cmd, sim_amps, reason in examples['added']:
            print(f'  {ts}  cmd={cmd:>2}A sim→{sim_amps}A  {reason}')
    if examples['different']:
        print('\nDifferent amps (both issued, different value):')
        for ts, cmd, arg, sim_amps, reason in examples['different']:
            print(f'  {ts}  cmd={cmd:>2}A actual→{arg}A vs sim→{sim_amps}A   {reason}')


if __name__ == '__main__':
    main()
