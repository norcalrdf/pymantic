#!/usr/bin/env python
"""Wait until the machine is quiet, then run a benchmark command, so its
timings are not taken while other work competes for the CPU.

    python benchmarks/when_quiet.py -- python benchmarks/compare_implementations.py
    python benchmarks/when_quiet.py --load 1.5 --checks 5 -- python benchmarks/timing.py doid

Quiet means the 1-minute load average is under --load and no other Python
or Node process is using more than --busy percent of a core, on --checks
checks in a row --interval seconds apart. Other Python and Node processes
compete with the benchmark directly; anything else shows in the load
average. Progress goes to stderr; the load and busiest processes are
printed when the command starts and when it ends, so a run disturbed part
way through can be spotted. Exits with the command's status.
"""

import argparse
import os
import subprocess
import sys
import time


def busiest_competitor():
    """CPU percent of the busiest Python or Node process other than this one."""
    lines = subprocess.run(
        ["ps", "-Ao", "pid=,pcpu=,comm="], capture_output=True, text=True, check=True
    ).stdout.splitlines()
    busiest = 0.0
    for line in lines:
        pid, cpu, command = line.split(None, 2)
        if int(pid) == os.getpid():
            continue
        name = os.path.basename(command).lower()
        if "python" in name or "node" in name:
            busiest = max(busiest, float(cpu))
    return busiest


def snapshot(label):
    load = os.getloadavg()
    top = subprocess.run(
        ["ps", "-Ao", "pcpu=,comm=", "-r"], capture_output=True, text=True, check=True
    ).stdout.splitlines()[:3]
    print(f"{label} {time.strftime('%H:%M:%S')} load {load[0]:.2f}", file=sys.stderr)
    for line in top:
        print(f"  {line.strip()}", file=sys.stderr)


def main():
    ap = argparse.ArgumentParser(
        description=__doc__.splitlines()[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="\n".join(__doc__.splitlines()[2:]),
    )
    ap.add_argument("--load", type=float, default=2.0, help="1-minute load below this")
    ap.add_argument("--busy", type=float, default=50.0, help="competitor CPU percent")
    ap.add_argument("--checks", type=int, default=3, help="quiet checks in a row")
    ap.add_argument(
        "--interval", type=float, default=60.0, help="seconds between checks"
    )
    ap.add_argument("command", nargs=argparse.REMAINDER, help="-- command to run")
    args = ap.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        ap.error("give the command to run after --")

    quiet = 0
    while quiet < args.checks:
        load = os.getloadavg()[0]
        busy = busiest_competitor()
        quiet = quiet + 1 if load < args.load and busy < args.busy else 0
        print(
            f"{time.strftime('%H:%M:%S')} load {load:.2f}, busiest Python/Node "
            f"{busy:.0f}%, quiet checks {quiet}/{args.checks}",
            file=sys.stderr,
            flush=True,
        )
        if quiet < args.checks:
            time.sleep(args.interval)
    snapshot("start")
    status = subprocess.run(command).returncode
    snapshot("end")
    sys.exit(status)


if __name__ == "__main__":
    main()
