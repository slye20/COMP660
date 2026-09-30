import pytest

from dnsbench.analysis import breakeven, comparisons, cumulative_batches, effects, paired_blocks, regressions, summarize


def row(state="cold", value=30, block=0, index=0, status="ok", **kwargs):
    return dict(network="wifi", profile="unshaped", resolver="a", protocol="dot", run_id="run",
                state=state, total_ms=value if status == "ok" else None, setup_ms=20 if state == "cold" else 0,
                query_ms=10, reused=state == "warm", new_connection=state == "cold", block=block,
                index=index, domain="example.com", status=status, phase="measurement") | kwargs


def test_quantiles_exclude_failures_and_false_warm():
    rows = [row("warm", 10), row("warm", 20, index=1), row("warm", 3000, index=2, status="timeout"),
            row("warm", 100, index=3, reused=False, new_connection=True)]
    s = summarize(rows)[0]
    assert s["mean_ms"] == 15
    assert s["p50_ms"] == 15
    assert s["variance_ms2"] == 50
    assert s["iqr_ms"] == 5
    assert s["successes"] == 3
    assert s["eligible_successes"] == 2
    assert s["timeout_rate"] == .25
    assert s["warm_reconnections"] == 1


def test_pairing_requires_matched_domain_run_block_and_success():
    rows = [row(), row("warm", 10), row(block=1), row("warm", 2, block=1, domain="different.org"),
            row(block=2), row("warm", 10, block=2, status="error")]
    blocks = paired_blocks(rows)
    assert len(blocks) == 1
    assert blocks[0]["effect_ms"] == 20
    assert blocks[0]["matched_pairs"] == 1


def test_block_weighting_is_not_query_weighting():
    rows = [row(value=100), row("warm", 10)]
    for i in range(5):
        rows.extend([row(value=20, block=1, index=i), row("warm", 10, block=1, index=i)])
    result = effects(paired_blocks(rows), bootstrap=1000)[0]
    assert result["effect_ms"] == 50
    assert result["matched_pairs"] == 6
    assert result["blocks"] == 2
    assert result["ci95_low_ms"] <= 50 <= result["ci95_high_ms"]


def test_reproducible_bootstrap():
    blocks = paired_blocks([row(value=30 + b, block=b, state=s) for b in range(4) for s in ("cold", "warm")])
    assert effects(blocks, 100, 123) == effects(blocks, 100, 123)


def test_no_invented_confidence_interval_from_one_block():
    result = effects(paired_blocks([row(), row("warm", 10)]))[0]
    assert result["ci95_low_ms"] is None
    assert result["ci95_high_ms"] is None


def test_holm_corrects_all_tests():
    blocks = []
    for resolver, effect in (("a", 10), ("b", 100), ("c", 200)):
        for block in range(8):
            blocks.append(dict(network="wifi", profile="unshaped", resolver=resolver, protocol="dot", effect_ms=effect + block))
    tests = comparisons(blocks)
    assert len(tests) == 3
    assert all(t["p_raw"] <= t["p_holm"] <= 1 for t in tests)
    assert tests[0]["p_holm"] == pytest.approx(tests[0]["p_raw"] * 3)


@pytest.mark.parametrize("udp,expected", [(20, 2), (10, None), (5, None)])
def test_breakeven_handles_no_finite_crossover(udp, expected):
    rows = [row(), row("warm", 10), row("stateless", udp, protocol="do53", setup_ms=0, query_ms=udp)]
    result = breakeven(summarize(rows))[0]
    assert result["n_to_match_do53"] == expected
    assert result["n_to_5pct_setup_overhead"] == 40


def test_cumulative_curve_includes_initial_connection_cost():
    rows = [row("warm", 30, index=-1, phase="warmup", reused=False, new_connection=True),
            row("warm", 10), row("warm", 10, index=1)]
    curve = cumulative_batches(rows)
    assert [r["reuse_cumulative_ms"] for r in curve] == [30, 40, 50]
    assert [r["n"] for r in curve] == [1, 2, 3]


def test_failed_or_reconnected_batch_does_not_generate_fake_curve():
    rows = [row("warm", 30, index=-1, phase="warmup", reused=False, new_connection=True),
            row("warm", 10, reused=False, new_connection=True)]
    assert len(cumulative_batches(rows)) == 1


def test_regression_refuses_single_condition():
    effect_rows = effects(paired_blocks([row(), row("warm", 10)]))
    results = regressions(effect_rows, summarize([row("stateless", 20, protocol="do53")]), [])
    assert len(results) == 3
    assert all(r["status"] == "insufficient_distinct_conditions" for r in results)


def test_exploratory_regression_uses_condition_means():
    effect_rows = []
    summaries = []
    metadata = []
    for index, delay in enumerate((10, 50, 100, 200)):
        profile = f"p{index}"
        effect_rows.append(dict(network="emulated", profile=profile, resolver="a", protocol="dot", effect_ms=2 * delay + 5))
        summaries.append(dict(network="emulated", profile=profile, resolver="a", protocol="do53", mean_ms=delay + 10))
        metadata.append(dict(network="emulated", profile=profile, emulation={"parameters": {"added_rtt_ms": delay, "downlink_loss_pct": index}}))
    results = regressions(effect_rows, summaries, metadata)
    rtt = next(r for r in results if r["predictor"] == "added_rtt_ms")
    assert rtt["n_conditions"] == 4
    assert rtt["slope"] == pytest.approx(2)
    assert rtt["intercept"] == pytest.approx(5)
    assert rtt["r_squared"] == pytest.approx(1)
