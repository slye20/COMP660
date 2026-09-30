#!/usr/bin/env python3
"""Probe, collect, audit and analyze one manually identified real network."""

import argparse
from datetime import datetime, timezone
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--network", choices=("wifi", "cellular", "wired", "unknown"), required=True)
    parser.add_argument("--note", default="Network label supplied by operator")
    parser.add_argument("--output", help="New directory; defaults to data/<network>-<UTC timestamp>")
    parser.add_argument("--trials", type=int, default=150)
    parser.add_argument("--batch-size", type=int, default=5)
    parser.add_argument("--seed", type=int, default=631)
    args = parser.parse_args()
    if args.trials < 1 or args.batch_size < 1:
        parser.error("trials and batch-size must be positive")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = Path(args.output or ROOT / "data" / f"{args.network}-{stamp}").resolve()
    out.mkdir(parents=True, exist_ok=False)
    base = [sys.executable, "-m", "dnsbench"]
    steps = [
        ["probe", "--output", str(out / "preflight.json")],
        ["run", "--network", args.network, "--note", args.note, "--trials", str(args.trials),
         "--batch-size", str(args.batch_size), "--seed", str(args.seed), "--output", str(out / "run")],
        ["audit", str(out / "run"), "--output", str(out / "audit.json")],
        ["analyze", str(out / "run"), "--output", str(out / "analysis")],
    ]
    for step in steps:
        subprocess.run(base + step, cwd=ROOT, check=True)
    print(f"Finished: {out / 'analysis/report.md'}")


if __name__ == "__main__":
    main()
