# SPDX-License-Identifier: GPL-3.0-or-later
import shutil

import pytest

from wls.analysis.diagnosis import Verdict, diagnose
from wls.analysis.summary import LatencySummary, MetricSummary
from wls.cli import main
from wls.core.storage import read_run, verify_run
from wls.providers.netinfo import parse_gateway


def lat(avg=None, *, sent=10, lost=0, jitter=1.0):
    if avg is None:
        return LatencySummary(sent, sent, None, None, None, None)
    return LatencySummary(sent, lost, avg, avg, avg, jitter)


def metric(avg, count=10):
    return MetricSummary(count, avg, avg, avg)


GOOD_WIFI = dict(wifi_connected=metric(1.0), wifi_rssi=metric(-45.0), wifi_snr=metric(45.0))
WEAK_WIFI = dict(wifi_connected=metric(1.0), wifi_rssi=metric(-80.0), wifi_snr=metric(12.0))


# --- verdicts ---------------------------------------------------------------------


def test_everything_fine():
    d = diagnose(lat(15), lat(2), **GOOD_WIFI)
    assert d.verdict is Verdict.OK
    assert any("strong" in x for x in d.details)


def test_slow_router_with_weak_wifi_blames_wifi():
    d = diagnose(lat(120, jitter=40), lat(60, jitter=30), **WEAK_WIFI)
    assert d.verdict is Verdict.LOCAL_PROBLEM
    assert "Wi-Fi is a likely cause" in d.headline
    assert any("weak" in x for x in d.details)


def test_slow_router_with_good_wifi_is_local_but_does_not_blame_wifi():
    d = diagnose(lat(120), lat(60), **GOOD_WIFI)
    assert d.verdict is Verdict.LOCAL_PROBLEM
    assert "Wi-Fi is a likely cause" not in d.headline


def test_loss_to_the_router_is_a_local_problem():
    d = diagnose(lat(15, lost=3), lat(2, lost=3), **GOOD_WIFI)
    assert d.verdict is Verdict.LOCAL_PROBLEM
    assert any("30% of packets lost" in x for x in d.details)


def test_fine_router_but_slow_internet_is_beyond_the_router():
    d = diagnose(lat(250), lat(2), **GOOD_WIFI)
    assert d.verdict is Verdict.INTERNET_PROBLEM
    assert "beyond your router" in d.headline


def test_fine_router_but_no_internet_is_beyond_the_router():
    d = diagnose(lat(None), lat(2), **GOOD_WIFI)
    assert d.verdict is Verdict.INTERNET_PROBLEM
    assert any("100% of packets lost" in x for x in d.details)


def test_nothing_answers():
    d = diagnose(lat(None), lat(None), **GOOD_WIFI)
    assert d.verdict is Verdict.NO_CONNECTIVITY


def test_nothing_answers_and_wifi_is_down():
    d = diagnose(lat(None), lat(None), wifi_connected=metric(0.0))
    assert d.verdict is Verdict.WIFI_NOT_CONNECTED


def test_router_that_ignores_ping_does_not_cause_a_false_alarm():
    d = diagnose(lat(15), lat(None), **GOOD_WIFI)
    assert d.verdict is Verdict.OK
    assert any("does not answer ping" in x for x in d.details)


def test_router_ignores_ping_and_internet_is_poor_is_inconclusive_with_good_wifi():
    d = diagnose(lat(300), lat(None), **GOOD_WIFI)
    assert d.verdict is Verdict.INCONCLUSIVE


def test_router_ignores_ping_and_internet_is_poor_with_weak_wifi_suspects_wifi():
    d = diagnose(lat(300), lat(None), **WEAK_WIFI)
    assert d.verdict is Verdict.LOCAL_PROBLEM


def test_wired_connection_without_wifi_data_still_works():
    assert diagnose(lat(15), lat(2)).verdict is Verdict.OK
    assert diagnose(lat(250), lat(2)).verdict is Verdict.INTERNET_PROBLEM


def test_unknown_router_address():
    d = diagnose(lat(15), None, **GOOD_WIFI)
    assert d.verdict is Verdict.OK
    assert any("router address is unknown" in x for x in d.details)


def test_wifi_that_keeps_dropping_is_noted():
    d = diagnose(lat(15, lost=4), lat(2, lost=4), wifi_connected=metric(0.6),
                 wifi_rssi=metric(-50.0))  # fmt: skip
    assert d.verdict is Verdict.LOCAL_PROBLEM
    assert any("only 60% of the time" in x for x in d.details)


def test_nothing_measured():
    assert diagnose(lat(15, sent=0)).verdict is Verdict.INCONCLUSIVE


# --- router address ------------------------------------------------------------------

MACOS_ROUTE = """   route to: default
destination: default
       mask: default
    gateway: 192.168.0.1
  interface: en0
"""
LINUX_ROUTE = "default via 10.0.0.1 dev wlan0 proto dhcp metric 600 \n"
WINDOWS_ROUTE = """
IPv4 Route Table
===========================================================================
Active Routes:
Network Destination        Netmask          Gateway       Interface  Metric
          0.0.0.0          0.0.0.0      192.168.1.1    192.168.1.23     35
===========================================================================
"""
WINDOWS_ONLINK = "          0.0.0.0          0.0.0.0         On-link      10.8.0.2     35\n"


@pytest.mark.parametrize(
    ("output", "system", "expected"),
    [
        (MACOS_ROUTE, "Darwin", "192.168.0.1"),
        (LINUX_ROUTE, "Linux", "10.0.0.1"),
        (WINDOWS_ROUTE, "Windows", "192.168.1.1"),
        (WINDOWS_ONLINK, "Windows", None),
        ("", "Linux", None),
        (LINUX_ROUTE, "Plan9", None),
    ],
)
def test_router_address_is_found_on_every_os(output, system, expected):
    assert parse_gateway(output, system) == expected


# --- command ---------------------------------------------------------------------------


@pytest.mark.skipif(shutil.which("ping") is None, reason="no system ping")
def test_diagnose_command_measures_together_and_prints_a_result(tmp_path, capsys):
    code = main(
        ["diagnose", "--target", "127.0.0.1", "--duration", "0.5", "--interval", "0.2",
         "--out", str(tmp_path)]
    )  # fmt: skip
    out = capsys.readouterr().out
    assert code == 0, out
    assert "result: " in out
    assert "internet " in out

    (run,) = tmp_path.glob("*-diagnose.sqlite")
    assert verify_run(run).intact
    _, samples = read_run(run)
    assert "internet" in {probe for _, probe, _, _ in samples}
