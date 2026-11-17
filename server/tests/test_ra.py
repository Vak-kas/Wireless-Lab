"""랜덤 액세스 관측(테스트베드 전용): RA-RNTI, RAR, TA -> 거리, Msg4."""

import pytest
from fastapi.testclient import TestClient
from nrtrail import mockraw
from nrtrail.app import create_app
from nrtrail.engines.mock import MockEngine
from nrtrail.nr import ntn, pdsch, ra


def test_ra_rnti_formula():
    assert ra.ra_rnti(0, 0, 0) == 1
    assert ra.ra_rnti(0, 19, 0) == 267
    assert ra.ra_rnti(13, 79, 7, 1) == 1 + 13 + 14 * 79 + 1120 * 7 + 8960    # 가능한 최댓값 17920
    with pytest.raises(ValueError):
        ra.ra_rnti(14, 0, 0)
    assert ra.prach_slot_index(9, 30, 1) == 19 and ra.prach_slot_index(4, 15, None) == 4 and ra.prach_slot_index(4, 30, 2) == 8


def test_rar_roundtrip_and_bit_layout():
    pdu = ra.build_rar_pdu(rapid=23, ta_command=77, ul_grant=0x0123456, tc_rnti=0x4601)
    assert len(pdu) == 8 and pdu[0] == 0x40 | 23
    # 손으로 짠 비트: R(1)=0 | TA(12)=77 | grant(27) | TC-RNTI(16)
    assert int.from_bytes(pdu[1:], "big") == (77 << 43) | (0x0123456 << 16) | 0x4601
    parsed = ra.parse_rar_pdu(pdu + b"\x00" * 10)
    assert parsed.backoff_indicator is None and len(parsed.rars) == 1
    r = parsed.rars[0]
    assert (r.rapid, r.ta_command, r.ul_grant, r.tc_rnti) == (23, 77, 0x0123456, 0x4601)
    assert sum(n for _, n in ra.UL_GRANT_FIELDS) == 27
    with_bi = ra.parse_rar_pdu(ra.build_rar_pdu(5, 3846, 0, 1, backoff=9))
    assert with_bi.backoff_indicator == 9 and with_bi.rars[0].ta_command == 3846
    with pytest.raises(ValueError):
        ra.parse_rar_pdu(b"\x57\x00")


def test_ul_grant_fields_split_msb_first():
    grant = (1 << 26) | (0x2ABC << 12) | (0x9 << 8) | (0xA << 4) | (0x5 << 1) | 1
    f = ra._grant_fields(grant)
    assert f == {"frequency hopping flag": 1, "PUSCH frequency resource allocation": 0x2ABC, "PUSCH time resource allocation": 9,
                 "MCS": 10, "TPC command for PUSCH": 5, "CSI request": 1}


def test_ta_command_to_distance():
    # T_A = 1, 15 kHz: 16*64 Tc = 0.5208 µs -> 편도 78.1 m
    assert ra.n_ta_from_command(1, 15) == 1024 and ra.n_ta_from_command(1, 30) == 512
    assert ra.distance_from_n_ta(1024) == pytest.approx(78.07, abs=0.01)
    assert ra.n_ta_from_command(77, 30) * ntn.TC == pytest.approx(20.052e-6, rel=1e-4)


def test_msg4_pdu_roundtrip_ignores_zero_padding():
    pdu = ra.build_msg4_pdu(bytes.fromhex("a1b2c3d4e5f6"), bytes.fromhex("0880"))
    for padded in (pdu, pdu + b"\x00" * 30):
        m = ra.parse_msg4_pdu(padded)
        assert m == {"contention_id": "a1b2c3d4e5f6", "ccch_sdu": "0880", "other_lcids": []}
    assert ra.parse_msg4_pdu(b"\x00" * 8)["contention_id"] is None


def test_ra_dci_has_same_length_as_si_dci_and_tb_scaling_shrinks_tbs():
    bits = ra.dci_1_0_ra_build(24, riv=48, tdra=0, mcs=2, tb_scaling=1)
    assert len(bits) == len(pdsch.dci_1_0_si_build(24, 48, 0, 0, 2, 0, 0)) == 37
    assert ra.dci_1_0_ra_parse(bits, 24)["TB scaling"] == 1 and ra.dci_1_0_ra_parse(bits, 24)["modulation and coding scheme"] == 2
    assert pdsch.tbs(12, 12, 36, 2, 193, scaling=0.5).tbs < pdsch.tbs(12, 12, 36, 2, 193).tbs


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("NRTRAIL_SESSIONS", str(tmp_path))
    with TestClient(create_app({"mock": MockEngine(delay_s=0)})) as c:
        yield c


def run(client, sid, stage):
    with client.websocket_connect(f"/api/ws/sessions/{sid}") as ws:
        r = client.post(f"/api/sessions/{sid}/stages/{stage}/run", json={"params": {}})
        assert r.status_code == 200, r.text
        while True:
            e = ws.receive_json()
            if e["type"] in ("job.finished", "job.failed"):
                return e


def test_ra_observation_on_synthetic_input_matches_the_known_answer(client):
    """합성 RAR 정답 일치 (M10 완료 기준의 Python 쪽: 저장된 결과로 조립까지)."""
    sid = client.post("/api/sessions", json={"source": {"kind": "synthetic", "scenario": "terrestrial-n78"}}).json()["id"]
    assert client.post(f"/api/sessions/{sid}/stages/ra/run", json={"params": {}}).status_code == 409   # SIB1 전에는 잠김
    for stage in ("scan", "ssb", "mib", "sib1"):
        run(client, sid, stage)
    e = run(client, sid, "ra")
    assert e["type"] == "job.finished", e
    result = e["result"]
    val = {v["key"]: v["value"] for v in result["values"]}
    truth = mockraw.RA_SAMPLE
    assert result["status"] == "ok" and val["ra_rnti"] == 267
    assert (val["rapid"], val["ta_command"], val["tc_rnti"]) == (truth["rapid"], truth["ta_command"], f"0x{truth['tc_rnti']:04X}")
    assert val["contention_id"] == truth["contention_id"] and val["msg4_rrc"] == "rrcReject"
    assert val["distance"] == pytest.approx(3005.7, abs=0.1)
    ids = {d["id"] for d in result["derivations"]}
    assert {"ra.ra_rnti", "ra.n_ta", "ra.distance", "ra.grant"} <= ids
    # 다시 SIB1을 돌리면 RA 결과는 지워진다. 그래도 5단계 사슬의 상태에는 RA가 끼어들지 않는다
    assert [s["stage"] for s in client.get(f"/api/sessions/{sid}").json()["stages"]] == ["scan", "ssb", "mib", "sib1", "sib19"]


def test_ra_is_refused_for_live_device_and_unmarked_files(client, tmp_path):
    """상용망 개별 단말 통신 수집 금지: 실시간 장비 입력과 testbed 표시가 없는 파일에서는 열리지 않는다."""
    sid = client.post("/api/sessions", json={"source": {"kind": "device", "device": "simulated:terrestrial-n78"}, "engine": "mock"}).json()["id"]
    for stage in ("scan", "ssb", "mib", "sib1"):
        run(client, sid, stage)
    r = client.post(f"/api/sessions/{sid}/stages/ra/run", json={"params": {}})
    assert r.status_code == 403 and "테스트베드" in r.json()["detail"]
