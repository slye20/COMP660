# Results and remaining collection

For the complete progress narrative, see the [project report](../docs/PROJECT_REPORT.md),
covering completed implementation, preliminary findings, and remaining work.

Start with the [separate Wi-Fi repeat](wifi-repeat-2026-09-30/report.md).
It uses the corrected harness, a different randomized schedule (seed 632), and
temporary macOS idle-sleep inhibition. The report includes uncertainty intervals,
failures, latency distributions, connection-amortization curves, and exact run context.

The repeat collected **3,750 measured queries** across **25 configurations**, with
**150 attempts per configuration**: 3,708 successes, 40 other errors, and 2 timeouts.
It completed in about 8.6 minutes, with no network-unreachable observations or
large timestamp gaps. All successful DoH requests used HTTP/2; all successful
encrypted requests used TLS 1.3. The raw-data integrity audit passed.

Thirty-seven DoT EOF errors and three DoH disconnects were observed against Quad9.
The other two failures were one Cloudflare DoH connect timeout and one NextDNS
UDP timeout. These are observations from this vantage point, not an identification
of the infrastructure cause. Warm reconnections are logged and excluded from
verified-reuse latency estimates.

Among matched successful queries, mean block-weighted reductions ranged from
55.5% to 76.8% across the ten encrypted resolver/protocol configurations. All ten
block-bootstrap 95% intervals for the mean reduction in milliseconds were above
zero in this repeat. This supports a reuse benefit at this vantage point; it does
not establish the proposed relationship across network conditions.

The [interrupted-network run](wifi-interrupted-2026-09-30/report.md) is retained
separately. It contains 3,750 measured attempts, with 3,387 successful resolutions,
329 other errors, and 34 timeouts. Across all phases, 294 observations reported
network-unreachable errors, and 14 large wall-clock gaps were detected. Those
failure rates should not be interpreted as resolver-specific service reliability.

The original pilot and development-only analyses are under `development/` and are
excluded from the research reports. Their instrumentation preceded the final
nonblocking TLS socket and consistent response-parsing timing fixes.

Each report directory includes the raw observations exported to CSV, aggregate
tables, block-level inference data, Holm-adjusted Mann–Whitney comparisons,
breakeven model outputs, quality diagnostics, PNG figures, input hashes, and a
copy of the analysis source. Original append-only logs and measurement source
snapshots are under [data/](../data/README.md).

## What the current data can establish

These are single-vantage-point observations of connection reuse over the available
Wi-Fi network. Read cold/warm latency estimates together with the reliability
tables and collection-quality notes. Bootstrap intervals quantify variation among
the sampled blocks; they do not describe every network, location, or time of day.

The four emulated profiles and real cellular anchor remain uncollected. The
regression files explicitly report insufficient distinct conditions instead of
fitting a network-quality relationship from Wi-Fi alone. The Linux Mininet runner
and cellular collection commands are implemented in the [runbook](../docs/RUNBOOK.md).
Actual Mininet execution remains unvalidated on Linux; command generation and
platform guards were checked here. No synthetic results fill those missing cells.

Implementation verification: 28 offline tests passed, including an end-to-end
mocked collection/audit/analysis test. Editable package installation and dependency
consistency checks passed. The repeat's raw-data and analysis-source hashes,
25 × 150 trial coverage, report links, and generated figures were verified.
