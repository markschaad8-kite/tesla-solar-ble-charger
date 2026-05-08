#!/usr/bin/env python3
"""
Solar Charge Daily Stats - passive observer
Analyzes yesterday's solar-charger journal logs and appends a daily summary.
Run via cron (see deploy/crontab.example).

Default output: ~/solar_charge_stats.log (override with SOLAR_CHARGE_STATS_LOG).
"""

import os
import subprocess
import re
import sys
from datetime import datetime, timedelta
from collections import defaultdict

OUTPUT_LOG = os.path.expanduser(
    os.environ.get("SOLAR_CHARGE_STATS_LOG", "~/solar_charge_stats.log")
)

def get_logs(date: datetime) -> list[str]:
    since = date.strftime("%Y-%m-%d 00:00:00")
    until = (date + timedelta(days=1)).strftime("%Y-%m-%d 00:00:00")
    result = subprocess.run(
        ["journalctl", "-u", "solar-charger", f"--since={since}", f"--until={until}", "--no-pager"],
        capture_output=True, text=True
    )
    # Deduplicate: podman and solar-charger[...] both log the same lines
    lines = []
    seen = set()
    for line in result.stdout.splitlines():
        if "podman[" in line:
            continue
        key = re.sub(
            r'^[A-Z][a-z]+ \d+ \d+:\d+:\d+ [^ ]+ solar-charger\[\d+\]: ',
            '',
            line,
        )
        if key not in seen:
            seen.add(key)
            lines.append(line)
    return lines


def parse_logs(lines: list[str]) -> dict:
    stats = {
        "date": None,
        "modes_seen": set(),
        "ble_commands": [],          # list of (time_str, amps)
        "solar_loops": [],           # list of (time_str, prod_w, excess_raw_w, excess_smooth_w, current_amps)
        "large_drops": [],           # (time_str, from_amps, to_amps, excess_w)
        "grid_import_loops": 0,      # loops where smoothed excess < -200W in SOLAR mode
        "night_stops": 0,
        "mode_sleeps": defaultdict(int),  # mode -> loop count
    }

    current_amps = 0
    current_mode = None
    prev_amps = None

    time_re = re.compile(r'\[(\d{2}:\d{2}:\d{2})\]')
    solar_re = re.compile(r'Solar: (\d+)W prod, ([-\d]+)W excess \(smoothed: [\d]+W / ([-\d]+)W\)')
    target_re = re.compile(r'Target: \d+A raw -> (\d+)A banded \(current: (\d+)A\)')
    ble_re = re.compile(r'BLE >>> charging-set-amps (\d+)')
    sleep_re = re.compile(r'Sleeping \d+s \(mode=(\w+), amps=(\d+)\)')
    night_re = re.compile(r'NIGHT_STOP|night.*stop|stopping.*night', re.I)

    for line in lines:
        tm = time_re.search(line)
        time_str = tm.group(1) if tm else "??"

        # Mode from sleep line
        sm = sleep_re.search(line)
        if sm:
            current_mode = sm.group(1)
            current_amps = int(sm.group(2))
            stats["mode_sleeps"][current_mode] += 1
            stats["modes_seen"].add(current_mode)

        # Solar data
        sol = solar_re.search(line)
        if sol and current_mode in ("SOLAR", "CALENDAR_WAITING", None):
            prod_w = int(sol.group(1))
            excess_raw = int(sol.group(2))
            excess_smooth = int(sol.group(3))
            stats["solar_loops"].append((time_str, prod_w, excess_raw, excess_smooth, current_amps))
            if current_mode == "SOLAR" and prod_w > 100 and excess_smooth < -200:
                stats["grid_import_loops"] += 1

        # BLE amp command
        ble = ble_re.search(line)
        if ble:
            new_amps = int(ble.group(1))
            stats["ble_commands"].append((time_str, new_amps))
            if prev_amps is not None:
                drop = prev_amps - new_amps
                if drop >= 8:
                    # Use smoothed excess from the most recent daytime solar loop
                    daytime_ctx = [(es, er) for _, p, er, es, _ in stats["solar_loops"] if p > 100]
                    excess_ctx = daytime_ctx[-1][1] if daytime_ctx else 0  # raw excess for context
                    stats["large_drops"].append((time_str, prev_amps, new_amps, excess_ctx))
            prev_amps = new_amps

        if night_re.search(line):
            if "night_stop_sent" not in line and "False" not in line:
                stats["night_stops"] += 1

    return stats


def summarize(stats: dict, date: datetime) -> str:
    date_str = date.strftime("%Y-%m-%d (%a)")
    ble = stats["ble_commands"]
    solar = stats["solar_loops"]
    drops = stats["large_drops"]
    mode_counts = stats["mode_sleeps"]

    # Filter to daytime solar loops (prod > 100W)
    daytime = [(t, p, er, es, a) for t, p, er, es, a in solar if p > 100]

    if not daytime and not ble:
        return f"\n=== {date_str} === [no solar charging activity]\n"

    # Amp oscillation: count direction reversals in BLE commands
    ble_amps = [a for _, a in ble if a > 0]
    reversals = 0
    for i in range(1, len(ble_amps) - 1):
        if (ble_amps[i] > ble_amps[i-1] and ble_amps[i] > ble_amps[i+1]) or \
           (ble_amps[i] < ble_amps[i-1] and ble_amps[i] < ble_amps[i+1]):
            reversals += 1

    avg_excess = sum(es for _, _, _, es, _ in daytime) / len(daytime) if daytime else 0
    pct_grid_import = (stats["grid_import_loops"] / len(daytime) * 100) if daytime else 0

    # Distribution of amp levels (daytime SOLAR only)
    amp_counts = defaultdict(int)
    for _, _, _, _, a in daytime:
        amp_counts[a] += 1
    top_amps = sorted(amp_counts.items(), key=lambda x: -x[1])[:5]
    amp_dist = ", ".join(f"{a}A:{c}" for a, c in top_amps)

    # Max and min amps during daytime
    if daytime:
        max_amp = max(a for _, _, _, _, a in daytime)
        min_amp = min(a for _, _, _, _, a in daytime if a > 0) if any(a > 0 for _, _, _, _, a in daytime) else 0
    else:
        max_amp = min_amp = 0

    # BLE rate: commands per hour of daytime
    if daytime and len(daytime) > 2:
        first_t = datetime.strptime(daytime[0][0], "%H:%M:%S")
        last_t = datetime.strptime(daytime[-1][0], "%H:%M:%S")
        hours = (last_t - first_t).seconds / 3600 or 1
        ble_per_hr = len(ble) / hours
    else:
        ble_per_hr = 0

    modes_str = ", ".join(sorted(stats["modes_seen"]))

    lines = [
        f"\n=== {date_str} ===",
        f"  Modes active : {modes_str}",
        f"  Solar loops  : {len(daytime)} (daytime, prod>100W)",
        f"  Avg excess   : {avg_excess:+.0f}W (smoothed)  |  Grid import loops: {stats['grid_import_loops']} ({pct_grid_import:.0f}%)",
        f"  BLE amp cmds : {len(ble)} total  ({ble_per_hr:.1f}/hr)  |  Oscillation reversals: {reversals}",
        f"  Amp range    : {min_amp}A – {max_amp}A  |  Top levels: {amp_dist}",
    ]

    if drops:
        lines.append(f"  Large drops  : {len(drops)}x (>=8A single loop)")
        for t, frm, to, exc in drops[:5]:
            lines.append(f"    {t}  {frm}A -> {to}A  (excess at cmd: {exc:+d}W)")
        if len(drops) > 5:
            lines.append(f"    ... and {len(drops)-5} more")
    else:
        lines.append(f"  Large drops  : none")

    # Mode breakdown
    solar_loops_total = mode_counts.get("SOLAR", 0) + mode_counts.get("CALENDAR_WAITING", 0)
    away_loops = mode_counts.get("AWAY", 0)
    night_loops = mode_counts.get("NIGHT_STOP", 0)
    lines.append(f"  Loop counts  : SOLAR={mode_counts.get('SOLAR',0)}, CAL_WAIT={mode_counts.get('CALENDAR_WAITING',0)}, "
                 f"EMERGENCY={mode_counts.get('EMERGENCY',0)}, MANUAL={mode_counts.get('MANUAL',0)}, "
                 f"NIGHT_STOP={night_loops}, AWAY={away_loops}")

    return "\n".join(lines) + "\n"


def main():
    # Default: analyze yesterday.
    # --today  : analyze today so far
    # --date YYYY-MM-DD : analyze a specific date
    if "--today" in sys.argv:
        target_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    elif "--date" in sys.argv:
        idx = sys.argv.index("--date")
        target_date = datetime.strptime(sys.argv[idx + 1], "%Y-%m-%d")
    else:
        target_date = (datetime.now() - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)

    lines = get_logs(target_date)
    if not lines:
        print(f"No logs found for {target_date.date()}")
        return

    stats = parse_logs(lines)
    summary = summarize(stats, target_date)

    print(summary)

    with open(OUTPUT_LOG, "a") as f:
        f.write(summary)

    print(f"Appended to {OUTPUT_LOG}")


if __name__ == "__main__":
    main()
