# DNS Connection Reuse Project Progress Report

**COMP631 — Networked and Distributed Systems**  
**Project:** Characterizing DoT/DoH Connection-Reuse Amortization Across Resolvers and Network Conditions  
**Authors:** Jaymeson Koh and Samuel Lim  
**Status covered:** Implementation and measurements collected on September 30, 2026

The project has an implemented DNS measurement and analysis pipeline and a completed preliminary Wi-Fi experiment across all five proposed resolvers. In the primary experiment, reusing encrypted connections reduced mean resolution latency by **55.5% to 76.8%** across the ten resolver/protocol combinations, when comparing matched successful queries. However, the central research question—how that benefit changes jointly with resolver and network condition—remains open. The four emulated conditions and the cellular anchor have not been collected, and the Linux testbed still needs execution and validation.

## Research objective

The project examines how much DNS-over-TLS (DoT) and DNS-over-HTTPS (DoH) benefit from reusing an established connection instead of opening a new connection for every query. Traditional DNS over UDP (Do53) supplies a connectionless control. The proposed comparison crosses five resolvers—Cloudflare, Google, Quad9, NextDNS, and OpenDNS—with four emulated network profiles and two real network anchors.

The intended contribution is an empirical comparison of connection-reuse benefits across those conditions, including whether a consistent relationship exists between network quality and the benefit of reuse. It does not attempt to identify the exact internal infrastructure responsible for resolver differences. The original scope and bibliography are preserved in the [project proposal](../readme.md).

## Work completed

| Area | Completed work | Verification status |
|---|---|---|
| Protocol measurement | Do53 using UDP, DoT using TLS, and DoH with HTTP/2 support | All five configured resolvers answered live probes over all three protocols |
| Connection handling | New sessions for cold queries, persistent sessions for warm batches, and observed reuse/reconnection tracking | Exercised by tests and live measurements |
| Timing | Separate TCP/TLS setup and post-setup query time, plus total resolution time | Arithmetic and connection-state checks passed; packet-level timing validation remains additional work |
| Experimental scheduling | Matched domain sequences, randomized resolver/protocol/block order, and randomized cold/warm order | Saved schedules and trial coverage audited |
| Data preservation | Raw JSONL observations, metadata, schedules, source snapshots, dependency versions, and hashes | Primary dataset integrity audit passed |
| Analysis | Latency distributions, reliability rates, block-bootstrap intervals, Mann–Whitney comparisons, Holm correction, and amortization models | Analysis executed on collected data |
| Reporting | CSV tables, latency plots, confidence intervals, reliability plots, and cumulative amortization curves | Primary report and figures generated and inspected |
| Testbed implementation | Mininet runner, private virtual link, downlink shaping, validation commands, and cleanup logic | Command generation and platform guards checked; actual Linux execution pending |
| Automation and tests | Collection, audit, and analysis commands; installation instructions; test suite | 28 offline tests passed, including a mocked end-to-end experiment; editable installation and dependency checks passed |

The implementation is in [dnsbench](../dnsbench/), configuration files are in [config](../config/), and collection scripts are in [scripts](../scripts/). The [runbook](RUNBOOK.md) documents installation and execution. The passing tests establish checks of the implemented behavior; they do not substitute for testing Mininet on a real Linux kernel.

## Measurement method

Each resolver has five configurations: Do53, cold DoT, warm DoT, cold DoH, and warm DoH. At 150 measured attempts per configuration, one network condition contains **5 × 5 × 150 = 3,750 measured attempts**. Priming and warmup requests are logged separately and are excluded from that count.

Cold encrypted queries use a new connection and TLS context. Warm queries use a session that first performs a logged warmup, followed by five measured queries. Thus, each encrypted configuration has 30 blocks. A connection is classified as reused only when the instrumentation confirms reuse. A request that reconnects is retained in the intended warm condition's reliability statistics but excluded from the verified-warm latency estimate.

The workload uses 20 fixed public domains and A-record queries. Cold and warm measurements within a block use matching domain sequences. Priming favors resolver cache hits, but does not prove cache residency. “Cold” and “warm” describe connection state, not DNS cache state. Requests run sequentially with a 50 ms pause; this experiment does not measure performance under concurrent load.

Endpoints use pinned IP addresses with TLS hostname and certificate verification. This avoids including endpoint hostname lookup in setup measurements. Total resolution time includes transport-library work and response parsing. Setup time represents application-observed TCP/TLS intervals; query time is total time minus setup time. These intervals are not direct measurements of propagation RTT or isolated server processing time.

The primary effect is the successful cold-query latency minus the matching successful, verified-warm latency. Differences are averaged within each block, and block means receive equal weight. The analysis uses 5,000 bootstrap resamples of blocks for 95% confidence intervals. It does not treat all queries sharing a connection as independent samples. Failed pairs remain in the raw data and reliability counts.

## Data collected

| Dataset | Measured attempts | Successful resolutions | Other errors | Timeouts | Role |
|---|---:|---:|---:|---:|---|
| Development pilot | 3,750 | 3,697 | 53 | 0 | Excluded because it preceded timing and socket-mode corrections |
| Corrected run with network interruption | 3,750 | 3,387 | 329 | 34 | Preserved and reported separately |
| Separate Wi-Fi repeat | 3,750 | 3,708 | 40 | 2 | Primary preliminary dataset |

These counts represent attempts, not unique domain names. Including the pilot, 11,250 measured attempts were recorded; the two runs using corrected instrumentation account for 7,500. Preflight, cache-priming, and connection-warmup requests are additional observations and are not included in these totals.

The interrupted run contained 294 “Network is unreachable” observations across all phases and 14 large timestamp gaps. It spanned more than two hours. Those failures cannot be attributed to individual resolver infrastructure, so this run was not silently pooled with the repeat or cleaned by deleting its failures.

The primary repeat ran from **17:29:51 to 17:38:29 UTC on September 30, 2026**, approximately 8.6 minutes. It used a different scheduling seed and temporarily inhibited macOS idle sleep. Its audit found no network-unreachable observations or large timestamp gaps. All successful DoH requests negotiated HTTP/2, and all successful encrypted requests used TLS 1.3.

The active default interface was identified as Wi-Fi. The upstream access type, VPN state, and competing traffic were not independently verified. This is one laptop, one vantage point, and one primary observation window. Dataset locations and their intended uses are recorded in the [data inventory](../data/README.md).

## Preliminary findings

### Connection reuse reduced successful resolution latency

The following values are the matched, equally weighted block means from the primary repeat. The confidence interval applies to milliseconds saved, not to the percentage reduction.

| Resolver | Protocol | Cold mean ms | Warm mean ms | Saved ms | Reduction | 95% interval for saved ms |
|---|---|---:|---:|---:|---:|---|
| Cloudflare | DoT | 63.67 | 22.96 | 40.70 | 63.9% | 36.89–44.55 |
| Cloudflare | DoH | 71.91 | 27.84 | 44.07 | 61.3% | 39.24–49.28 |
| Google | DoT | 48.68 | 16.15 | 32.53 | 66.8% | 29.22–36.37 |
| Google | DoH | 50.05 | 19.30 | 30.75 | 61.4% | 27.33–35.34 |
| Quad9 | DoT | 61.85 | 20.81 | 41.05 | 66.4% | 36.18–48.39 |
| Quad9 | DoH | 65.08 | 28.53 | 36.54 | 56.2% | 24.12–49.71 |
| NextDNS | DoT | 211.73 | 49.06 | 162.67 | 76.8% | 148.76–176.56 |
| NextDNS | DoH | 216.45 | 63.04 | 153.42 | 70.9% | 137.67–168.74 |
| OpenDNS | DoT | 90.29 | 39.75 | 50.54 | 56.0% | 40.32–61.25 |
| OpenDNS | DoH | 79.02 | 35.15 | 43.88 | 55.5% | 38.64–49.00 |

Source: [amortization results](../results/wifi-repeat-2026-09-30/amortization.csv).

All ten confidence intervals were above zero. This supports a reuse benefit for successful queries in the measured Wi-Fi setting. NextDNS had the largest absolute reductions, but also comparatively high cold latency. A larger reduction does not imply the lowest final resolution latency or establish why that resolver behaves differently.

Each estimate includes 30 blocks. Most configurations have 150 matched successful pairs; Cloudflare DoH has 149, Quad9 DoH has 145, and Quad9 DoT has 103. The lower Quad9 counts reflect failed requests and reconnections, making reliability particularly important when interpreting those latency estimates.

![Mean latency savings and block bootstrap confidence intervals](../results/wifi-repeat-2026-09-30/effect-confidence.png)

### Reliability affected the interpretation

The primary repeat's overall successful-resolution rate was **98.88%**. Its 42 unsuccessful measured attempts consisted of:

- 37 Quad9 DoT EOF errors, indicating that the connection ended before the expected response completed.
- Three Quad9 DoH server disconnects.
- One Cloudflare DoH connection timeout.
- One NextDNS Do53 timeout.

There were also 21 connection-establishment attempts during intended warm measurements. These are not an additional set of failures to add to the 42; reconnection is a separate recorded property. The analysis excludes successful requests that established a new connection from verified-warm latency estimates.

The cause of the Quad9 disconnects has not been isolated. Server behavior, the network path, and client interaction remain possible explanations. The current results do not justify a general claim about provider reliability. The full [quality audit](../data/wifi-repeat-2026-09-30-audit.json) and [per-configuration summary](../results/wifi-repeat-2026-09-30/summary.csv) preserve the evidence.

### Resolver differences are preliminary

The analysis compared block-effect distributions between resolvers within each encrypted protocol. Fourteen of 20 two-sided Mann–Whitney comparisons had Holm-adjusted p-values below 0.05. These tests suggest differences among sampled effect distributions; they do not identify a causal infrastructure mechanism or prove differences under other network conditions. The [comparison table](../results/wifi-repeat-2026-09-30/comparisons.csv) contains all tests, including those that did not meet the threshold.

Reuse also does not automatically make encrypted DNS faster than Do53. For example, Google's successful Do53 mean was 18.34 ms, while its warm DoH mean was 19.30 ms. Its warm DoT mean was 16.15 ms. These are descriptive observations, not evidence of a universal protocol ranking.

### Breakeven results are model estimates

The analysis models average encrypted-query cost over a connection as `S/N + W`, where `S` is mean setup cost, `N` is the number of queries, and `W` is mean verified-warm latency. Comparing this with mean Do53 latency produces a finite estimated crossover only when the warm encrypted latency is below the UDP mean.

The [breakeven output](../results/wifi-repeat-2026-09-30/breakeven.csv) contains finite crossover estimates for six combinations and no finite crossover under the model for four. These are extrapolations, not directly observed thresholds. The measured sessions have five warm queries plus their initial warmup, while several modeled thresholds require much longer sessions. Longer-batch experiments are needed before presenting these values as measured breakeven behavior.

## What remains unfinished

Only **one of the six planned network conditions** has a primary measured dataset. The extra interrupted run and development pilot do not count as additional conditions.

| Remaining task | Current status | What will establish completion |
|---|---|---|
| Validate the Linux testbed | Runner implemented; not executed on Linux | Run a smoke experiment, verify shaping and Internet access, and check cleanup after success and interruption |
| Collect broadband emulation | No measurements | All 25 configurations, 150 attempts each, with shaping metadata and a passing integrity audit |
| Collect 4G-like emulation | No measurements | Same complete measurement design |
| Collect lossy emulation | No measurements | Same complete measurement design |
| Collect high-latency emulation | No measurements | Same complete measurement design |
| Collect real cellular anchor | No tethered-cellular measurements | Verify cellular routing, record network context, and collect all 25 configurations |
| Assess the network-quality relationship | Analysis code exists; data insufficient | Analyze the completed condition matrix and assess whether the observed relationships differ across resolvers |
| Validate longer-session breakeven behavior | Model estimates and short-session curves available | Measure longer batches around predicted crossover sizes and compare observations with the model |
| Strengthen repeatability and diagnostics | One primary Wi-Fi session; disconnect causes unresolved | Repeat sessions at different times and investigate recurrent disconnects without discarding unsuccessful requests |
| Complete the final research deliverables | Proposal, code, and preliminary reports available | Finalize the full study report and presentation after the missing experiments and interpretation |

At the present sampling target, the four emulated profiles require **15,000 additional measured attempts**, and the cellular anchor requires **3,750**. Thus, **18,750 additional attempts** are needed to populate the five missing conditions once, excluding validation runs, priming, warmups, and recommended replications. One complete six-condition matrix would contain 22,500 measured attempts.

## Recommended sequence for the remaining work

First, provision a dedicated Linux machine or VM and run the existing Mininet smoke test against one resolver. Verify added RTT, downlink shaping, connectivity, and cleanup before launching the full sweep. The implemented short ping and throughput checks are useful initial checks; longer local calibration is needed to characterize low loss rates and bandwidth accurately.

Second, run all four profiles with the same domain workload, batch size, pacing, and trial count. The configured values are 10, 53.3, 53.3, and 150 ms of **added RTT**, with downlink loss of 0%, 0.5%, 1.5%, and 2.1%, respectively. The delay is applied once on the downlink and is added to the existing Internet path. These profiles do not establish an absolute total RTT, and this downlink-only design is not an exact replication of the original paper's asymmetric bidirectional emulation. Optional corruption and duplication should remain separate from the core sweep.

Third, collect the cellular anchor using actual tethered cellular access. Record the carrier, tethering method, location at an appropriate level of detail, signal conditions where available, VPN state, and competing traffic. Avoid inadvertently sending the experiment through another Wi-Fi or wired connection.

Fourth, analyze the condition matrix and repeat selected experiments to test stability over time. The current regressions fit separate predictors and are exploratory. Because profiles jointly change several network properties, those fits cannot isolate the causal contribution of RTT, loss, or bandwidth. Repeated sessions and a model that explicitly compares resolver responses to network conditions would strengthen the answer to the central question. Do53 latency should remain described as a resolver-and-network response-time proxy, rather than pure network RTT.

Finally, perform longer-session measurements for the proposed crossover behavior, investigate the observed disconnects, and finish the final report and presentation. Investigations should preserve the original observations and document any client or endpoint changes as a new measurement version.

## Current conclusion

The project has completed its core software implementation and demonstrated a substantial connection-reuse benefit in a preliminary Wi-Fi experiment. The primary dataset, statistical outputs, and reproducibility records are available, with failures and the interrupted run preserved transparently. The full empirical study remains incomplete: Linux testbed validation, four emulated conditions, and the real cellular anchor are required before drawing conclusions about how connection-reuse amortization varies across network quality and resolver infrastructure.

The [results index](../results/README.md) links to the generated reports and figures. The [runbook](RUNBOOK.md) provides the commands needed to continue collection and analysis.
