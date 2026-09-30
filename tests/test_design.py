from collections import Counter
from types import SimpleNamespace

import pytest

from dnsbench.experiment import build_schedule, read_inputs, run
from dnsbench.transports import Result


def test_schedule_pairs_domains_and_exact_counts():
    resolvers = [{"name": "a"}, {"name": "b"}]
    schedule = build_schedule(resolvers, ["do53", "dot", "doh"], ["a.org", "b.org"], 13, 5, 631)
    assert schedule == build_schedule(resolvers, ["do53", "dot", "doh"], ["a.org", "b.org"], 13, 5, 631)
    counts = Counter()
    domains_by_block = {}
    for job in schedule:
        for state in job["states"]:
            counts[job["resolver"], job["protocol"], state] += len(job["domains"])
        prior = domains_by_block.setdefault(job["block"], job["domains"])
        assert prior == job["domains"]
    assert len(counts) == 10
    assert set(counts.values()) == {13}
    assert {tuple(j["states"]) for j in schedule if j["protocol"] != "do53"} == {("cold", "warm"), ("warm", "cold")}


def test_unknown_resolver_rejected():
    with pytest.raises(ValueError, match="Unknown resolvers"):
        read_inputs("config/resolvers.json", "config/domains.txt", ["typo"])


def test_experiment_logs_priming_and_reconnection_separately(tmp_path, monkeypatch):
    import json
    import dnsbench.experiment as experiment

    class FakeSession:
        def __init__(self, resolver, protocol, timeout):
            self.calls = 0
            self.protocol = protocol
            import uuid
            self.connection_id = uuid.uuid4().hex

        def query(self, domain, qtype):
            reused = self.calls > 0 and self.protocol != "do53"
            self.calls += 1
            return Result(status="ok", total_ms=10 if reused else 30, setup_ms=0 if reused else 20,
                          query_ms=10, reused=reused, new_connection=not reused,
                          connection_id=self.connection_id, tls_resumed=False)

        def close(self):
            pass

    monkeypatch.setattr(experiment, "Session", FakeSession)
    args = SimpleNamespace(resolvers_file="config/resolvers.json", domains_file="config/domains.txt",
                           resolvers=["cloudflare"], output=str(tmp_path / "run"), network="unknown", note="unit test",
                           profile="unshaped", seed=1, trials=7, batch_size=3, timeout=1, pause=0,
                           qtype="A", protocols=["dot"], emulation_metadata=None, no_prime=False)
    run(args)
    rows = [json.loads(line) for line in (tmp_path / "run/observations.jsonl").read_text().splitlines()]
    assert Counter(r["phase"] for r in rows) == {"cache_prime": 20, "warmup": 3, "measurement": 14}
    measured = [r for r in rows if r["phase"] == "measurement"]
    assert all(r["reused"] for r in measured if r["state"] == "warm")
    assert not any(r["reused"] for r in measured if r["state"] == "cold")
    assert json.loads((tmp_path / "run/metadata.json").read_text())["state"] == "complete"
    from dnsbench.audit import audit
    assert audit(tmp_path / "run")["passed"]
    from dnsbench.analysis import analyze
    analyze(SimpleNamespace(runs=[str(tmp_path / "run")], output=str(tmp_path / "analysis"), bootstrap=50, seed=631))
    assert (tmp_path / "analysis/report.md").is_file()
    assert (tmp_path / "analysis/effect-confidence.png").is_file()
    assert json.loads((tmp_path / "analysis/quality.json").read_text())[0]["passed"]
    # A complete, arithmetically valid run can still have an interruption warning.
    from datetime import datetime, timedelta
    rows[-1]["timestamp_utc"] = (datetime.fromisoformat(rows[-1]["timestamp_utc"]) + timedelta(minutes=5)).isoformat()
    (tmp_path / "run/observations.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    checked = audit(tmp_path / "run")
    assert checked["passed"] and len(checked["large_time_gaps"]) == 1
    rows[-1]["total_ms"] += 1
    (tmp_path / "run/observations.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    assert not audit(tmp_path / "run")["passed"]
    with pytest.raises(FileExistsError):
        run(args)
