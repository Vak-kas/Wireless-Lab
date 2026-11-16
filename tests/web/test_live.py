# SPDX-License-Identifier: GPL-3.0-or-later
import json
import time

import pytest
from fastapi.testclient import TestClient

from wls.core.storage import verify_run
from wls.measurements import providers
from wls.web.app import create_app


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path, providers)) as client:
        client.runs_dir = tmp_path
        yield client


def stream(client) -> list[dict]:
    """All messages of the current run; returns when the run has finished."""
    with client.stream("GET", "/api/measure/stream") as response:
        assert response.headers["content-type"].startswith("text/event-stream")
        return [json.loads(line[6:]) for line in response.iter_lines() if line.startswith("data: ")]


def wait_idle(client, timeout=5.0):
    deadline = time.monotonic() + timeout
    while client.get("/api/measure").json()["running"]:
        assert time.monotonic() < deadline
        time.sleep(0.02)


def test_kinds_are_listed_with_defaults(client):
    kinds = {k["kind"]: k for k in client.get("/api/kinds").json()["kinds"]}
    assert {"diagnose", "ping", "wifi", "speed", "demo"} <= set(kinds)
    assert kinds["ping"]["target"] == "1.1.1.1"
    assert kinds["demo"]["available"] is True
    assert kinds["wifi"]["available"] or kinds["wifi"]["reason"]


def test_nothing_is_running_at_first(client):
    assert client.get("/api/measure").json()["running"] is False
    assert client.get("/api/measure/stream").status_code == 404


def test_demo_run_is_streamed_saved_and_listed(client):
    started = client.post("/api/measure", json={"kind": "demo", "duration": 0.6}).json()
    assert started["running"] is True and started["kind"] == "demo"

    messages = stream(client)
    types = [m["type"] for m in messages]
    assert types[0] == "started" and types[-1] == "finished"
    samples = [m for m in messages if m["type"] == "sample"]
    assert len(samples) >= 2
    assert samples[0]["probe"] == "sim" and "rtt_ms" in samples[0]["values"]
    assert [m["t"] for m in samples] == sorted(m["t"] for m in samples)
    states = [m["state"] for m in messages if m["type"] == "state"]
    assert states[-1] == "completed" and "measuring" in states
    assert messages[-1]["state"] == "completed"

    wait_idle(client)
    name = messages[-1]["name"]
    assert verify_run(client.runs_dir / name).intact
    assert name in [r["name"] for r in client.get("/api/runs").json()["runs"]]
    assert client.get(f"/api/runs/{name}").json()["kind"] == "demo"


def test_late_listener_gets_the_whole_run(client):
    client.post("/api/measure", json={"kind": "demo", "duration": 0.3})
    first = stream(client)
    again = stream(client)  # after the run has finished
    assert again == first


def test_stop_ends_a_long_run_early(client):
    client.post("/api/measure", json={"kind": "demo", "duration": 3000})
    time.sleep(0.4)
    assert client.post("/api/measure/stop").status_code == 200
    began = time.monotonic()
    messages = stream(client)
    assert time.monotonic() - began < 5
    assert messages[-1] == {"type": "finished", "name": messages[0]["name"], "state": "completed"}


def test_second_start_is_refused_while_one_is_running(client):
    client.post("/api/measure", json={"kind": "demo", "duration": 3000})
    assert client.post("/api/measure", json={"kind": "demo"}).status_code == 409
    client.post("/api/measure/stop")
    stream(client)
    wait_idle(client)
    assert client.post("/api/measure", json={"kind": "demo", "duration": 0.2}).status_code == 200
    stream(client)


def test_running_measurement_is_not_listed_as_a_finished_run(client):
    client.post("/api/measure", json={"kind": "demo", "duration": 3000})
    time.sleep(0.2)
    assert client.get("/api/runs").json()["runs"] == []
    client.post("/api/measure/stop")
    stream(client)


@pytest.mark.parametrize(
    ("body", "status"),
    [
        ({"kind": "nope"}, 400),
        ({"kind": "ping"}, 400),
        ({"kind": "ping", "target": "-f"}, 400),
        ({"kind": "ping", "target": "1.1.1.1 -f"}, 400),
        ({"kind": "demo", "duration": 0}, 422),
        ({"kind": "demo", "duration": 999999}, 422),
        ({}, 422),
    ],
)
def test_bad_requests_start_nothing(client, body, status):
    assert client.post("/api/measure", json=body).status_code == status
    assert client.get("/api/measure").json()["running"] is False
    assert not list(client.runs_dir.iterdir())


# --- only this computer, only this page ---------------------------------------------


def test_requests_for_a_foreign_host_name_are_refused(client):
    assert client.get("/api/runs", headers={"Host": "evil.example"}).status_code == 403
    assert client.get("/api/runs", headers={"Host": "127.0.0.1:8765"}).status_code == 200


def test_cross_site_post_is_refused(client):
    response = client.post(
        "/api/measure", json={"kind": "demo"}, headers={"Origin": "http://evil.example"}
    )
    assert response.status_code == 403
    assert client.get("/api/measure").json()["running"] is False
    same = client.post(
        "/api/measure", json={"kind": "demo", "duration": 0.2},
        headers={"Origin": "http://testserver"},
    )  # fmt: skip
    assert same.status_code == 200
    stream(client)
