"""Randomized paired blocks with durable, append-only JSONL observations."""

from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import math
from pathlib import Path
import platform
import random
import time
import uuid

from .transports import Session

PROTOCOLS = ("do53", "dot", "doh")


def utc():
    return datetime.now(timezone.utc).isoformat()


def read_inputs(resolvers_path, domains_path, names=None):
    resolvers = json.loads(Path(resolvers_path).read_text())
    if len({r["name"] for r in resolvers}) != len(resolvers):
        raise ValueError("Duplicate resolver names")
    if names:
        missing = set(names) - {r["name"] for r in resolvers}
        if missing:
            raise ValueError(f"Unknown resolvers: {sorted(missing)}")
        resolvers = [r for r in resolvers if r["name"] in names]
    domains = [s.strip() for s in Path(domains_path).read_text().splitlines()
               if s.strip() and not s.lstrip().startswith("#")]
    if not domains or not resolvers:
        raise ValueError("Need at least one domain and resolver")
    return resolvers, domains


def build_schedule(resolvers, protocols, domains, trials, batch_size, seed):
    rng = random.Random(seed)
    schedule = []
    # Identical domain workload across resolvers/protocols for each block.
    for block in range(math.ceil(trials / batch_size)):
        count = min(batch_size, trials - block * batch_size)
        names = []
        while len(names) < count:
            shuffled = list(domains)
            rng.shuffle(shuffled)
            names.extend(shuffled)
        for resolver in resolvers:
            for protocol in protocols:
                states = ["stateless"] if protocol == "do53" else ["cold", "warm"]
                rng.shuffle(states)
                schedule.append({"resolver": resolver["name"], "protocol": protocol,
                                 "block": block, "domains": names[:count], "states": states})
    rng.shuffle(schedule)
    return schedule


def run(args):
    resolvers, domains = read_inputs(args.resolvers_file, args.domains_file, args.resolvers)
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=False)  # Never overwrite or append to another run.
    run_id = uuid.uuid4().hex
    source_files = sorted(Path(__file__).parent.glob("*.py"))
    source_hash = hashlib.sha256(b"".join(p.name.encode() + p.read_bytes() for p in source_files)).hexdigest()
    metadata = {
        "schema_version": 1, "run_id": run_id, "started_utc": utc(), "state": "running",
        "network": args.network, "network_note": args.note,
        "profile": args.profile, "emulation": None,
        "seed": args.seed, "trials_per_state": args.trials, "batch_size": args.batch_size,
        "timeout_seconds_per_io": args.timeout, "pause_seconds": args.pause,
        "qtype": args.qtype, "resolvers": resolvers, "domains": domains,
        "protocols": args.protocols, "source_sha256": source_hash,
        "platform": platform.platform(), "python": platform.python_version(),
        "packages": {p: importlib.metadata.version(p) for p in ("dnspython", "httpx", "httpcore", "h2")},
        "design": "randomized paired blocks, fixed cache-favored names, IPv4 pinned endpoints, no retries",
        "proxy_environment_used": False,
    }
    if args.emulation_metadata:
        metadata["emulation"] = json.loads(Path(args.emulation_metadata).read_text())
    if args.profile != "unshaped" and not metadata["emulation"]:
        raise ValueError("Emulated profile requires --emulation-metadata; a label does not apply netem")
    schedule = build_schedule(resolvers, args.protocols, domains, args.trials, args.batch_size, args.seed)
    (out / "schedule.json").write_text(json.dumps(schedule, indent=2) + "\n")
    meta_path = out / "metadata.json"
    meta_path.write_text(json.dumps(metadata, indent=2) + "\n")
    by_name = {r["name"]: r for r in resolvers}
    counters = {}
    sequence = 0

    with (out / "observations.jsonl").open("x", buffering=1) as log:
        def measure(session, resolver, protocol, state, domain, block, index, phase):
            nonlocal sequence
            stamp = utc()
            result = session.query(domain, args.qtype).dict()
            row = {"run_id": run_id, "sequence": sequence, "timestamp_utc": stamp,
                   "network": args.network, "profile": args.profile,
                   "resolver": resolver["name"], "protocol": protocol, "state": state,
                   "domain": domain, "qtype": args.qtype, "block": block, "index": index,
                   "phase": phase, **result}
            log.write(json.dumps(row, allow_nan=False) + "\n")
            sequence += 1
            if phase == "measurement":
                key = result["status"]
                counters[key] = counters.get(key, 0) + 1
            time.sleep(args.pause)
            return row

        try:
            # Logged cache priming is not proof of cache residency. The same
            # fixed workload is repeated and paired; TTL/answers are recorded.
            if not args.no_prime:
                for resolver in resolvers:
                    for protocol in args.protocols:
                        s = Session(resolver, protocol, args.timeout)
                        try:
                            for index, domain in enumerate(domains):
                                row = measure(s, resolver, protocol, "prime", domain, -1, index, "cache_prime")
                                if row["status"] != "ok":
                                    break  # Priming unavailable endpoints is not a measurement trial.
                        finally:
                            s.close()
            for position, job in enumerate(schedule):
                resolver = by_name[job["resolver"]]
                protocol = job["protocol"]
                for state in job["states"]:
                    s = Session(resolver, protocol, args.timeout)
                    try:
                        if state == "warm":
                            measure(s, resolver, protocol, state, job["domains"][0], job["block"], -1, "warmup")
                        for index, domain in enumerate(job["domains"]):
                            if state == "cold" and index:
                                s.close()
                                s = Session(resolver, protocol, args.timeout)
                            measure(s, resolver, protocol, state, domain, job["block"], index, "measurement")
                    finally:
                        s.close()
                print(f"[{position + 1}/{len(schedule)}] {resolver['name']} {protocol} block={job['block']} {counters}", flush=True)
            metadata["state"] = "complete"
        except BaseException:
            metadata["state"] = "interrupted"
            raise
        finally:
            metadata["finished_utc"] = utc()
            metadata["measurement_counts"] = counters
            metadata["rows"] = sequence
            meta_path.write_text(json.dumps(metadata, indent=2) + "\n")
    print(f"Saved {sequence} observations to {out}", flush=True)


def probe(args):
    resolvers, domains = read_inputs(args.resolvers_file, args.domains_file, args.resolvers)
    records = []
    for resolver in resolvers:
        for protocol in args.protocols:
            session = Session(resolver, protocol, args.timeout)
            try:
                for i in range(2):
                    row = {"timestamp_utc": utc(), "resolver": resolver["name"],
                           "ip": resolver["ip"], "protocol": protocol, "attempt": i,
                           **session.query(domains[0], args.qtype).dict()}
                    records.append(row)
                    print(f"{resolver['name']:12s} {protocol:5s} {i} {row['status']:9s} "
                          f"total={row['total_ms']} reused={row['reused']} {row['error']}", flush=True)
            finally:
                session.close()
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x") as file:
        json.dump(records, file, indent=2)
        file.write("\n")
