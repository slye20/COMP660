# Running the DNS amortization study

The implementation measures all five proposal resolvers over Do53, DoT, and DoH.
DoT and DoH have cold and warm configurations; Do53 has one stateless control.
The default research run in the convenience scripts is 150 queries per configuration,
or 3,750 measured queries, plus cache priming and one warmup per persistent batch.
No account, NextDNS profile, or API key is needed for the configured public endpoints.

## Installation and verification

Use Python 3.11 or newer from the repository root:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[test]'
.venv/bin/python -m pytest -q
.venv/bin/python -m dnsbench --help
```

`requirements-lock.txt` records the exact dependency versions installed for the
collected macOS/Python 3.14 run. To reproduce that environment, install that file.
The editable install resolves compatible analysis dependencies on older Python
versions. HTTPX, httpcore, and dnspython are pinned because timing depends on their
APIs. DoH installs HTTP/2 support; negotiated HTTP versions are recorded.

Tests are offline: generated DNS responses and instrumented fake transports exercise
the protocol handling, with independent known-data checks of the statistics.
The live preflight checks actual public resolver connectivity, TLS, and reuse.
Offline tests alone do not validate a Linux kernel's shaping behavior.

The delivered raw data includes an interrupted-network run and a separately
collected repeat. See `data/README.md` and `results/README.md`; do not pool them
automatically. An integrity audit can pass while a dataset still has major
network-quality limitations, which are reported separately.

## Collecting a real network anchor

```sh
# New timestamped folder: preflight, raw run, audit, analysis, and figures.
.venv/bin/python scripts/collect_anchor.py --network wifi --note 'Laptop on home Wi-Fi'

# Only after the laptop is actually using a cellular tether:
.venv/bin/python scripts/collect_anchor.py --network cellular --note 'USB tether; Wi-Fi disabled; carrier and location recorded separately'
```

Network names are operator-supplied labels. The harness does not switch networks,
enable tethering, change system DNS, or infer that Wi-Fi implies a fixed-line ISP.
Keep the computer awake, avoid downloads, record VPN/background traffic, and repeat
at different times for stronger external validity. Each invocation creates a new
directory and refuses to overwrite an existing run. Interrupted observations remain
on disk, and metadata says `interrupted`; restart into a new directory, rather than
mixing connections or silently treating incomplete data as a complete run.

On macOS, prefix collection with `/usr/bin/caffeinate -i` to inhibit idle sleep
for the lifetime of the command. It cannot prevent lid closure, manual sleep,
Wi-Fi disconnection, or upstream outages. The audit flags large observation gaps
and network-unreachable errors, and the generated report surfaces those flags.

The lower-level CLI permits smaller experiments:

```sh
.venv/bin/python -m dnsbench probe --output data/my-preflight.json
.venv/bin/python -m dnsbench run --network wifi --resolvers cloudflare google \
  --trials 150 --batch-size 5 --seed 631 --timeout 3 --pause 0.05 \
  --output data/my-wifi-run --note 'Explain the measurement environment here'
.venv/bin/python -m dnsbench audit data/my-wifi-run --output data/my-wifi-audit.json
.venv/bin/python -m dnsbench analyze data/my-wifi-run --output results/my-wifi-run
```

Run defaults are 120 trials with 10-query batches; specify `--trials 150 --batch-size 5`
to match the delivered dataset and convenience scripts. `--protocols do53 dot doh`
and `--resolvers cloudflare google quad9 nextdns opendns` can select subsets.
The query type is A by default; `--qtype AAAA` asks for IPv6 records over the same
pinned IPv4 transport. Config files are editable and can be overridden with
`--resolvers-file` / `--domains-file`. These paths default to the repository's
`config/` directory; use an editable installation, or supply explicit files if
installing the package without the repository.

## Linux / Mininet sweep

This runner requires a **dedicated Linux VM or machine** with Internet access,
root privileges, network namespaces, `tc netem`, and the following tools. macOS
does not provide these Linux kernel features. No Linux VM or container runtime was
available in the collection environment, so execution has not been validated here.

Example Debian/Ubuntu preparation:

```sh
sudo apt-get update
sudo apt-get install -y python3-venv mininet iproute2 iptables iputils-ping iperf3 ethtool
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[test]'

# Inspect the shaping plan without root, even on macOS:
.venv/bin/python scripts/mininet_sweep.py --dry-run

# Small end-to-end proof of concept, on Linux:
sudo /usr/bin/python3 scripts/mininet_sweep.py --profiles broadband --resolvers cloudflare \
  --trials 10 --batch-size 5 --output data/emulation-smoke

# All four profiles and all five resolvers:
sudo /usr/bin/python3 scripts/mininet_sweep.py --trials 150 --batch-size 5 \
  --output data/emulated-full
```

Use system Python for Mininet (installed by apt); the runner invokes `.venv/bin/python`
for DNS measurements and analysis. Override `--python /absolute/path/to/venv/bin/python`
when needed. Outputs created by root can be copied or given back to the normal user
after the run. The profile order is randomized by seed, and each profile uses the
same resolver/protocol schedule for comparability. It is still useful to repeat
the entire sweep with another seed/time window to reduce profile-order confounding.

Topology: isolated `dnclient` namespace → private veth → `dngw` in the root namespace
→ scoped NAT → the real Internet. There is no OpenFlow controller or OVS dependency.
The root-side **private veth**, `dngw-eth0`, shapes only packets heading toward the
client. The physical uplink is never assigned a qdisc. The runner checks for subnet
collisions, adds tagged NAT/forwarding rules, and removes its rules and virtual links
on normal exit, exceptions, SIGINT, and SIGTERM. It restores the original IP-forwarding
value. A SIGKILL, power loss, or kernel crash cannot run cleanup; inspect the VM's
interfaces, tagged rules, and forwarding state if that happens. The runner does not
flush firewall tables or restart network services. Use one sweep per VM at a time.

Before each measurement run the script records:

- Exact `tc` command, kernel version, and qdisc state/counters.
- Unshaped gateway ping and shaped gateway ping (30 probes).
- A local three-second reverse `iperf3` result as a bandwidth sanity check.
- Offload settings (TSO/GSO/GRO disabled on both veth ends).
- An added-RTT check, which must pass before DNS measurement starts.

After collection it saves qdisc counters, audits the run, cleans up the network,
and analyzes all profiles together. A short lossy TCP throughput test need not
reach the configured cap; it is recorded, not treated as an exact rate calibration.
Thirty pings are also too few to estimate sub-percent packet loss precisely.
For publication, validate rate/loss over longer local tests and repeat the sweep.
Shaping commands and parser behavior have offline tests; actual Mininet execution
remains pending on Linux.

### Precise interpretation of the profiles

| Profile | Added RTT | Downlink jitter | Downlink packet loss | Downlink cap |
|---|---:|---:|---:|---:|
| broadband | 10 ms | 2 ms | 0% | 100 Mbit/s |
| 4g | 53.3 ms | 1 ms | 0.5% | 22.1 Mbit/s |
| lossy | 53.3 ms | 1 ms | 1.5% | 22.1 Mbit/s |
| high-latency | 150 ms | 8 ms | 2.1% | 1 Mbit/s |

These values are added to the physical path. `netem delay` delays packets once on
the downlink in this topology, so it adds approximately that much to round-trip
latency. It does **not** make the total Internet RTT equal to the configured number.
Uplink delay, loss, and rate remain unshaped. Jitter and loss are also downlink-only;
loss uses netem's independent random model. The default jitter distribution is the
netem default. The scheduling seed does not seed the kernel's loss RNG.

This explicitly resolves the proposal's conflict between the table's “RTT” heading
and its `netem delay` example. It follows the proposal's downlink-only adaptation;
it is not an exact replication of the cited paper's asymmetric bidirectional link.
Even identical netem parameters would not eliminate different physical routes,
vantage points, resolver caches, time windows, or implementation differences.
The original proposal's claim that all observed differences could then be attributed
only to resolver identity is stronger than this experimental design supports.

Optional corruption/duplication is off by default. `--optional-impairments` enables
the supplied optional values and adds `-extra` to profile names so the extra factor
cannot silently pool with the main experiment. A profile label alone never applies
emulation: the raw CLI requires `--emulation-metadata` for shaped labels.

## Instrumentation and experimental design

1. **Endpoints:** Each provider uses one pinned IPv4 address for all three protocols.
   TLS still verifies the configured hostname and certificate. DoH uses the correct
   HTTP Host / HTTP/2 authority plus HTTPX's SNI extension. No endpoint bootstrap
   DNS lookup, proxy environment, redirect, or insecure TLS bypass contaminates
   setup timing. NextDNS measures its public pinned anycast endpoint, not an
   account-specific profile or dynamically steered ultralow endpoint.
2. **Cold connections:** Each measured query gets a new session, socket, and TLS
   context. No session objects are shared between cold queries. The observed TLS
   resumption flag is logged and audited. Cold means cold connection, not cold DNS
   cache. Python object creation and CA loading are outside the timed interval.
3. **Warm connections:** Each block gets a new session and one logged warmup query.
   Five measured queries then attempt to reuse it. Actual setup/connection identity
   determines reuse; an automatic reconnection is recorded and excluded from the
   verified-warm latency distribution. No failed query is retried by the harness.
4. **Timing:** Monotonic high-resolution wall-clock intervals. DoT explicitly times
   TCP establishment and TLS negotiation; its socket then becomes nonblocking for
   dnspython's deadline handling. DoH uses pinned httpcore trace events for TCP/TLS.
   Total time includes request serialization/HTTP framing and DNS response parsing;
   final response validation and logging are outside. `query_ms = total_ms - setup_ms`.
   DoH query time includes HTTP/2 initialization and client overhead outside its
   TCP/TLS trace intervals. These are application-observed phases, not packet-level
   estimates of pure propagation or server processing time.
5. **UDP control:** Do53 uses UDP only, setup zero. Truncation is a failure; it is
   never silently converted into TCP. Timeouts are separated from other transport
   errors and DNS errors. The fixed workload expects NOERROR with at least one answer;
   NXDOMAIN, SERVFAIL, and empty answers are classified as DNS failures.
6. **Workload:** Twenty fixed public domains, EDNS payload 1232 bytes, recursion
   requested, no DNSSEC DO bit, no ECS insertion, no random NXDOMAIN generation.
   Each resolver/protocol is primed against the list (logged separately, stops
   after a priming failure). This favors cache hits but cannot guarantee residency.
   Answer counts, RCODE, response size, and minimum answer TTL are logged.
7. **Randomization:** Every resolver/protocol/block job is shuffled. Within each job,
   cold-first versus warm-first is randomized. Cold and warm measured queries have
   identical names and order; domain lists are also shared across resolvers/protocols
   for the corresponding block number. Query IDs remain library-generated; the
   scheduling seed does not control DNS IDs, network events, or server behavior.
8. **Pacing and deadlines:** Sequential requests, no multiplexing load test, 50 ms
   pause between queries. HTTPX uses per-I/O timeouts; DoT has separate connect,
   handshake, and DNS-query timeouts. The configured timeout is not one global
   whole-resolution deadline and should not be interpreted as an identical total
   cutoff across protocols. Failure elapsed time remains available separately.

## Outputs and statistical definitions

Every run contains `metadata.json`, `schedule.json`, `source/*.py`, and an immediately
flushed `observations.jsonl`. Metadata includes UTC times, platform, package versions,
seed, full endpoint/workload settings, completion status, and a source SHA-256.
The log distinguishes `cache_prime`, `warmup`, and `measurement`; only the last is
used for the main latency and reliability summaries. Source snapshots preserve the
exact measurement implementation even if the working code later changes.

The audit checks coverage, log sequence, schedule/domain agreement, source hash,
phase timing arithmetic, cold/warm connection invariants, and unexpected TLS
resumption. It does not prove cache residency, absence of transparent network
interception, or correctness of labels supplied by the operator.

```sh
.venv/bin/python -m dnsbench analyze data/wifi-2026-09-30 \
  data/emulated-full/broadband data/emulated-full/4g \
  data/emulated-full/lossy data/emulated-full/high-latency \
  --output results/combined
```

Supply only actual run directories, never pilot or preflight files. Add a cellular
run once collected. Duplicate run IDs and incompatible designs sharing a condition
label are rejected. Multiple compatible runs can be pooled descriptively, but the
current bootstrap samples blocks rather than nesting by run; analyze time windows
separately or extend to a hierarchical model for claims about multiple sessions.

| File | Meaning |
|---|---|
| `observations.csv` | Flat export of all phases, including failures |
| `summary.csv` | Per-configuration mean, p50/p95/p99, sample variance, IQR, phase means, timeout/failure rates |
| `paired-blocks.csv` | Matched successful cold/warm differences, averaged within each connection block |
| `amortization.csv` | Equal-weight mean block effect and percentile block-bootstrap 95% CI (5,000 draws) |
| `comparisons.csv` | Two-sided Mann–Whitney U on block effects, Holm adjustment over the exported comparison family |
| `breakeven.csv` | Explicit amortization model, including absent finite crossover |
| `regressions.csv` | Separate exploratory per-resolver fits or an insufficient-data status |
| `batch-curves.csv` | Observed cumulative warm-session time including the initial query/handshake |
| `provenance.json` | Raw-data hashes, analysis-code hash, package versions and analysis RNG seed |
| `quality.json` | Integrity audit, protocol versions, errors, network-unreachable counts, and large timing gaps |
| `analysis-source.py` | Exact analysis source used to generate the report |
| `report.md`, `*.png` | Readable results and figures |

For each domain-matched successful pair, effect is `cold_total - warm_total`.
Average these within a block, then average the block means equally. Percentage
reduction is `100 × (mean_cold - mean_warm) / mean_cold` using the same paired
block means. Missing/failed pairs are excluded from latency contrasts but remain
in reliability denominators. `failure_rate` excludes timeouts;
`unsuccessful_rate = timeout_rate + failure_rate`. Both denominators include all
measured attempts, including reconnections in the intended warm condition.

Thirty five-query blocks offer more replication than one 150-query connection, but
they are not fully independent draws from all possible network conditions. Paired
success conditioning can bias apparent speed if the slowest requests fail. Read
the reliability table alongside every speed claim. Tail quantiles at 150 trials
are descriptive. A Mann–Whitney test detects distributional differences under its
assumptions; it is not automatically a test of medians or a causal infrastructure test.

The setup model is `T(N)/N ≈ S/N + W`, with mean cold setup `S` and successful
verified-warm latency `W`. The 5% overhead count is `ceil(S / (0.05 W))`.
Against mean UDP latency `U`, `ceil(S/(U-W))` estimates the first matching batch
size only if `U > W`. Otherwise there is no finite crossover under this model.
Model values may extrapolate beyond the observed batch size and do not include
retry costs, failures, idle expiry, session resumption, or changing server load.
The observed batch curves use the real warmup followed by measured queries, stop
at failure/reconnection, and include the initial handshake. They are not a second
domain-matched cold/warm estimator.

Regression uses condition-level mean effects against each of observed Do53 latency,
configured added RTT, and configured downlink loss separately, requiring at least
three conditions and three distinct predictor values. Do53 latency is a proxy for
network plus resolver response time, **not** measured pure RTT. Profiles jointly
vary several factors; these fits remain exploratory and confounded. Wi-Fi alone
cannot answer whether the relationship generalizes across network conditions.

## Endpoint and API references

The endpoint configurations were checked against primary documentation and then
probed live on 2026-09-30. Provider policies and support may change; rerun preflight.

- [Cloudflare public endpoints](https://developers.cloudflare.com/1.1.1.1/infrastructure/network-operators/)
  documents the public IPv4 addresses and encrypted hostnames.
- [Google secure DNS transports](https://developers.google.com/speed/public-dns/docs/secure-transports)
  documents DoT/DoH for Google Public DNS.
- [Quad9 services](https://docs.quad9.net/services/) lists the secure resolver's
  addresses and encrypted endpoints. Its [FAQ](https://docs.quad9.net/FAQs/) explains
  its removal of DoH HTTP/1.1 support; the harness enables HTTP/2.
- [Cisco's encrypted DNS announcement](https://umbrella.cisco.com/blog/enhancing-support-dns-encryption-with-dns-over-https)
  documents core OpenDNS DoH endpoints and DoT availability. Both worked live here.
- [NextDNS resolver implementation](https://github.com/nextdns/nextdns/blob/master/resolver/endpoint/doh.go)
  provides first-party implementation context. Our no-account `/` path and
  `dns.nextdns.io` TLS hostname were validated directly against `45.90.28.0`.
- [HTTPX extensions](https://www.python-httpx.org/advanced/extensions/) documents
  trace hooks, SNI overrides, and SSL/connection metadata.
- [dnspython DNS queries](https://dnspython.readthedocs.io/en/stable/query.html)
  specifies the supplied-socket API and nonblocking requirement.
- [Mininet API](https://mininet.org/api/classmininet_1_1net_1_1Mininet.html)
  describes network namespace hosts and links.
- [tc netem manual](https://man7.org/linux/man-pages/man8/tc-netem.8.html)
  defines delay, random loss, rate, optional impairments, and kernel timing limitations.

The bibliography and research motivation remain in the original proposal in
`readme.md`. No claim of reproducing that paper's results is made by this code.
