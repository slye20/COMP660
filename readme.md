# COMP631 DNS connection-reuse experiment

The proposal below is preserved. The implemented project is documented in
[docs/RUNBOOK.md](docs/RUNBOOK.md), including installation, measurement commands,
statistical definitions, and the Linux Mininet testbed.

- **Code:** `dnsbench/` — Do53, DoT, HTTP/2-capable DoH, randomized cold/warm trials,
  timing/reuse instrumentation, data audit, statistics, and figures.
- **Project progress report:** [docs/PROJECT_REPORT.md](docs/PROJECT_REPORT.md) — findings,
  completed work, limitations, and remaining experiments.
- **Real collected data:** [data/README.md](data/README.md).
- **Wi-Fi results:** [results/README.md](results/README.md), with the interrupted run
  and its separate repeat reported independently.
- **One-command collection:** `.venv/bin/python scripts/collect_anchor.py --network wifi`.
- **Tests:** `.venv/bin/python -m pytest -q`.

The Wi-Fi anchor is collected on this Mac. The four emulated conditions and the
cellular anchor require a Linux host and an actual tethered cellular connection,
respectively; they are not represented by synthetic results. Details and limitations
are explicit in the runbook and results.

---

University of North Carolina
at Chapel Hill


COMP631
Networked & Distributed Systems

Project Proposal
Topic: Characterizing DoT/DoH Connection-Reuse Amortization Across Resolvers and Network Conditions

By
Jaymeson Koh 731064003
Samuel Lim 731063769

Scope of Project
Hounsel et al. (2020) compared Do53, DoT, and DoH across multiple public DNS resolvers, including Google, Cloudflare, and Quad9, from five geographic vantage points, and found that connection and session reuse largely closes the performance gap between encrypted and unencrypted DNS. In their study, connection reuse was one component of a broader evaluation of DNS and web performance, and resolver differences were entangled with vantage-point differences rather than measured under a controlled, single-variable comparison.
This project treats connection-reuse amortization as the primary phenomenon under study, and expands it into a two-dimensional question:
How does the magnitude of the connection-reuse amortization effect for DoT and DoH vary jointly across resolver infrastructure and network condition, and is there a general relationship between baseline network quality and the size of that benefit that holds consistently across resolvers, or does resolver-specific infrastructure change where that relationship breaks down?
We measure the amortization effect, the reduction in total resolution time from reusing an established connection instead of creating a new one, across five modern public resolvers (Cloudflare, Google, Quad9, NextDNS, and OpenDNS) and a controlled sweep of network conditions (a low-latency broadband baseline, a moderate 4G-like profile, a lossy or congested profile, and a high-latency profile), implemented through network emulation, plus real Wi-Fi and real cellular measurements as ground-truth anchors. Total resolution latency is decomposed into connection setup time and post-connection query response time, and Do53 serves as a connectionless control for isolating resolver-level and network-level effects from protocol-level connection-reuse effects.
The project does not attempt to identify the exact internal cause of any observed difference between resolvers; anycast routing, server implementation, and TLS configuration are plausible contributors but are not individually isolated. The contribution is an empirical characterization: a resolver by network condition matrix of amortization effects, together with an assessment of whether a consistent breakeven relationship exists between network quality and the benefit of connection reuse, or whether that relationship is resolver dependent.
State of the Art
Traditional DNS (Do53) sends queries unencrypted, which motivated DNS-over-TLS (DoT), run over a dedicated TLS connection on port 853 (Hu et al., 2016), and DNS-over-HTTPS (DoH), tunneled inside HTTPS on port 443 (Hoffman and McManus, 2018). Both were designed to close the privacy gap left by plaintext DNS, since any on-path observer can otherwise see and potentially tamper with every domain a user resolves.
Böttger et al. (2019) found that DoH's overhead over plain UDP DNS has only a limited impact on page load times in practice. Hounsel et al. (2020) directly compared Do53, DoT, and DoH across Google, Cloudflare, and Quad9 from five geographic vantage points, randomizing resolver and protocol order, and found that connection and session reuse largely closes the performance gap between encrypted and unencrypted DNS. A related follow-up, Hounsel, Schmitt, Borgolte, and Feamster (2021), further examined when encrypted DNS can match or beat plaintext DNS once connection costs are amortized across repeated queries.
Hounsel et al.'s methodology allows some resolver comparison under a shared vantage point, but connection-reuse behavior itself was not the primary object of study; it was one mechanism folded into a broader evaluation of protocol and resolver effects on web performance, and their network condition emulation was tied to specific vantage points rather than applied as an independent, controlled variable crossed against every resolver. It remains unknown whether the amortization benefit is a stable property of the DoT/DoH protocols themselves, or whether it depends jointly on resolver infrastructure and network quality in ways that only become visible once both are varied systematically and independently. This project addresses that gap by treating resolver and network condition as two independently controlled axes of a single experimental design.
Proposed Methodology
Providers: Five modern public resolvers supporting Do53, DoT, and DoH: Cloudflare (1.1.1.1), Google (8.8.8.8), Quad9 (9.9.9.9), NextDNS, and OpenDNS.
Emulated network conditions: A Mininet testbed using tc netem to implement a small set of controlled, reproducible profiles: a low-latency broadband baseline, a moderate 4G-like profile, a lossy or congested profile, and a high-latency profile. Independently varying RTT, loss, and bandwidth is not possible on any single real network, which is why controlled emulation is necessary to answer the breakeven question at the center of the project.
Network Condition Profiles
Profile
Latency (RTT)
Jitter
Packet Loss
Bandwidth
Corruption*
Duplication*
Broadband
10ms
2ms
0%
100 Mbps
0%
0%
4G-like
53.3ms
1ms
0.5%
22.1 Mbps
0.01%
0.01%
Lossy/Congested
53.3ms
1ms
1.5%
22.1 Mbps
0.05%
0.1%
High-Latency
150ms
8ms
2.1%
1 Mbps
0.02%
0.02%

*Corruption and duplication are proposed as an optional methodological enhancement pending scope feedback.
Why These Values Were Chosen
4G-like, Lossy/Congested, and High-latency are taken directly from Hounsel et al. (2020). Rather than inventing new emulated conditions, we deliberately reuse the exact netem parameters from the paper this project extends. Hounsel et al. (2020) emulated a 4G network with 53.3ms of added latency, 1ms of jitter, 0.5% packet loss, and asymmetric bandwidth shaping to 22.1 Mb/s downlink and 7.44 Mb/s uplink, values they grounded in an OpenSignal report on real-world mobile network performance rather than arbitrary estimates. Their "lossy 4G" condition uses identical latency and jitter but raises loss to 1.5%, isolating the effect of loss alone from the effect of latency. Their "3G" condition (which we label High-latency, since our study is not cellular-generation-specific) adds 150ms of latency, 8ms of jitter, 2.1% loss, and a much tighter 1 Mb/s symmetric bandwidth cap. For this project, we will be only focusing on shaping the downlink bandwidth using tc and netem.
Reusing these exact values, rather than approximations of our own, is a deliberate methodological choice: it means any difference we observe between our multi-resolver results and Hounsel et al.'s (2020) original single-vantage-point findings can be attributed to the variables we changed, resolver identity and the cross-resolver design, rather than to us having quietly tested under different network conditions than they did. It also means our results are directly citable against theirs in the final report, since a reader can compare our 4G-condition amortization numbers against their published 4G query response time figures under the same emulated network.
Broadband is our own addition, representing a condition Hounsel et al. did not test. Their study focused specifically on cellular degradation (4G, lossy 4G, 3G) and did not include a low-latency wired baseline. We add it because our research question is about the full range of network quality, not just the degraded end. Ten milliseconds of latency with minimal jitter and zero loss is representative of a client on a fiber connection or a strong home Wi-Fi network reaching a nearby ISP peering point. This is consistent with the FCC's Measuring Broadband America program, which has consistently reported idle latency in the 7 to 14 millisecond range for fiber ISPs and 12 to 24 milliseconds for cable ISPs across its most recent measurement cycles (FCC, 2024), with fiber and cable latencies both well below the 23 to 34 millisecond range typically reported for DSL. This profile also functions as our sanity-check baseline: if amortization behaves unexpectedly even under near-ideal network conditions, that would suggest an issue with our harness rather than a genuine finding about resolver behavior.
Bandwidth is included in all four profiles for completeness and to match Hounsel et al.'s (2020) original methodology, but is expected to be the least influential variable specifically for DNS traffic, since DNS payloads are small (typically under 512 bytes) and are unlikely to be constrained even by the 1 Mb/s cap in the High-latency profile.
Achieved with, for example, the 4G-like profile:
tc qdisc add dev eth0 root netem delay 53.3ms 1ms loss 0.5% rate 22.1mbit
Real network anchors: Real Wi-Fi and real tethered cellular measurements for the same resolver set, serving both as standalone data points and as a validity check on whether the emulated profiles produce results broadly consistent with real conditions.
Tooling: A Python measurement harness using dnspython for Do53 and DoT and httpx for DoH, timing connection setup and query response as separate phases, applied identically across every resolver and network condition combination.
Connection state: Cold (a new connection per query) versus warm (a persistent connection reused across a batch of queries) for DoT and DoH, measured under every resolver and network condition.
Do53 as control: Since Do53 has no connection to amortize, it provides a per-resolver, per-condition baseline for how much of any observed effect is due to raw resolver or network performance rather than protocol-level connection reuse.
Trials and statistics: 100 to 150 trials per configuration (3 protocols, 5 resolvers, up to 6 network conditions, cold and warm for DoT and DoH), sufficient for full latency distributions given the scale of the design.
Optional Methodological Enhancement: Corruption and Duplication
As a possible extension, we could additionally emulate two further netem parameters: corruption (random bit-flips, simulating physical-layer noise) and duplication (resent packets, simulating aggressive lower-layer retransmission). Each represents a distinct failure mode from plain packet loss, and each could plausibly affect DoT/DoH differently than Do53, since TCP and TLS carry their own integrity checking and sequencing logic that a stateless UDP exchange does not. We flag this as an enhancement for feedback on whether it fits within the project's intended depth, rather than committing it to the core scope, since it would add a second experimental dimension on top of the resolver by network condition matrix already proposed.
Metrics
Primary metrics (per query):
Connection setup time, zero for Do53, the full TLS handshake for a cold DoT or DoH connection, near zero for warm.
Query response time, measured separately from connection setup.
Total resolution time, the sum of the two.
Derived metric:
Amortization effect, the cold-to-warm reduction in total resolution time, computed for every resolver and network condition combination, producing a full matrix rather than a single number.
Characterisation metrics:
An empirical relationship between baseline network quality (RTT and loss from the emulated profiles) and the size of the amortization effect, fit separately per resolver, testing whether a consistent breakeven pattern holds across resolvers or is resolver-specific. This is the metric that directly answers the project's open question.
Distributional metrics:
p50, p95, and p99 of total resolution time, per protocol, per resolver, per network condition, per connection state.
Variance and interquartile range of total resolution time, as a measure of consistency within each configuration.
Reliability metrics, secondary:
Timeout rate and failure rate, per protocol, per resolver, per network condition, logged separately since they indicate different failure modes.
Statistical test:
Mann-Whitney U, comparing amortization effects across resolvers within a fixed network condition, and across network conditions within a fixed resolver.
Expected Timeline (2-week milestones)
Weeks 6–7 (Sept 21–Oct 4):
Project Proposal Presentation. Build the core harness (Do53, DoT, DoH timing, with connection setup and query response measured as separate phases) and validate it against Cloudflare on Wi-Fi, with connection setup and query response measured as separate phases. Confirm the timing instrumentation is accurate before adding a second provider and more.
Weeks 8–9 (Oct 5–18):
Preliminary results due for the mid-project presentation. Extend the harness to all five resolvers and complete real Wi-Fi measurements for at least three of them, enough to show an initial cross-resolver amortization comparison. Build and validate the Mininet/tc netem testbed in parallel, and run an initial small-scale sweep (one or two network profiles) against one resolver as a proof of concept.
Weeks 10–11 (Oct 19–Nov 1):
Run the full emulated network condition sweep, all profiles, across all five resolvers, for Do53, DoT, and DoH, cold and warm.
Weeks 12–13 (Nov 2–15):
Complete real cellular anchor measurements across all five resolvers, fill in any remaining Wi-Fi measurements, and cross-check emulated results against the real Wi-Fi and cellular anchors for consistency.
Weeks 14–15 (Nov 16–29):
Build the network-quality-versus-amortization relationship per resolver, run statistical comparisons across resolvers and conditions, compile reliability results, and begin drafting the report.
Week 16 (Nov 30–Dec 3):
Finalize the report, polish all figures, including the resolver by network condition amortization matrix, and prepare the final presentation.

References
Böttger, T., Cuadrado, F., Antichi, G., Fernandes, E. L., Tyson, G., Castro, I., and Uhlig, S. (2019). An Empirical Study of the Cost of DNS-over-HTTPS. In Proceedings of the 2019 ACM Internet Measurement Conference (IMC '19), pp. 15 to 21. https://doi.org/10.1145/3355369.3355575

Federal Communications Commission. (2024). Measuring Fixed Broadband: Thirteenth Report. Office of Engineering and Technology. https://www.fcc.gov/reports-research/reports/measuring-broadband-america/measuring-fixed-broadband-thirteenth-report

Hoffman, P. and McManus, P. (2018). DNS Queries over HTTPS (DoH). RFC 8484, IETF. https://doi.org/10.17487/RFC8484

Hounsel, A., Borgolte, K., Schmitt, P., Holland, J., and Feamster, N. (2020). Comparing the Effects of DNS, DoT, and DoH on Web Performance. In Proceedings of The Web Conference 2020 (WWW '20). https://doi.org/10.1145/3366423.3380139

Hounsel, A., Schmitt, P., Borgolte, K., & Feamster, N. (2021, March). Can encrypted DNS be fast?. In International Conference on Passive and Active Network Measurement (pp. 444-459). Cham: Springer International Publishing. https://arxiv.org/abs/2007.06812

Hu, Z., Zhu, L., Heidemann, J., Mankin, A., Wessels, D., and Hoffman, P. (2016). Specification for DNS over Transport Layer Security (TLS). RFC 7858, IETF. https://doi.org/10.17487/RFC7858
