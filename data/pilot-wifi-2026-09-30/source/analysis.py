"""Success-conditioned latency estimates, block-level uncertainty, and plots."""

from collections import defaultdict
import csv
import hashlib
import itertools
import json
import math
import os
from pathlib import Path

import numpy as np
from scipy import stats


KEYS = ("network", "profile", "resolver", "protocol")


def key(row):
    return tuple(row[k] for k in KEYS)


def eligible(row):
    return (row["status"] == "ok" and row.get("total_ms") is not None
            and (row["state"] != "warm" or row.get("reused") is True))


def write_csv(path, rows, columns=None):
    columns = columns or list(dict.fromkeys(k for r in rows for k in r))
    with Path(path).open("w", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def summarize(rows):
    groups = defaultdict(list)
    for row in rows:
        groups[(*key(row), row["state"])].append(row)
    summaries = []
    for group, values in sorted(groups.items()):
        good = [r for r in values if eligible(r)]
        times = [r["total_ms"] for r in good]
        n = len(values)
        timeouts = sum(r["status"] == "timeout" for r in values)
        failures = sum(r["status"] not in ("ok", "timeout") for r in values)
        row = dict(zip((*KEYS, "state"), group))
        row.update(attempts=n, successes=sum(r["status"] == "ok" for r in values),
                   eligible_successes=len(good), timeouts=timeouts, other_failures=failures,
                   timeout_rate=timeouts / n, failure_rate=failures / n,
                   unsuccessful_rate=(timeouts + failures) / n,
                   warm_reconnections=sum(r["state"] == "warm" and r["new_connection"] for r in values),
                   independent_blocks=len({(r["run_id"], r["block"]) for r in good}))
        for name in ("mean_ms", "p50_ms", "p95_ms", "p99_ms", "variance_ms2", "iqr_ms", "mean_setup_ms", "mean_query_ms"):
            row[name] = None
        if times:
            row.update(mean_ms=float(np.mean(times)), p50_ms=float(np.percentile(times, 50)),
                       p95_ms=float(np.percentile(times, 95)), p99_ms=float(np.percentile(times, 99)),
                       variance_ms2=float(np.var(times, ddof=1)) if len(times) > 1 else None,
                       iqr_ms=float(np.percentile(times, 75) - np.percentile(times, 25)),
                       mean_setup_ms=float(np.mean([r["setup_ms"] for r in good])),
                       mean_query_ms=float(np.mean([r["query_ms"] for r in good])))
        summaries.append(row)
    return summaries


def paired_blocks(rows):
    pairs = defaultdict(dict)
    for r in rows:
        if r["state"] in ("cold", "warm"):
            pair = (*key(r), r["run_id"], r["block"], r["index"], r["domain"])
            pairs[pair][r["state"]] = r
    blocks = defaultdict(list)
    for pair, states in pairs.items():
        if set(states) != {"cold", "warm"} or not all(eligible(r) for r in states.values()):
            continue
        cold, warm = states["cold"], states["warm"]
        blocks[pair[:6]].append((cold["total_ms"], warm["total_ms"]))
    results = []
    for group, values in sorted(blocks.items()):
        c, w = np.array(values).T
        results.append({**dict(zip(KEYS, group[:4])), "run_id": group[4], "block": group[5],
                        "matched_pairs": len(values), "cold_mean_ms": float(c.mean()),
                        "warm_mean_ms": float(w.mean()), "effect_ms": float((c - w).mean())})
    return results


def effects(blocks, bootstrap=5000, seed=631):
    groups = defaultdict(list)
    for r in blocks:
        groups[key(r)].append(r)
    rng = np.random.default_rng(seed)
    output = []
    for group, values in sorted(groups.items()):
        samples = np.array([r["effect_ms"] for r in values])
        n = len(samples)
        lo = hi = None
        if n >= 2:
            draws = rng.choice(samples, size=(bootstrap, n), replace=True).mean(axis=1)
            lo, hi = map(float, np.percentile(draws, [2.5, 97.5]))
        c = float(np.mean([r["cold_mean_ms"] for r in values]))
        w = float(np.mean([r["warm_mean_ms"] for r in values]))
        output.append({**dict(zip(KEYS, group)), "blocks": n,
                       "matched_pairs": sum(r["matched_pairs"] for r in values),
                       "cold_mean_ms": c, "warm_mean_ms": w,
                       "effect_ms": float(samples.mean()),
                       "reduction_pct": 100 * (c - w) / c,
                       "ci95_low_ms": lo, "ci95_high_ms": hi})
    return output


def comparisons(blocks):
    groups = defaultdict(list)
    for r in blocks:
        groups[key(r)].append(r["effect_ms"])
    output = []
    for (a, x), (b, y) in itertools.combinations(sorted(groups.items()), 2):
        same_condition = a[:2] == b[:2] and a[3] == b[3] and a[2] != b[2]
        same_resolver = a[2:] == b[2:] and a[:2] != b[:2]
        if not (same_condition or same_resolver) or min(len(x), len(y)) < 2:
            continue
        u, p = stats.mannwhitneyu(x, y, alternative="two-sided", method="auto")
        output.append({"comparison": "resolver" if same_condition else "condition",
                       "a": "/".join(a), "b": "/".join(b), "n_a_blocks": len(x),
                       "n_b_blocks": len(y), "u": float(u), "p_raw": float(p)})
    # One Holm family across every comparison produced by this analysis.
    running = 0.0
    for rank, row in enumerate(sorted(output, key=lambda r: r["p_raw"])):
        running = max(running, min(1.0, (len(output) - rank) * row["p_raw"]))
        row["p_holm"] = running
    return output


def breakeven(summaries):
    lookup = {(*key(r), r["state"]): r for r in summaries}
    output = []
    for r in summaries:
        if r["state"] != "cold" or r["mean_ms"] is None:
            continue
        group = key(r)
        warm = lookup.get((*group, "warm"))
        udp = lookup.get((*group[:3], "do53", "stateless"))
        if not warm or warm["mean_ms"] is None:
            continue
        setup, query = r["mean_setup_ms"], warm["mean_ms"]
        base = udp["mean_ms"] if udp else None
        delta = base - query if base is not None else None
        output.append({**dict(zip(KEYS, group)), "setup_ms": setup, "warm_ms": query,
                       "do53_mean_ms": base,
                       "n_to_5pct_setup_overhead": max(1, math.ceil(setup / (0.05 * query))) if query > 0 else None,
                       "n_to_match_do53": max(1, math.ceil(setup / delta)) if delta is not None and delta > 0 else None,
                       "do53_status": "finite_model_estimate" if delta is not None and delta > 0 else
                           "missing_control" if delta is None else "no_finite_crossover",
                       "model": "setup/N + warm_mean; success-conditioned, constant latency assumption"})
    return output


def regressions(effect_rows, summaries, metadata):
    """Exploratory OLS over condition means, not over pseudoreplicated queries."""
    udp = {key(r)[:3]: r["mean_ms"] for r in summaries if r["protocol"] == "do53"}
    profile_info = {}
    for m in metadata:
        if m.get("emulation"):
            profile_info[(m["network"], m["profile"])] = m["emulation"]["parameters"]
    groups = defaultdict(list)
    for r in effect_rows:
        groups[(r["resolver"], r["protocol"])].append(r)
    output = []
    for (resolver, protocol), values in sorted(groups.items()):
        for predictor in ("do53_mean_ms", "added_rtt_ms", "downlink_loss_pct"):
            xy = []
            for r in values:
                if predictor == "do53_mean_ms":
                    x = udp.get((r["network"], r["profile"], resolver))
                else:
                    x = profile_info.get((r["network"], r["profile"]), {}).get(predictor)
                if x is not None:
                    xy.append((x, r["effect_ms"]))
            out = {"resolver": resolver, "protocol": protocol, "predictor": predictor,
                   "n_conditions": len(xy), "status": "insufficient_distinct_conditions"}
            if len(xy) >= 3 and len({x for x, _ in xy}) >= 3:
                x, y = np.array(xy).T
                fit = stats.linregress(x, y)
                out.update(status="exploratory_confounded_profiles", slope=float(fit.slope),
                           intercept=float(fit.intercept), r_squared=float(fit.rvalue ** 2),
                           p_value=float(fit.pvalue), slope_stderr=float(fit.stderr))
            output.append(out)
    return output


def cumulative_batches(all_rows):
    groups = defaultdict(list)
    for r in all_rows:
        if r["phase"] in ("measurement", "warmup") and r["state"] in ("warm", "cold"):
            groups[(*key(r), r["run_id"], r["block"])].append(r)
    output = []
    for group, values in sorted(groups.items()):
        cold = sorted((r for r in values if r["state"] == "cold"), key=lambda r: r["index"])
        warm = sorted((r for r in values if r["state"] == "warm"), key=lambda r: r["index"])
        # Warmup is a real paid query; include its full cost. Compare N cold
        # queries with first N of the warm sequence, including the first query.
        if not warm or warm[0]["phase"] != "warmup":
            continue
        csum = wsum = 0.0
        for i, (c, w) in enumerate(zip(cold, warm), start=1):
            if c["status"] != "ok" or w["status"] != "ok":
                break
            csum += c["total_ms"]
            wsum += w["total_ms"]
            output.append({**dict(zip(KEYS, group[:4])), "run_id": group[4], "block": group[5],
                           "n": i, "cold_cumulative_ms": csum, "reuse_cumulative_ms": wsum,
                           "saved_ms": csum - wsum})
    return output


def plots(out, rows, effect_rows, summaries, curves):
    os.environ.setdefault("MPLCONFIGDIR", str(out / ".mplconfig"))
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False,
                         "figure.dpi": 140, "savefig.bbox": "tight"})
    conditions = sorted({(r["network"], r["profile"]) for r in rows})
    resolvers = sorted({r["resolver"] for r in rows})
    for protocol in ("dot", "doh"):
        matrix = np.full((len(resolvers), len(conditions)), np.nan)
        for r in effect_rows:
            if r["protocol"] == protocol:
                matrix[resolvers.index(r["resolver"]), conditions.index((r["network"], r["profile"]))] = r["effect_ms"]
        fig, ax = plt.subplots(figsize=(max(5, len(conditions) * 1.8), 4))
        cmap = plt.get_cmap("RdBu_r").copy()
        cmap.set_bad("#dddddd")
        finite = np.abs(matrix[np.isfinite(matrix)])
        limit = max(1, float(finite.max())) if len(finite) else 1
        im = ax.imshow(matrix, cmap=cmap, vmin=-limit, vmax=limit, aspect="auto")
        ax.set_xticks(range(len(conditions)), ["\n".join(c) for c in conditions])
        ax.set_yticks(range(len(resolvers)), resolvers)
        for i in range(len(resolvers)):
            for j in range(len(conditions)):
                v = matrix[i, j]
                ax.text(j, i, "missing" if np.isnan(v) else f"{v:.1f}", ha="center", va="center",
                        color="white" if np.isfinite(v) and abs(v) > .6 * limit else "black")
        ax.set_title(f"{protocol.upper()}: cold − reused mean latency (ms)\nMatched, equally weighted blocks; positive favors reuse")
        fig.colorbar(im, ax=ax, label="Milliseconds saved per query")
        fig.savefig(out / f"amortization-{protocol}.png")
        plt.close(fig)
    for condition in conditions:
        fig, axes = plt.subplots(1, len(resolvers), figsize=(3.3 * len(resolvers), 3.8), squeeze=False)
        colors = {("do53", "stateless"): "#555555", ("dot", "cold"): "#bb6600",
                  ("dot", "warm"): "#e4b65a", ("doh", "cold"): "#125c99", ("doh", "warm"): "#69b2d2"}
        for ax, resolver in zip(axes[0], resolvers):
            for (protocol, state), color in colors.items():
                times = sorted(r["total_ms"] for r in rows if (r["network"], r["profile"]) == condition
                               and r["resolver"] == resolver and r["protocol"] == protocol
                               and r["state"] == state and eligible(r))
                if times:
                    ax.step(times, np.arange(1, len(times) + 1) / len(times), where="post",
                            label=f"{protocol} {state}", color=color)
            ax.set(xlabel="Resolution latency (ms)", ylabel="Empirical CDF", title=resolver, ylim=(0, 1.02))
            ax.set_xscale("log")
            ax.grid(alpha=.15)
        handles, labels = axes[0, 0].get_legend_handles_labels()
        if handles:
            fig.legend(handles, labels, loc="lower center", ncol=5, bbox_to_anchor=(.5, -.06))
        fig.suptitle(f"{' / '.join(condition)} · successful queries; warm requires verified reuse")
        fig.tight_layout()
        fig.savefig(out / f"latency-cdf-{'-'.join(condition)}.png")
        plt.close(fig)
    if effect_rows:
        fig, ax = plt.subplots(figsize=(9, max(4, len(effect_rows) * .32)))
        for i, r in enumerate(effect_rows):
            ax.plot(r["effect_ms"], i, "o", color="#12628e")
            if r["ci95_low_ms"] is not None:
                ax.plot([r["ci95_low_ms"], r["ci95_high_ms"]], [i, i], color="#12628e")
        ax.set_yticks(range(len(effect_rows)), [f"{r['resolver']} {r['protocol']} {r['network']}/{r['profile']}" for r in effect_rows])
        ax.axvline(0, color="gray", linestyle="--")
        ax.set(xlabel="Cold − warm (ms), block-bootstrap 95% CI", title="Connection-reuse benefit")
        fig.tight_layout()
        fig.savefig(out / "effect-confidence.png")
        plt.close(fig)
    if curves:
        fig, ax = plt.subplots(figsize=(8, 5))
        groups = defaultdict(lambda: defaultdict(list))
        for r in curves:
            groups[key(r)][r["n"]].append(r["reuse_cumulative_ms"] / r["n"])
        for group, ns in sorted(groups.items()):
            ax.plot(sorted(ns), [np.mean(ns[n]) for n in sorted(ns)], marker=".", label="/".join(group))
        ax.set(xlabel="Queries on connection (includes first handshake)", ylabel="Mean cumulative time / N (ms)",
               title="Observed connection setup amortization")
        ax.legend(fontsize=7, loc="upper left", bbox_to_anchor=(1, 1))
        fig.savefig(out / "batch-amortization.png")
        plt.close(fig)


def analyze(args):
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=False)
    all_rows, metadata, sources = [], [], []
    seen_runs = set()
    for path in args.runs:
        path = Path(path)
        m = json.loads((path / "metadata.json").read_text())
        if m["run_id"] in seen_runs:
            raise ValueError("Duplicate run supplied; refusing to double-count data")
        seen_runs.add(m["run_id"])
        metadata.append(m)
        raw = (path / "observations.jsonl").read_bytes()
        sources.append({"run": str(path), "sha256": hashlib.sha256(raw).hexdigest(), "state": m["state"]})
        all_rows.extend(json.loads(line) for line in raw.splitlines() if line.strip())
    # Do not silently pool incompatible designs under the same condition label.
    signatures = defaultdict(set)
    for m in metadata:
        signature = {k: m[k] for k in ("domains", "qtype", "batch_size", "timeout_seconds_per_io", "pause_seconds", "resolvers")}
        signature["emulation"] = m.get("emulation", {}).get("parameters") if m.get("emulation") else None
        signatures[(m["network"], m["profile"])].add(json.dumps(signature, sort_keys=True))
    if any(len(s) > 1 for s in signatures.values()):
        raise ValueError("Incompatible runs share a network/profile label; analyze them separately")
    rows = [r for r in all_rows if r["phase"] == "measurement"]
    if not rows:
        raise ValueError("No measurement rows")
    summary = summarize(rows)
    blocks = paired_blocks(rows)
    effect_rows = effects(blocks, args.bootstrap, args.seed)
    tests = comparisons(blocks)
    curves = cumulative_batches(all_rows)
    write_csv(out / "observations.csv", all_rows)
    write_csv(out / "summary.csv", summary)
    write_csv(out / "paired-blocks.csv", blocks, [*KEYS, "run_id", "block", "matched_pairs", "cold_mean_ms", "warm_mean_ms", "effect_ms"])
    write_csv(out / "amortization.csv", effect_rows, [*KEYS, "blocks", "matched_pairs", "cold_mean_ms", "warm_mean_ms", "effect_ms", "reduction_pct", "ci95_low_ms", "ci95_high_ms"])
    write_csv(out / "comparisons.csv", tests, ["comparison", "a", "b", "n_a_blocks", "n_b_blocks", "u", "p_raw", "p_holm"])
    write_csv(out / "breakeven.csv", breakeven(summary))
    write_csv(out / "regressions.csv", regressions(effect_rows, summary, metadata))
    write_csv(out / "batch-curves.csv", curves)
    plots(out, rows, effect_rows, summary, curves)
    (out / "provenance.json").write_text(json.dumps({"inputs": sources, "bootstrap_draws": args.bootstrap,
                                                    "seed": args.seed, "analysis": "block-weighted effects; success-conditioned"}, indent=2) + "\n")
    lines = ["# DNS connection-reuse results", "", f"Measured attempts: **{len(rows):,}** across **{len(metadata)}** run(s).",
             "", "Latency estimates include successful responses only. Warm estimates require observed connection reuse. "
             "Timeouts and other failures remain in the reliability denominators. CIs resample paired blocks, not individual queries.", "",
             "| Network/profile | Resolver | Protocol | Paired queries | Blocks | Saved ms | Reduction | 95% CI (ms) |",
             "|---|---|---|---:|---:|---:|---:|---|"]
    for r in effect_rows:
        ci = f"{r['ci95_low_ms']:.2f} to {r['ci95_high_ms']:.2f}" if r["ci95_low_ms"] is not None else "insufficient blocks"
        lines.append(f"| {r['network']}/{r['profile']} | {r['resolver']} | {r['protocol']} | {r['matched_pairs']} | "
                     f"{r['blocks']} | {r['effect_ms']:.2f} | {r['reduction_pct']:.1f}% | {ci} |")
    lines.extend(["", "## Reliability", "", "| Resolver | Condition | Protocol/state | Attempts | Timeouts | Other failures | Warm reconnections |",
                  "|---|---|---|---:|---:|---:|---:|"])
    for r in summary:
        lines.append(f"| {r['resolver']} | {r['network']}/{r['profile']} | {r['protocol']}/{r['state']} | {r['attempts']} | "
                     f"{r['timeouts']} | {r['other_failures']} | {r['warm_reconnections']} |")
    lines.extend(["", "## Interpretation limits", "",
                  "- A single network condition cannot establish the proposed network-quality relationship; missing conditions are not imputed.",
                  "- A run samples one vantage point and time window. Queries within a connection are dependent. Even blocks may share temporal network conditions.",
                  "- Fixed popular names favor resolver cache hits but do not guarantee them; DNS cache state is separate from connection state.",
                  "- The p99 at 120 trials is based on roughly the largest two observations; treat it as descriptive, not a precise tail estimate.",
                  "- Mann–Whitney tests compare block-mean effects, with Holm correction across all exported comparisons. They do not prove causation.",
                  "- Breakeven values use setup/N + warm latency, omit failures, and assume constant service time. A missing crossover can mean reuse never matches Do53 under this model.",
                  "- Profiles jointly vary latency, jitter, loss and rate. Exploratory per-predictor regressions cannot identify independent causal effects.",
                  "- No packet capture is required by this harness. Its setup values are application-observed TCP/TLS intervals, not pure propagation RTT.",
                  "", "See summary.csv for quantiles, variance and IQR; paired-blocks.csv for the inference units; "
                  "comparisons.csv for corrected tests; breakeven.csv and regressions.csv for model outputs.", ""])
    (out / "report.md").write_text("\n".join(lines))
    print(f"Analysis saved to {out}")
