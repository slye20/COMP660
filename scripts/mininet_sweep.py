#!/usr/bin/env python3
"""Linux-only, isolated client veth, downlink netem, scoped NAT rules.

Use a dedicated Linux VM. Never attach a qdisc to a physical interface.
--dry-run prints the complete shaping plan without requiring Linux/root.
"""

import argparse
from datetime import datetime, timezone
import ipaddress
import json
import os
from pathlib import Path
import platform
import random
import re
import shutil
import signal
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parent.parent
SUBNET = "10.231.63.0/24"
GATEWAY = "10.231.63.1"
CLIENT = "10.231.63.2"
INTERFACE = "dngw-eth0"


def netem_command(profile, impairments=False):
    """One traversal: downlink delay increases end-to-end RTT by this value."""
    cmd = ["tc", "qdisc", "replace", "dev", INTERFACE, "root", "netem", "limit", "10000",
           "delay", f"{profile['added_rtt_ms']:g}ms", f"{profile['downlink_jitter_ms']:g}ms",
           "loss", "random", f"{profile['downlink_loss_pct']:g}%",
           "rate", f"{profile['downlink_mbit']:g}mbit"]
    if impairments:
        cmd.extend(["corrupt", f"{profile['optional_corrupt_pct']:g}%",
                    "duplicate", f"{profile['optional_duplicate_pct']:g}%"])
    return cmd


def execute(command, node=None, check=True, timeout=60):
    if node:
        proc = node.popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
        except BaseException:
            proc.kill()
            proc.wait()
            raise
        result = subprocess.CompletedProcess(command, proc.returncode, stdout, stderr)
    else:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    if check and result.returncode:
        raise RuntimeError(f"Command failed: {command!r}\n{result.stdout}\n{result.stderr}")
    return {"command": command, "returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr}


def ping_stats(result):
    text = result["stdout"]
    match = re.search(r"= ([\d.]+)/([\d.]+)/([\d.]+)/([\d.]+) ms", text)
    loss = re.search(r"([\d.]+)% packet loss", text)
    return {"mean_rtt_ms": float(match[2]) if match else None,
            "loss_pct": float(loss[1]) if loss else None}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profiles-file", default=str(ROOT / "config/profiles.json"))
    parser.add_argument("--profiles", nargs="+")
    parser.add_argument("--output", default="data/emulated")
    parser.add_argument("--python", default=str(ROOT / ".venv/bin/python"))
    parser.add_argument("--trials", type=int, default=150)
    parser.add_argument("--batch-size", type=int, default=5)
    parser.add_argument("--seed", type=int, default=631)
    parser.add_argument("--timeout", type=float, default=5)
    parser.add_argument("--resolvers", nargs="+")
    parser.add_argument("--optional-impairments", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    profiles = json.loads(Path(args.profiles_file).read_text())
    names = args.profiles or list(profiles)
    if set(names) - profiles.keys():
        parser.error("Unknown profile")
    if args.trials < 1 or args.batch_size < 1 or args.timeout <= 0:
        parser.error("trials, batch-size and timeout must be positive")
    random.Random(args.seed).shuffle(names)
    commands = {n: netem_command(profiles[n], args.optional_impairments) for n in names}
    if args.dry_run:
        print(json.dumps({"order": names, "commands": commands, "direction": "gateway veth egress toward client only",
                          "latency_semantics": "added RTT, not total path RTT; uplink is unshaped"}, indent=2))
        return
    if platform.system() != "Linux" or os.geteuid() != 0:
        parser.error("Execution requires root on Linux; use --dry-run to inspect on macOS")
    for tool in ("ip", "tc", "iptables", "ping", "iperf3", "ethtool"):
        if not shutil.which(tool):
            parser.error(f"Missing {tool}; install dependencies in docs/RUNBOOK.md")
    if not Path(args.python).is_file():
        parser.error("--python must point to the installed measurement virtualenv")
    # Fail before mutations if our private subnet conflicts with any real route.
    routes = json.loads(execute(["ip", "-j", "route", "show"])['stdout'])
    for route in routes:
        dest = route.get("dst", "default")
        if dest != "default" and ipaddress.ip_network(dest, strict=False).overlaps(ipaddress.ip_network(SUBNET)):
            parser.error(f"Subnet {SUBNET} conflicts with existing route {dest}")
    links = json.loads(execute(["ip", "-j", "link", "show"])['stdout'])
    if any(r["ifname"] in (INTERFACE, "dnclient-eth0") for r in links):
        parser.error("Test interfaces already exist; resolve the previous run before retrying")
    from mininet.net import Mininet
    from mininet.node import Host

    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    old_forward = Path("/proc/sys/net/ipv4/ip_forward").read_text().strip()
    tag = f"dnsbench-{uuid.uuid4().hex[:12]}"
    rules = [
        ["iptables", "-I", "FORWARD", "-i", INTERFACE, "-s", SUBNET, "-m", "comment", "--comment", tag, "-j", "ACCEPT"],
        ["iptables", "-I", "FORWARD", "-o", INTERFACE, "-d", SUBNET, "-m", "conntrack", "--ctstate", "ESTABLISHED,RELATED", "-m", "comment", "--comment", tag, "-j", "ACCEPT"],
        ["iptables", "-t", "nat", "-A", "POSTROUTING", "-s", SUBNET, "!", "-d", SUBNET, "-m", "comment", "--comment", tag, "-j", "MASQUERADE"],
    ]
    installed = []
    cleanup_errors = []
    net = Mininet(controller=None, build=False, ipBase=SUBNET)
    process = None

    def interrupted(signum, frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, interrupted)
    try:
        gateway = net.addHost("dngw", cls=Host, inNamespace=False, ip=f"{GATEWAY}/24")
        client = net.addHost("dnclient", ip=f"{CLIENT}/24", defaultRoute=f"via {GATEWAY}")
        net.addLink(gateway, client)
        net.start()
        # Avoid offload aggregating packets before netem, especially when testing
        # corruption or loss. Record both requested and effective offload state.
        offloads = []
        for node, interface in ((gateway, INTERFACE), (client, "dnclient-eth0")):
            offloads.append(execute(["ethtool", "-K", interface, "tso", "off", "gso", "off", "gro", "off"], node))
            offloads.append(execute(["ethtool", "-k", interface], node))
        for rule in rules:
            execute(rule)
            installed.append(rule)
        Path("/proc/sys/net/ipv4/ip_forward").write_text("1\n")
        baseline = execute(["ping", "-n", "-c", "20", "-i", "0.05", "-W", "2", GATEWAY], client, check=False)
        baseline_stats = ping_stats(baseline)
        if baseline_stats["mean_rtt_ms"] is None:
            raise RuntimeError("Client cannot reach gateway before shaping")
        for name in names:
            label = name + ("-extra" if args.optional_impairments else "")
            execute(commands[name], gateway)
            validation = execute(["ping", "-n", "-c", "30", "-i", "0.05", "-W", "2", GATEWAY], client, check=False)
            observed = ping_stats(validation)
            measured_added = (observed["mean_rtt_ms"] - baseline_stats["mean_rtt_ms"]
                              if observed["mean_rtt_ms"] is not None else None)
            tolerance = max(5, 4 * profiles[name]["downlink_jitter_ms"])
            valid_delay = measured_added is not None and abs(measured_added - profiles[name]["added_rtt_ms"]) <= tolerance
            # Reverse iperf is local gateway -> client, not traffic to a public server.
            server = gateway.popen(["iperf3", "-s", "-1", "-B", GATEWAY], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                import time
                time.sleep(.3)
                throughput = execute(["iperf3", "-c", GATEWAY, "-R", "-t", "3", "-J"], client, check=False)
            finally:
                if server.poll() is None:
                    server.terminate()
                server.wait(timeout=5)
            meta = {"created_utc": datetime.now(timezone.utc).isoformat(), "profile": label,
                    "parameters": profiles[name], "optional_impairments": args.optional_impairments,
                    "direction": "downlink only", "delay_semantics": "added RTT above real path",
                    "qdisc_command": commands[name], "qdisc_before": execute(["tc", "-s", "-j", "qdisc", "show", "dev", INTERFACE], gateway),
                    "baseline_ping": baseline, "shaped_ping": validation, "measured_added_rtt_ms": measured_added,
                    "delay_validation_passed": valid_delay, "local_reverse_iperf": throughput,
                    "offload_state": offloads, "kernel": platform.release(),
                    "netem_rng": "kernel random; scheduling seed does not seed netem"}
            meta_path = output / f"{label}-emulation.json"
            meta_path.write_text(json.dumps(meta, indent=2) + "\n")
            if not valid_delay:
                raise RuntimeError(f"Delay validation failed for {name}; see {meta_path}")
            command = [str(Path(args.python).absolute()), "-m", "dnsbench", "run", "--network", "emulated",
                       "--profile", label, "--emulation-metadata", str(meta_path),
                       "--trials", str(args.trials), "--batch-size", str(args.batch_size),
                       "--seed", str(args.seed), "--timeout", str(args.timeout), "--output", str(output / label),
                       "--note", "Mininet isolated client; single downlink netem; real WAN delay remains"]
            if args.resolvers:
                command.extend(["--resolvers", *args.resolvers])
            with (output / f"{label}.log").open("w") as log:
                process = client.popen(command, cwd=str(ROOT), stdout=log, stderr=subprocess.STDOUT)
                status = process.wait()
                process = None
            meta["qdisc_after"] = execute(["tc", "-s", "-j", "qdisc", "show", "dev", INTERFACE], gateway)
            meta_path.write_text(json.dumps(meta, indent=2) + "\n")
            if status:
                raise RuntimeError(f"Harness failed for {label}; inspect its log")
            subprocess.run([args.python, "-m", "dnsbench", "audit", str(output / label),
                            "--output", str(output / f"{label}-audit.json")], cwd=ROOT, check=True)
            print(f"Finished {label}", flush=True)
    finally:
        if process is not None and process.poll() is None:
            process.send_signal(signal.SIGINT)
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        for rule in reversed(installed):
            inverse = ["-D" if token in ("-I", "-A") else token for token in rule]
            try:
                execute(inverse)
            except Exception as exc:
                cleanup_errors.append(str(exc))
        try:
            Path("/proc/sys/net/ipv4/ip_forward").write_text(old_forward + "\n")
        finally:
            net.stop()
        (output / "cleanup.json").write_text(json.dumps({"errors": cleanup_errors, "restored_ip_forward": old_forward}, indent=2) + "\n")
        if cleanup_errors:
            print("Cleanup errors: " + repr(cleanup_errors), file=sys.stderr)
    run_paths = [str(output / (name + ("-extra" if args.optional_impairments else ""))) for name in names]
    subprocess.run([args.python, "-m", "dnsbench", "analyze", *run_paths,
                    "--output", str(output / "analysis")], cwd=ROOT, check=True)


if __name__ == "__main__":
    main()
