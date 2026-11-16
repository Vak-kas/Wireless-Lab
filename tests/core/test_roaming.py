# SPDX-License-Identifier: GPL-3.0-or-later
import json

from fastapi.testclient import TestClient

from wls.core.roaming import LinkEvent, LinkObservation, LinkTracker
from wls.probes.wifi_link import LinkReading, WifiBackend
from wls.providers.sim import SimProvider, sim_wifi_nic
from wls.web.app import create_app
from wls.web.watch import WifiWatch

A, B, C = "aa:aa:aa:aa:aa:01", "aa:aa:aa:aa:aa:02", "cc:cc:cc:cc:cc:03"


def on(t, bssid=A, ssid="home", channel=36, rssi=-50.0):
    return LinkObservation(t, True, ssid, bssid, channel, rssi)


def off(t):
    return LinkObservation(t, False)


def feed(tracker, *observations):
    events = []
    for obs in observations:
        events += tracker.observe(obs)
    return events


# --- tracker ----------------------------------------------------------------------


def test_starting_point_and_steady_connection_produce_no_events():
    assert feed(LinkTracker(), on(1), on(2), on(3, rssi=-55.0)) == []
    assert feed(LinkTracker(), off(1), off(2)) == []


def test_moving_to_another_access_point_of_the_same_network_is_a_roam():
    events = feed(LinkTracker(), on(1, A, channel=36, rssi=-72.0), on(2, B, channel=149, rssi=-48.0))
    assert events == [
        LinkEvent(2, "roamed", "home", B, 149, -48.0, "home", A, 36, -72.0),
    ]


def test_switching_to_a_different_network_is_not_called_a_roam():
    (event,) = feed(LinkTracker(), on(1, A, "home"), on(2, C, "cafe"))
    assert event.kind == "network_changed"
    assert (event.from_ssid, event.ssid) == ("home", "cafe")


def test_single_missed_reading_is_not_a_disconnect():
    assert feed(LinkTracker(), on(1), off(2), on(3)) == []


def test_disconnect_and_reconnect_are_recorded():
    events = feed(LinkTracker(), on(1, A, rssi=-80.0), off(2), off(3), off(4), on(5, B))
    assert [e.kind for e in events] == ["disconnected", "connected"]
    assert (events[0].t, events[0].from_bssid, events[0].from_rssi_dbm) == (3, A, -80.0)
    assert (events[1].t, events[1].bssid) == (5, B)


def test_connecting_from_a_disconnected_start_is_recorded():
    (event,) = feed(LinkTracker(), off(1), on(2))
    assert event.kind == "connected" and event.bssid == A


def test_hidden_identity_never_fakes_a_roam():
    hidden = LinkObservation(2, True, None, None, 36, -50.0)
    tracker = LinkTracker()
    assert feed(tracker, on(1, A), hidden, on(3, A)) == []
    # and the last known access point is remembered across the gap
    (event,) = feed(tracker, hidden, on(5, B))
    assert (event.kind, event.from_bssid, event.bssid) == ("roamed", A, B)


# --- watch --------------------------------------------------------------------------


class FakeLink:
    def __init__(self):
        self.reading = LinkReading(-50.0, channel=36)
        self.identity = ("home", A)
        self.asked = 0

    def read(self):
        return self.reading

    def who(self):
        self.asked += 1
        return self.identity


async def test_watch_logs_a_roam_and_keeps_it_across_restarts(tmp_path):
    link, log = FakeLink(), tmp_path / "wifi-events.jsonl"
    watch = WifiWatch(link.read, link.who, log)
    assert await watch.step(100.0) == []

    link.reading, link.identity = LinkReading(-45.0, channel=149), ("home", B)
    (event,) = await watch.step(101.0)
    assert (event.kind, event.from_bssid, event.bssid, event.channel) == ("roamed", A, B, 149)

    assert json.loads(log.read_text().splitlines()[0])["kind"] == "roamed"
    reloaded = WifiWatch(link.read, link.who, log).snapshot()
    assert [e["kind"] for e in reloaded["events"]] == ["roamed"]


async def test_watch_asks_for_identity_only_when_something_suggests_a_change(tmp_path):
    link = FakeLink()
    watch = WifiWatch(link.read, link.who, tmp_path / "log.jsonl")
    await watch.step(100.0)
    await watch.step(101.0)
    await watch.step(102.0)
    assert link.asked == 1  # steady signal on the same channel: no need to ask again

    link.reading = LinkReading(-49.0, channel=40)  # channel changed
    await watch.step(103.0)
    assert link.asked == 2
    link.reading = LinkReading(-70.0, channel=40)  # signal jumped
    await watch.step(104.0)
    assert link.asked == 3
    await watch.step(120.0)  # safety net after a while
    assert link.asked == 4


async def test_watch_records_disconnect_without_asking_for_identity(tmp_path):
    link = FakeLink()
    watch = WifiWatch(link.read, link.who, tmp_path / "log.jsonl")
    await watch.step(100.0)
    link.reading = None
    await watch.step(101.0)
    (event,) = await watch.step(102.0)
    assert event.kind == "disconnected" and event.from_bssid == A
    assert link.asked == 1


async def test_damaged_log_lines_are_skipped(tmp_path):
    log = tmp_path / "log.jsonl"
    log.write_text('{"t": 1, "kind": "connected", "bssid": "x"}\nnot json\n{"unknown": 1}\n')
    link = FakeLink()
    assert [e["kind"] for e in WifiWatch(link.read, link.who, log).snapshot()["events"]] == ["connected"]


# --- API ------------------------------------------------------------------------------


def test_events_api_reports_watching_and_events(tmp_path):
    link = FakeLink()
    provider = SimProvider([sim_wifi_nic("wifi:test0")])
    backend = WifiBackend(
        provider, lambda interface: link.read, lambda interface: (lambda: []), "wifi:",
        identity=lambda interface, fresh=False: link.who(),
    )  # fmt: skip
    (tmp_path / "wifi-events.jsonl").write_text('{"t": 5, "kind": "roamed", "bssid": "b"}\n')
    with TestClient(create_app(tmp_path, lambda: [], wifi=backend, bluetooth=None)) as client:
        answer = client.get("/api/wifi/events").json()
        assert answer["watching"] is True
        assert answer["events"][0]["kind"] == "roamed"


def test_events_api_without_wifi(tmp_path):
    with TestClient(create_app(tmp_path, lambda: [], wifi=None, bluetooth=None)) as client:
        assert client.get("/api/wifi/events").json() == {
            "watching": False, "watching_since": None, "identity_known": False, "events": [],
        }  # fmt: skip
