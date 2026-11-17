"""장비 계층: 능력표, 모의 장비, 수신 전용 보장."""

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from nrtrail import devices, sigmf
from nrtrail.app import create_app
from nrtrail.engines.mock import MockEngine

SERVER = Path(__file__).resolve().parents[1] / "nrtrail"
ORDER = ["scan", "ssb", "mib", "sib1", "sib19"]


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("NRTRAIL_SESSIONS", str(tmp_path))
    with TestClient(create_app({"mock": MockEngine(delay_s=0)})) as c:
        yield c


def run(client, sid, stage, params=None):
    with client.websocket_connect(f"/api/ws/sessions/{sid}") as ws:
        r = client.post(f"/api/sessions/{sid}/stages/{stage}/run", json={"params": params or {}})
        assert r.status_code == 200, r.text
        while True:
            e = ws.receive_json()
            if e["type"] in ("job.finished", "job.failed"):
                return e


def test_no_transmit_path_anywhere_in_the_server():
    """수신 전용: 서버 소스 어디에도 SDR 송신 방향 상수·함수 호출이 없다."""
    banned = re.compile(r"SOAPY_SDR_TX|writeStream|\bsetupStream\([^)]*TX|tx_stream|\.transmit\(|\bsend_iq\b", re.I)
    hits = [f"{p.name}:{n}" for p in SERVER.rglob("*.py") for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
            if banned.search(line) and "banned" not in line]
    assert not hits, hits


def test_capability_table_matches_drivers():
    assert devices.capability_for("hackrf")["id"] == "hackrf"
    assert devices.capability_for("uhd", "B210")["id"] == "usrp_b2xx"
    assert devices.capability_for("uhd", "something")["id"] == "usrp_generic"
    assert devices.capability_for("rtlsdr")["stages"]["ssb"] == "no"
    assert devices.capability_for("mystery")["id"] == "unknown"
    for cap in devices.capabilities():
        assert set(cap["stages"]) == set(ORDER) and cap["max_sample_rate_hz"] > 0 and cap["freq_max_hz"] > cap["freq_min_hz"]


def test_request_check_and_cfo_widening():
    hackrf = devices._info("x", "HackRF", "hackrf", devices.capability_for("hackrf"))
    assert devices.check_request(hackrf, 3.5e9, 30.72e6) == ["RATE_TOO_HIGH"]
    assert devices.check_request(hackrf, 7e9, 10e6) == ["FREQ_OUT_OF_RANGE"]
    assert devices.check_request(hackrf, 2.1e9, 10e6) == []
    # 20 ppm x 2 GHz = 40 kHz 만큼 탐색 범위가 넓어진다
    assert devices.cfo_search_hz(hackrf, 2e9, 15_000) == pytest.approx(55_000)


def test_simulated_device_streams_a_file_to_sigmf(tmp_path):
    sims = [d for d in devices.list_devices() if d["driver"] == "simulated"]
    assert {d["id"] for d in sims} >= {"simulated:ntn-leo-n256", "simulated:terrestrial-n78"}
    got = devices.capture("simulated:ntn-leo-n256", devices.CaptureRequest(0, 0, 0.02), tmp_path / "a" / "0.sigmf-meta")
    assert got.datatype == "cf32_le" and got.num_samples == round(0.02 * got.sample_rate_hz) and got.source == "device"
    src = sigmf.read_meta(devices.GOLDEN / "ntn-leo-n256" / "capture.sigmf-meta")
    assert (got.read(0, 1000) == src.read(0, 1000)).all()
    with pytest.raises(devices.DeviceError):
        devices.capture("simulated:nope", devices.CaptureRequest(0, 0, 0.01), tmp_path / "b.sigmf-meta")


def test_device_session_end_to_end_with_simulated_device(client, tmp_path):
    """모의 장비로 종단: 장비에서 받기 -> 5단계 (M8 완료 기준). 신호처리는 저장된 결과 재생."""
    assert any(d["id"] == "simulated:ntn-leo-n256" for d in client.get("/api/devices").json())
    r = client.post("/api/sessions", json={"source": {"kind": "device", "device": "simulated:ntn-leo-n256"}, "engine": "mock"})
    assert r.status_code == 200, r.text
    sid = r.json()["id"]
    for stage in ORDER:
        e = run(client, sid, stage)
        assert e["type"] == "job.finished" and e["result"]["status"] == "ok", e
    caps = sorted((tmp_path / sid / "captures").glob("*.sigmf-meta"))
    assert len(caps) == 1 and sigmf.read_meta(caps[0]).source == "device"
    # 실패 화면의 버튼이 보내는 값: 이득을 올려 새로 받고 스캔부터 이 단계까지 다시 돈다
    e = run(client, sid, "ssb", {"gain_delta_db": 10})
    assert e["result"]["stage"] == "ssb" and e["result"]["status"] == "ok"
    s = client.get(f"/api/sessions/{sid}").json()
    assert s["source"]["gain_db"] == 40 and len(list((tmp_path / sid / "captures").glob("*.sigmf-meta"))) == 2
    assert [x["state"] for x in s["stages"]] == ["done", "done", "next", "locked", "locked"]


def test_live_device_input_stops_at_broadcast_information(client):
    """실시간 장비 입력으로는 방송 정보(SIB)까지만. 그 밖의 단계는 거절한다."""
    sid = client.post("/api/sessions", json={"source": {"kind": "device", "device": "simulated:ntn-leo-n256"}, "engine": "mock"}).json()["id"]
    assert client.post(f"/api/sessions/{sid}/stages/ra/run", json={"params": {}}).status_code in (403, 404)


def test_narrowband_device_is_limited_to_spectrum(client, monkeypatch):
    rtl = devices.capability_for("rtlsdr")
    monkeypatch.setattr(devices, "capability_for", lambda driver, label="": rtl)
    sid = client.post("/api/sessions", json={"source": {"kind": "device", "device": "simulated:ntn-leo-n256"}, "engine": "mock"}).json()["id"]
    e = run(client, sid, "scan")
    assert any(d["code"] == "RSSI_ONLY_DEVICE" for d in e["result"]["diagnostics"])
    r = client.post(f"/api/sessions/{sid}/stages/ssb/run", json={"params": {}})
    assert r.status_code == 403 and "스펙트럼" in r.json()["detail"]


def test_unknown_device_is_rejected(client):
    assert client.post("/api/sessions", json={"source": {"kind": "device", "device": "driver=nope"}}).status_code == 400
