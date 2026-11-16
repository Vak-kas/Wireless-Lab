# SPDX-License-Identifier: GPL-3.0-or-later
import sqlite3

import pytest
from fastapi.testclient import TestClient

from wls.core.interfaces import Event, Sample
from wls.core.runs import list_runs, load_run, run_path
from wls.core.storage import SqliteRecorder
from wls.providers.sim import SimProvider, sim_host, sim_wifi_nic
from wls.web.app import create_app

S = 1_000_000_000


def write_run(path, *, close=True):
    recorder = SqliteRecorder(path)
    recorder.event(Event(10 * S, "state", {"state": "measuring"}))
    recorder.sample(Sample("ping", 11 * S, {"rtt_ms": 10.0, "lost": 0.0}))
    recorder.event(Event(12 * S, "state", {"state": "test_running"}))
    recorder.sample(Sample("ping", 13 * S, {"rtt_ms": 200.0, "lost": 0.0}))
    recorder.event(Event(14 * S, "mark", {"label": "door"}))
    recorder.event(Event(15 * S, "command", {"command": "stop"}))
    recorder.event(Event(16 * S, "state", {"state": "completed"}))
    if close:
        recorder.close()


@pytest.fixture
def runs(tmp_path):
    write_run(tmp_path / "20261116T010000Z-ping.sqlite")
    write_run(tmp_path / "20261116T020000Z-diagnose.sqlite", close=False)
    (tmp_path / "notes.txt").write_text("not a run")
    (tmp_path / "broken.sqlite").write_text("not a database")
    return tmp_path


@pytest.fixture
def client(runs):
    provider = SimProvider([sim_host(), sim_wifi_nic(inject=False)])
    return TestClient(create_app(runs, lambda: [provider]))


# --- run browsing -----------------------------------------------------------------


def test_runs_are_listed_with_kind_and_seal_status(runs):
    listed = {r.name: r for r in list_runs(runs)}
    assert set(listed) == {"20261116T010000Z-ping.sqlite", "20261116T020000Z-diagnose.sqlite"}
    ping = listed["20261116T010000Z-ping.sqlite"]
    assert (ping.kind, ping.sealed, ping.intact) == ("ping", True, True)
    crashed = listed["20261116T020000Z-diagnose.sqlite"]
    assert (crashed.kind, crashed.sealed, crashed.intact) == ("diagnose", False, False)


def test_missing_directory_lists_nothing(tmp_path):
    assert list_runs(tmp_path / "nope") == []


def test_run_is_loaded_as_series_relative_to_its_start(runs):
    detail = load_run(runs / "20261116T010000Z-ping.sqlite")
    assert detail.duration == 6.0
    series = {(s.probe, s.metric): s.points for s in detail.series}
    assert series[("ping", "rtt_ms")] == [(1.0, 10.0), (3.0, 200.0)]
    timeline = [(e.t, e.kind, e.label) for e in detail.events]
    assert timeline == [
        (0.0, "state", "measuring"),
        (2.0, "state", "test_running"),
        (4.0, "mark", "door"),
        (6.0, "state", "completed"),
    ]  # the "command" event is not part of the timeline


@pytest.mark.parametrize(
    "name", ["../secret.sqlite", "/etc/passwd", "notes.txt", "a/b.sqlite", ".hidden.sqlite", ""]
)
def test_only_plain_run_file_names_are_resolved(runs, name):
    assert run_path(runs, name) is None


# --- HTTP ---------------------------------------------------------------------------


def test_page_is_served(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "Wireless Lab" in response.text


def test_api_lists_runs_newest_first(client):
    names = [r["name"] for r in client.get("/api/runs").json()["runs"]]
    assert names == ["20261116T020000Z-diagnose.sqlite", "20261116T010000Z-ping.sqlite"]


def test_api_returns_one_run(client):
    run = client.get("/api/runs/20261116T010000Z-ping.sqlite").json()
    assert run["kind"] == "ping" and run["intact"] is True and run["duration"] == 6.0
    rtt = next(s for s in run["series"] if s["metric"] == "rtt_ms")
    assert rtt["points"] == [[1.0, 10.0], [3.0, 200.0]]
    assert {"t": 4.0, "kind": "mark", "label": "door"} in run["events"]


def test_api_reports_a_modified_run(client, runs):
    db = sqlite3.connect(runs / "20261116T010000Z-ping.sqlite")
    with db:
        db.execute("UPDATE sample SET value = 1.0 WHERE metric = 'rtt_ms'")
    db.close()
    run = client.get("/api/runs/20261116T010000Z-ping.sqlite").json()
    assert (run["sealed"], run["intact"]) == (True, False)


@pytest.mark.parametrize(
    "name", ["nope.sqlite", "notes.txt", "..%2Fsecret.sqlite", "%2E%2E%2F%2E%2E%2Fetc%2Fpasswd"]
)
def test_api_refuses_unknown_or_escaping_names(client, name):
    assert client.get(f"/api/runs/{name}").status_code == 404


def test_api_lists_devices_with_reasons(client):
    devices = {d["id"]: d for d in client.get("/api/devices").json()["devices"]}
    assert set(devices) == {"sim-host", "sim-wlan0"}
    inject = next(c for c in devices["sim-wlan0"]["capabilities"] if c["name"] == "wifi_inject")
    assert inject["supported"] is False and "injection" in inject["reason"]
