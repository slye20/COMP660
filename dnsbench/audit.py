"""Check recorded experiment coverage and timing invariants without networking."""

from collections import Counter
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path


def audit(path):
    path = Path(path)
    metadata = json.loads((path / "metadata.json").read_text())
    rows = [json.loads(line) for line in (path / "observations.jsonl").read_text().splitlines() if line.strip()]
    errors = []
    warnings = []
    if metadata["state"] != "complete":
        errors.append(f"Run state is {metadata['state']}, not complete")
    if len(rows) != metadata.get("rows"):
        errors.append("Metadata row count does not match log")
    if [r["sequence"] for r in rows] != list(range(len(rows))):
        errors.append("Observation sequence has duplicates or gaps")
    if any(r["run_id"] != metadata["run_id"] for r in rows):
        errors.append("Mixed run IDs")
    sources = sorted((path / "source").glob("*.py"))
    digest = hashlib.sha256(b"".join(p.name.encode() + p.read_bytes() for p in sources)).hexdigest()
    if digest != metadata["source_sha256"]:
        errors.append("Archived source does not match recorded hash")
    measured = [r for r in rows if r["phase"] == "measurement"]
    counts = Counter((r["resolver"], r["protocol"], r["state"]) for r in measured)
    expected = {}
    for resolver in metadata["resolvers"]:
        for protocol in metadata["protocols"]:
            for state in (["stateless"] if protocol == "do53" else ["cold", "warm"]):
                expected[resolver["name"], protocol, state] = metadata["trials_per_state"]
    if counts != expected:
        errors.append("Per-configuration trial counts differ from design")
    identity = [(r["resolver"], r["protocol"], r["state"], r["block"], r["index"]) for r in measured]
    if len(identity) != len(set(identity)):
        errors.append("Duplicate measurement identities")
    schedule = json.loads((path / "schedule.json").read_text())
    jobs = {(j["resolver"], j["protocol"], j["block"]): j for j in schedule}
    for row in measured:
        job = jobs.get((row["resolver"], row["protocol"], row["block"]))
        if not job or not 0 <= row["index"] < len(job["domains"]) or row["domain"] != job["domains"][row["index"]]:
            errors.append(f"Row {row['sequence']}: does not match saved schedule")
    connections = set()
    for row in rows:
        prefix = f"Row {row['sequence']}: "
        if row["status"] == "ok":
            values = [row.get(k) for k in ("total_ms", "setup_ms", "query_ms")]
            if any(v is None or not math.isfinite(v) or v < 0 for v in values):
                errors.append(prefix + "invalid successful timing")
                continue
            if not math.isclose(row["total_ms"], row["setup_ms"] + row["query_ms"], abs_tol=1e-6):
                errors.append(prefix + "total != setup + query")
            if row["protocol"] == "do53" and row["setup_ms"] != 0:
                errors.append(prefix + "Do53 setup is nonzero")
            if row["protocol"] != "do53":
                if not row["connection_id"]:
                    errors.append(prefix + "missing connection identity")
                if row["new_connection"] == row["reused"]:
                    errors.append(prefix + "ambiguous connection state")
                if row["state"] == "cold" and not row["new_connection"]:
                    errors.append(prefix + "cold request reused a connection")
                if row["reused"] and row["setup_ms"] != 0:
                    errors.append(prefix + "reused connection has setup time")
                if row["reused"] and row["connection_id"] not in connections:
                    errors.append(prefix + "reuse without observed prior connection")
                if row["tls_resumed"]:
                    errors.append(prefix + "unexpected TLS session resumption")
        elif row["total_ms"] is not None:
            errors.append(prefix + "failed request has successful-resolution latency")
        if row["connection_id"]:
            connections.add(row["connection_id"])
    failures = Counter((r["resolver"], r["protocol"], r["error"]) for r in measured if r["status"] != "ok")
    if failures:
        warnings.append("Observed failures are retained; latency estimates are success-conditioned")
    unreachable = [r for r in rows if "Network is unreachable" in r.get("error", "")]
    if unreachable:
        warnings.append("Network-unreachable errors occurred; do not attribute this interruption to individual resolver infrastructure")
    gaps = []
    for previous, current in zip(rows, rows[1:]):
        seconds = (datetime.fromisoformat(current["timestamp_utc"]) - datetime.fromisoformat(previous["timestamp_utc"])).total_seconds()
        if seconds > max(30, metadata["timeout_seconds_per_io"] * 4 + metadata["pause_seconds"] + 5):
            gaps.append({"after_sequence": previous["sequence"], "seconds": seconds,
                         "start_utc": previous["timestamp_utc"], "end_utc": current["timestamp_utc"]})
    if gaps:
        warnings.append("Large wall-clock gaps occurred; possible suspension/interruption, not established by timing alone")
    return {"passed": not errors, "errors": errors, "warnings": warnings,
            "measurements": len(measured), "all_observations": len(rows),
            "configurations": len(counts), "status_counts": dict(Counter(r["status"] for r in measured)),
            "http_versions": dict(Counter(r["http_version"] for r in measured if r["protocol"] == "doh" and r["status"] == "ok")),
            "tls_versions": dict(Counter(r["tls_version"] for r in measured if r["protocol"] != "do53" and r["status"] == "ok")),
            "warm_reconnections": sum(r["new_connection"] for r in measured if r["state"] == "warm"),
            "network_unreachable_observations": len(unreachable), "large_time_gaps": gaps,
            "failure_details": [{"resolver": k[0], "protocol": k[1], "error": k[2], "count": v} for k, v in failures.items()]}
