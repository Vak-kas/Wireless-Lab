"""서버: 세션·작업·이벤트. MockEngine으로 MATLAB 없이 전 과정을 돈다."""

import pytest
from fastapi.testclient import TestClient
from nrtrail.app import create_app
from nrtrail.engines.mock import MockEngine

ORDER = ["scan", "ssb", "mib", "sib1", "sib19"]


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("NRTRAIL_SESSIONS", str(tmp_path))
    with TestClient(create_app({"mock": MockEngine(delay_s=0)})) as c:
        yield c


def new_session(client, scenario="ntn-leo-n256"):
    r = client.post("/api/sessions", json={"source": {"kind": "synthetic", "scenario": scenario}})
    assert r.status_code == 200, r.text
    return r.json()


def run(client, sid, stage, params=None):
    """단계를 실행하고 끝날 때까지의 이벤트를 모은다."""
    with client.websocket_connect(f"/api/ws/sessions/{sid}") as ws:
        r = client.post(f"/api/sessions/{sid}/stages/{stage}/run", json={"params": params or {}})
        assert r.status_code == 200, r.text
        events = []
        while True:
            e = ws.receive_json()
            events.append(e)
            if e["type"] in ("job.finished", "job.failed"):
                return events


def states(session):
    return [s["state"] for s in session["stages"]]


def test_info_endpoints(client):
    assert client.get("/api/health").json()["ok"] is True
    assert [s["id"] for s in client.get("/api/pipeline").json()["stages"]] == ORDER
    assert "ssb" in client.get("/api/glossary").json()
    assert {s["id"] for s in client.get("/api/scenarios").json()} >= {"ntn-leo-n256", "weak-n256"}
    assert client.get("/api/doctor?quick=1").json()["engines"]["mock"] is True
    assert client.get("/api/settings").json()["location"]["lat"] == 36.35


def test_full_practice_run_with_events(client):
    s = new_session(client)
    assert states(s) == ["next", "locked", "locked", "locked", "locked"] and s["practice"] is True
    for stage in ORDER:
        events = run(client, s["id"], stage)
        types = [e["type"] for e in events]
        assert types[0] == "job.started" and types[-1] == "job.finished", events[-1]
        assert events[-1]["result"]["status"] == "ok" and events[-1]["result"]["stage"] == stage
        if stage in ("scan", "ssb", "mib"):
            assert any(e["type"] == "job.progress" and e["message"] for e in events)
    s = client.get(f"/api/sessions/{s['id']}").json()
    assert states(s) == ["done"] * 5 and s["selected_cell"]["pci"] == 502
    assert client.get(f"/api/sessions/{s['id']}/results/sib19").json()["status"] == "ok"
    assert client.get(f"/api/sessions/{s['id']}/results/mib?run=1").json()["stage"] == "mib"


def test_locked_stage_and_unknown_things(client):
    s = new_session(client)
    assert client.post(f"/api/sessions/{s['id']}/stages/mib/run", json={"params": {}}).status_code == 409
    assert client.post(f"/api/sessions/{s['id']}/stages/nope/run", json={"params": {}}).status_code == 404
    assert client.get(f"/api/sessions/{s['id']}/results/scan").status_code == 404
    assert client.get("/api/sessions/nope").status_code == 404
    assert client.post("/api/sessions", json={"source": {"kind": "synthetic", "scenario": "nope"}}).status_code == 400
    assert client.post("/api/sessions", json={"source": {"kind": "file", "path": "/nope.sigmf-meta"}}).status_code == 400


def test_failure_keeps_next_stage_locked(client):
    s = new_session(client, "weak-n256")
    for stage in ("scan", "ssb"):
        run(client, s["id"], stage)
    result = run(client, s["id"], "mib")[-1]["result"]
    assert result["status"] == "fail" and result["diagnostics"][0]["action"]["label"]
    s = client.get(f"/api/sessions/{s['id']}").json()
    assert states(s) == ["done", "done", "next", "locked", "locked"] and s["stages"][2]["last_status"] == "fail"


def test_sessions_survive_restart_and_can_be_deleted(client, tmp_path):
    s = new_session(client)
    for stage in ("scan", "ssb", "mib"):
        run(client, s["id"], stage)
    with TestClient(create_app({"mock": MockEngine(delay_s=0)})) as again:
        restored = again.get(f"/api/sessions/{s['id']}").json()
        assert states(restored) == ["done", "done", "done", "next", "locked"]
        assert run(again, s["id"], "sib1")[-1]["result"]["status"] == "ok"
        assert again.delete(f"/api/sessions/{s['id']}").status_code == 204
        assert again.get("/api/sessions").json() == []
    assert not (tmp_path / s["id"]).exists()


def test_same_input_gives_same_result(client):
    """같은 파일이면 같은 결과(결정적 처리)."""
    a, b = new_session(client), new_session(client)
    for stage in ORDER:
        ra = run(client, a["id"], stage)[-1]["result"]
        rb = run(client, b["id"], stage)[-1]["result"]
        ra.pop("meta"), rb.pop("meta")
        assert ra == rb


def test_ntn_calculation(client):
    s = new_session(client)
    assert client.post(f"/api/sessions/{s['id']}/ntn", json={"lat": 36.35, "lon": 127.38, "alt_m": 60}).status_code == 409
    for stage in ORDER:
        run(client, s["id"], stage)
    r = client.post(f"/api/sessions/{s['id']}/ntn", json={"lat": 36.35, "lon": 127.38, "alt_m": 60})
    assert r.status_code == 200, r.text
    result = r.json()
    assert result["stage"] == "ntn" and result["status"] == "ok"
    assert any(p["type"] == "sky_geometry" for p in result["plots"])
    val = {v["key"]: v["value"] for v in result["values"]}
    assert 600 < val["range"] < 620 and 80 < val["elevation"] <= 90 and val["k_offset_ok"] is True
    assert client.post(f"/api/sessions/{s['id']}/ntn", json={"lat": 99, "lon": 0}).status_code == 422


def test_settings_validation_and_persistence(client):
    s = client.get("/api/settings").json()
    s["location"] = {"lat": 37.5, "lon": 127.0, "alt_m": 30}
    assert client.put("/api/settings", json=s).json()["location"]["lat"] == 37.5
    assert client.get("/api/settings").json()["location"]["lon"] == 127.0
    s["location"]["lat"] = 123
    assert client.put("/api/settings", json=s).status_code == 422


def test_english_overlay_has_the_same_shape_and_placeholders():
    """영어 덮어쓰기: 구조가 같고, 번역된 요약 문구의 {자리}가 한국어와 같아야 한다(다르면 실행 중 오류가 난다)."""
    import json
    import re

    from nrtrail.paths import PIPELINE

    ko = json.loads((PIPELINE / "stages.json").read_text(encoding="utf-8"))
    en = json.loads((PIPELINE / "stages.en.json").read_text(encoding="utf-8"))

    def walk(a, b, path):
        if isinstance(a, dict):
            for k, v in b.items():
                assert k in a or k == "_comment", f"{path}/{k}: 한국어에 없는 키"
                if k in a:
                    walk(a[k], v, f"{path}/{k}")
        elif isinstance(a, list):
            assert isinstance(b, list) and len(a) == len(b), f"{path}: 목록 길이가 다름"
            for i, (x, y) in enumerate(zip(a, b, strict=True)):
                walk(x, y, f"{path}[{i}]")
        elif isinstance(a, str) and isinstance(b, str) and b:
            assert set(re.findall(r"\{(\w+)\}", a)) == set(re.findall(r"\{(\w+)\}", b)), f"{path}: 자리 이름이 다름"

    walk({"stages": [{k: v for k, v in s.items() if k not in ("id", "requires", "spec_refs")} for s in ko["stages"]],
          "views": [{k: v for k, v in s.items() if k not in ("id", "requires", "spec_refs")} for s in ko["views"]],
          "common_diagnostics": ko["common_diagnostics"]}, en, "")
    kg = json.loads((PIPELINE / "glossary.json").read_text(encoding="utf-8"))["terms"]
    eg = json.loads((PIPELINE / "glossary.en.json").read_text(encoding="utf-8"))["terms"]
    assert set(kg) == set(eg) and all(v["short"] for v in eg.values())


def test_language_setting_switches_server_texts(client):
    assert client.get("/api/pipeline").json()["stages"][0]["title"] == "대역 스캔"
    assert client.get("/api/pipeline?lang=en").json()["stages"][0]["title"] == "Band scan"
    s = client.get("/api/settings").json()
    s["lang"] = "en"
    client.put("/api/settings", json=s)
    assert client.get("/api/pipeline").json()["stages"][1]["button"] == "Synchronise to SSB"
    assert "beacon" in client.get("/api/glossary").json()["ssb"]["short"]
    sid = new_session(client)["id"]
    result = run(client, sid, "scan")[-1]["result"]
    assert result["summary_easy"].startswith("Found 1 base station")
