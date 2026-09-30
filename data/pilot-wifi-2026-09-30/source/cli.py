import argparse
from pathlib import Path

from .experiment import PROTOCOLS, probe, run

ROOT = Path(__file__).resolve().parent.parent


def positive(value):
    value = int(value)
    if value < 1:
        raise argparse.ArgumentTypeError("must be positive")
    return value


def main():
    parser = argparse.ArgumentParser(description="DNS connection-reuse measurement and analysis")
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("probe", "run"):
        p = sub.add_parser(command)
        p.add_argument("--resolvers-file", default=str(ROOT / "config/resolvers.json"))
        p.add_argument("--domains-file", default=str(ROOT / "config/domains.txt"))
        p.add_argument("--resolvers", nargs="+")
        p.add_argument("--protocols", nargs="+", choices=PROTOCOLS, default=list(PROTOCOLS))
        p.add_argument("--timeout", type=float, default=3.0)
        p.add_argument("--qtype", choices=("A", "AAAA"), default="A")
        p.add_argument("--output", required=True)
        if command == "run":
            p.add_argument("--network", choices=("wifi", "cellular", "wired", "unknown", "emulated"), required=True)
            p.add_argument("--note", default="")
            p.add_argument("--profile", default="unshaped")
            p.add_argument("--emulation-metadata")
            p.add_argument("--trials", type=positive, default=120)
            p.add_argument("--batch-size", type=positive, default=10)
            p.add_argument("--seed", type=int, default=631)
            p.add_argument("--pause", type=float, default=0.05)
            p.add_argument("--no-prime", action="store_true")
    p = sub.add_parser("analyze")
    p.add_argument("runs", nargs="+")
    p.add_argument("--output", required=True)
    p.add_argument("--bootstrap", type=positive, default=5000)
    p.add_argument("--seed", type=int, default=631)
    args = parser.parse_args()
    if args.command in ("probe", "run") and args.timeout <= 0:
        parser.error("--timeout must be positive")
    if args.command == "run" and args.pause < 0:
        parser.error("--pause cannot be negative")
    if args.command == "run":
        run(args)
    elif args.command == "probe":
        probe(args)
    else:
        from .analysis import analyze
        analyze(args)
