# Collected data inventory

Only observations from actual DNS requests are included. No simulated observations
are mixed with measured data.

| Path | Role | Include in final analysis? |
|---|---|---|
| `wifi-repeat-2026-09-30/` | Separate Wi-Fi repeat with idle sleep inhibited: 150 trials × 25 configurations | Yes, analyze separately |
| `wifi-2026-09-30/` | Corrected-instrumentation run, 150 trials × 25 configurations; substantial network interruption | Yes, retain as interrupted-network observations; analyze separately |
| `pilot-wifi-2026-09-30/` | Development pilot: TLS sockets had a blocking timeout; DoH parsing boundary differed | No |
| `preflight-live.json` | Initial two-query endpoint/reuse checks per resolver/protocol | No |
| `preflight-validated.json` | Checks after correcting socket mode and timing boundaries | No |
| `preflight-after-outage.json` | Connectivity rechecked before the separate repeat | No |
| `preflight-sandbox.json` | Diagnostic permission-denied attempts inside the tool sandbox | No |

Wi-Fi was identified by the default route using `en0` and macOS mapping `en0` to
Wi-Fi. SSID, MAC address, local/public client IP, and gateway are not saved in the
measurement metadata. The upstream connection type, VPN state, and competing
traffic were not independently established. Use the metadata's UTC timestamps,
rather than directory names, for exact run times.

Each run saves its raw observations, randomized schedule, input settings, package
versions, source snapshot, and source hash. Pilot observations are preserved for
traceability and explicitly excluded from the delivered report.

The interrupted run has 294 network-unreachable observations across all phases.
The measured attempts comprise 3,387 successes, 329 other errors, and 34 timeouts.
It ran from 14:53:03 to 17:10:13 UTC, including large gaps. These failures cannot
be assigned to individual resolver infrastructure. No observations were removed
or relabeled to make this run look like a stable baseline.

See `wifi-repeat-2026-09-30-audit.json` for the separate repeat's passing audit:
3,750 measured attempts, 3,708 successes, 40 other errors, 2 timeouts, no detected
network-unreachable observations, and no large timestamp gaps. The repeat ran
from 17:29:51 to 17:38:29 UTC with seed 632 and idle-sleep inhibition.

Pending data: four Linux Mininet profiles and the real cellular anchor. See
`docs/RUNBOOK.md` for the implemented collection commands. Neither a label nor a
synthetic delay on application calls substitutes for those measurements.
