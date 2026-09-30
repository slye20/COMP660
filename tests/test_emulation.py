import json

from scripts.mininet_sweep import netem_command, ping_stats


def test_profiles_shape_downlink_once_and_exclude_optional_impairments():
    profiles = json.loads(open("config/profiles.json").read())
    cmd = netem_command(profiles["4g"])
    assert cmd[cmd.index("dev") + 1] == "dngw-eth0"
    assert cmd[cmd.index("delay") + 1] == "53.3ms"
    assert cmd[cmd.index("rate") + 1] == "22.1mbit"
    assert "corrupt" not in cmd and "duplicate" not in cmd
    assert cmd.count("delay") == 1


def test_optional_impairments_are_explicit():
    profiles = json.loads(open("config/profiles.json").read())
    cmd = netem_command(profiles["lossy"], True)
    assert cmd[cmd.index("corrupt") + 1] == "0.05%"
    assert cmd[cmd.index("duplicate") + 1] == "0.1%"


def test_ping_validation_parser():
    result = {"stdout": "30 packets transmitted, 29 received, 3.33333% packet loss\nrtt min/avg/max/mdev = 52.5/53.4/55.0/0.98 ms"}
    assert ping_stats(result) == {"mean_rtt_ms": 53.4, "loss_pct": 3.33333}
    assert ping_stats({"stdout": "100% packet loss"})["mean_rtt_ms"] is None
