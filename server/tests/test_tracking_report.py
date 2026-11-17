"""추적, 기록·재생, 리포트."""

import time

import pytest
from fastapi.testclient import TestClient
from nrtrail import tracking
from nrtrail.app import create_app
from nrtrail.engines.mock import MockEngine

ORDER = ["scan", "ssb", "mib", "sib1", "sib19"]


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("NRTRAIL_SESSIONS", str(tmp_path))
    with TestClient(create_app({"mock": MockEngine(delay_s=0)})) as c:
        yield c


def run_all(client, source):
    sid = client.post("/api/sessions", json={"source": source}).json()["id"]
    results = {}
    for stage in ORDER:
        with client.websocket_connect(f"/api/ws/sessions/{sid}") as ws:
            assert client.post(f"/api/sessions/{sid}/stages/{stage}/run", json={"params": {}}).status_code == 200
            while True:
                e = ws.receive_json()
                if e["type"] in ("job.finished", "job.failed"):
                    results[stage] = e.get("result")
                    break
    return sid, results


def wait_points(client, sid, n, timeout=10.0):
    t0 = time.time()
    while time.time() - t0 < timeout:
        data = client.get(f"/api/sessions/{sid}/track/timeseries").json()
        if len(data["points"]) >= n and not data["running"]:
            return data
        time.sleep(0.05)
    raise AssertionError("추적이 끝나지 않음")


def test_tracking_records_a_timeseries_and_exports_csv(client):
    sid, _ = run_all(client, {"kind": "synthetic", "scenario": "ntn-leo-n256"})
    assert client.post(f"/api/sessions/{sid}/track/start", json={"interval_s": 0.2, "max_points": 4}).status_code == 200
    data = wait_points(client, sid, 4)
    pts = data["points"]
    assert [p["t_s"] for p in pts] == [0.0, 0.2, 0.4, 0.6] and data["replay"] is True
    assert len({p["cfo_hz"] for p in pts}) == 1                      # 같은 캡처를 다시 읽으므로 측정값은 같다
    assert len({p["ta_total_ms"] for p in pts}) == 4                 # 궤도로 계산한 값은 시간에 따라 변한다
    assert {s["key"] for s in data["series"]} >= {"cfo_hz", "ta_total_ms", "doppler_pred_hz"}
    csv_text = client.get(f"/api/sessions/{sid}/track/timeseries.csv").text
    assert csv_text.splitlines()[0].startswith("t_s,cfo_hz") and len(csv_text.splitlines()) == 5
    assert client.get(f"/api/sessions/{sid}/track/changes").json() == []
    # 표시 중인 단계 결과는 추적이 건드리지 않는다
    assert [s["state"] for s in client.get(f"/api/sessions/{sid}").json()["stages"]] == ["done"] * 5


def test_tracking_needs_sib19_and_can_be_stopped(client):
    sid = client.post("/api/sessions", json={"source": {"kind": "synthetic", "scenario": "ntn-leo-n256"}}).json()["id"]
    assert client.post(f"/api/sessions/{sid}/track/start", json={"interval_s": 1}).status_code == 409
    sid, _ = run_all(client, {"kind": "synthetic", "scenario": "ntn-leo-n256"})
    client.post(f"/api/sessions/{sid}/track/start", json={"interval_s": 0.2})
    assert client.post(f"/api/sessions/{sid}/track/start", json={"interval_s": 0.2}).status_code == 409
    assert client.post(f"/api/sessions/{sid}/track/stop", json={}).json()["running"] is False
    assert client.get(f"/api/sessions/{sid}").json()["tracking"] is False


def test_sib19_changes_and_orbit_jump_detection():
    base = {"epoch_sfn": 420, "epoch_subframe": 0, "validity_s": 20, "k_offset": 16, "ta_common": 1964636, "ta_drift": -12,
            "ta_drift_variant": 0, "pos_x": -2613462, "pos_y": 3468000, "pos_z": 3155077, "vel_x": -72107, "vel_y": -93772, "vel_z": 43330}
    # 1초 뒤의 정상 갱신: 궤도를 따라 움직인 위치 -> 점프 아님
    from nrtrail.nr import ntn
    p, v = ntn.propagate(tuple(base[f"pos_{a}"] * 1.3 for a in "xyz"), tuple(base[f"vel_{a}"] * 0.06 for a in "xyz"), 1.0)
    moved = base | {"epoch_sfn": 520} | {f"pos_{a}": round(x / 1.3) for a, x in zip("xyz", p, strict=True)} \
        | {f"vel_{a}": round(x / 0.06) for a, x in zip("xyz", v, strict=True)}
    assert tracking.position_jump_km(base, moved) < 0.01
    # 같은 시각에 위치만 100 km 옮겨진 값 -> 점프
    spoofed = moved | {"pos_x": moved["pos_x"] + round(100e3 / 1.3)}
    assert tracking.position_jump_km(base, spoofed) == pytest.approx(100, abs=0.1)


def test_recording_makes_the_session_replayable_with_identical_results(client, tmp_path):
    """기록 -> 그 파일을 입력으로 다시 실행 -> 같은 결과 (SPEC 8절, M7 완료 기준)."""
    sid, first = run_all(client, {"kind": "synthetic", "scenario": "ntn-leo-n256"})
    s = client.post(f"/api/sessions/{sid}/record", json={"on": True}).json()
    assert s["recording"] is True
    meta = tmp_path / sid / "captures" / "0.sigmf-meta"
    assert meta.exists() and (tmp_path / sid / "captures" / "0.sigmf-data").stat().st_size > 1_000_000
    replay = client.post("/api/sessions", json={"source": {"kind": "file", "path": str(meta)}, "engine": "mock"})
    assert replay.status_code == 200, replay.text
    assert replay.json()["source"]["kind"] == "file"


def test_report_contains_every_stage_values_plots_and_derivations(client):
    sid, _ = run_all(client, {"kind": "synthetic", "scenario": "ntn-leo-n256"})
    client.post(f"/api/sessions/{sid}/track/start", json={"interval_s": 0.2, "max_points": 2})
    wait_points(client, sid, 2)
    html = client.get(f"/api/sessions/{sid}/report.html").text
    for needle in ("대역 스캔", "SSB 동기", "MIB", "SIB1", "SIB19", "위성 계산", "계산 과정", "TS 38.213 4.2", "<svg", "추적 기록", "N_{TA,adj}^{UE}"):
        assert needle in html, needle
    assert "http://" not in html and "https://" not in html  # 외부 자원을 불러오지 않는다
    empty = client.post("/api/sessions", json={"source": {"kind": "synthetic", "scenario": "weak-n256"}}).json()["id"]
    assert "실행하지 않음" in client.get(f"/api/sessions/{empty}/report.html").text
