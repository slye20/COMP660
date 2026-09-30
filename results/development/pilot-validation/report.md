# DNS connection-reuse results

Measured attempts: **3,750** across **1** run(s).

Latency estimates include successful responses only. Warm estimates require observed connection reuse. Timeouts and other failures remain in the reliability denominators. CIs resample paired blocks, not individual queries.

| Network/profile | Resolver | Protocol | Paired queries | Blocks | Saved ms | Reduction | 95% CI (ms) |
|---|---|---|---:|---:|---:|---:|---|
| wifi/unshaped | cloudflare | doh | 150 | 30 | 42.12 | 62.7% | 39.53 to 44.52 |
| wifi/unshaped | cloudflare | dot | 149 | 30 | 43.16 | 64.9% | 39.62 to 46.62 |
| wifi/unshaped | google | doh | 150 | 30 | 30.21 | 58.7% | 27.97 to 32.04 |
| wifi/unshaped | google | dot | 150 | 30 | 33.53 | 66.3% | 31.99 to 35.20 |
| wifi/unshaped | nextdns | doh | 150 | 30 | 150.55 | 70.5% | 136.46 to 165.14 |
| wifi/unshaped | nextdns | dot | 150 | 30 | 153.68 | 69.7% | 135.91 to 171.54 |
| wifi/unshaped | opendns | doh | 150 | 30 | 54.06 | 57.8% | 48.20 to 58.93 |
| wifi/unshaped | opendns | dot | 150 | 30 | 62.63 | 64.6% | 58.26 to 67.23 |
| wifi/unshaped | quad9 | doh | 144 | 30 | 40.03 | 58.2% | 34.31 to 45.57 |
| wifi/unshaped | quad9 | dot | 88 | 29 | 41.11 | 67.4% | 38.68 to 43.68 |

## Reliability

| Resolver | Condition | Protocol/state | Attempts | Timeouts | Other failures | Warm reconnections |
|---|---|---|---:|---:|---:|---:|
| cloudflare | wifi/unshaped | do53/stateless | 150 | 0 | 0 | 0 |
| cloudflare | wifi/unshaped | doh/cold | 150 | 0 | 0 | 0 |
| cloudflare | wifi/unshaped | doh/warm | 150 | 0 | 0 | 0 |
| cloudflare | wifi/unshaped | dot/cold | 150 | 0 | 0 | 0 |
| cloudflare | wifi/unshaped | dot/warm | 150 | 0 | 0 | 1 |
| google | wifi/unshaped | do53/stateless | 150 | 0 | 0 | 0 |
| google | wifi/unshaped | doh/cold | 150 | 0 | 0 | 0 |
| google | wifi/unshaped | doh/warm | 150 | 0 | 0 | 0 |
| google | wifi/unshaped | dot/cold | 150 | 0 | 0 | 0 |
| google | wifi/unshaped | dot/warm | 150 | 0 | 0 | 0 |
| nextdns | wifi/unshaped | do53/stateless | 150 | 0 | 0 | 0 |
| nextdns | wifi/unshaped | doh/cold | 150 | 0 | 0 | 0 |
| nextdns | wifi/unshaped | doh/warm | 150 | 0 | 0 | 0 |
| nextdns | wifi/unshaped | dot/cold | 150 | 0 | 0 | 0 |
| nextdns | wifi/unshaped | dot/warm | 150 | 0 | 0 | 0 |
| opendns | wifi/unshaped | do53/stateless | 150 | 0 | 0 | 0 |
| opendns | wifi/unshaped | doh/cold | 150 | 0 | 0 | 0 |
| opendns | wifi/unshaped | doh/warm | 150 | 0 | 0 | 0 |
| opendns | wifi/unshaped | dot/cold | 150 | 0 | 0 | 0 |
| opendns | wifi/unshaped | dot/warm | 150 | 0 | 0 | 0 |
| quad9 | wifi/unshaped | do53/stateless | 150 | 0 | 0 | 0 |
| quad9 | wifi/unshaped | doh/cold | 150 | 0 | 0 | 0 |
| quad9 | wifi/unshaped | doh/warm | 150 | 0 | 3 | 3 |
| quad9 | wifi/unshaped | dot/cold | 150 | 0 | 26 | 0 |
| quad9 | wifi/unshaped | dot/warm | 150 | 0 | 24 | 22 |

## Interpretation limits

- A single network condition cannot establish the proposed network-quality relationship; missing conditions are not imputed.
- A run samples one vantage point and time window. Queries within a connection are dependent. Even blocks may share temporal network conditions.
- Fixed popular names favor resolver cache hits but do not guarantee them; DNS cache state is separate from connection state.
- At 100–150 trials, p99 is based on roughly the largest two or three observations; treat it as descriptive, not a precise tail estimate.
- Mann–Whitney tests compare block-mean effects, with Holm correction across all exported comparisons. They do not prove causation.
- Breakeven values use setup/N + warm latency, omit failures, and assume constant service time. A missing crossover can mean reuse never matches Do53 under this model.
- Profiles jointly vary latency, jitter, loss and rate. Exploratory per-predictor regressions cannot identify independent causal effects.
- No packet capture is required by this harness. Its setup values are application-observed TCP/TLS intervals, not pure propagation RTT.

See summary.csv for quantiles, variance and IQR; paired-blocks.csv for the inference units; comparisons.csv for corrected tests; breakeven.csv and regressions.csv for model outputs.
