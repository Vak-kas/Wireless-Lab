"""OAI NTN gNB(RF 시뮬레이터)가 실제로 방송한 SIB1·SIB19로 Python 쪽 해석을 대조한다.

자료(fixtures/oai/ntn_leo_broadcast.json)는 testbed/oai-ntn 레시피로 기록한 신호를 nrtrail(MATLAB)로 복호해 얻은 전송 블록이다.
우리가 만든 합성 파형이 아니라 **다른 구현(OpenAirInterface)** 이 만든 메시지라서, 단위·규칙 해석이 독립적으로 확인된다.
"""

import json
from pathlib import Path

import pytest
from nrtrail import tracking
from nrtrail.asn1 import rrc
from nrtrail.nr import ntn, occasions, sched
from nrtrail.pipeline import load_pipeline
from nrtrail.stages import sib1 as sib1_stage
from nrtrail.stages import sib19 as sib19_stage
from nrtrail.stages.base import Ctx

FX = json.loads((Path(__file__).parent / "fixtures" / "oai" / "ntn_leo_broadcast.json").read_text(encoding="utf-8"))


def test_oai_mib_and_sib1_decode():
    mib, _ = rrc.decode("BCCH-BCH-Message", bytes.fromhex(FX["mib_hex"]))
    assert rrc.find_path(mib, "message", "mib")["pdcch-ConfigSIB1"] == {"controlResourceSetZero": 2, "searchSpaceZero": 2}
    value, tree = rrc.decode("BCCH-DL-SCH-Message", bytes.fromhex(FX["sib1_tb_hex"]))
    sib1 = rrc.find_path(value, "message", "c1", "systemInformationBlockType1")
    msgs = sib1_stage.si_messages(sib1)
    assert [(m["sibs"], m["period"], m["list"]) for m in msgs] == [(["SIB2"], "rf16", "schedulingInfoList"),
                                                                    (["SIB19"], "rf16", "schedulingInfoList2-r17")]
    pcc = tree["message"]["c1"]["systemInformationBlockType1"]["servingCellConfigCommon"]["downlinkConfigCommon"]["initialDownlinkBWP"]["pdcch-ConfigCommon"]["setup"]
    assert pcc["searchSpaceOtherSystemInformation"] == 3
    rule = occasions.parse_search_space(next(x for x in pcc["commonSearchSpaceList"] if x["searchSpaceId"] == 3))
    assert (rule["coreset_id"], rule["period_slots"], rule["first_symbols"], rule["candidates"]) == (0, 1, [0], {4: 2})
    tdl = sib1["servingCellConfigCommon"]["downlinkConfigCommon"]["initialDownlinkBWP"]["pdsch-ConfigCommon"][1]["pdsch-TimeDomainAllocationList"]
    assert [sched.sliv_decode(e["startSymbolAndLength"]) for e in tdl] == [(2, 12), (2, 11)]


def test_oai_sib19_was_found_inside_the_si_window_python_computed():
    # si-WindowPosition 2, 창 10슬롯, 주기 16프레임 -> SFN mod 16 = 1, 슬롯 0~9
    w = sched.si_window(2, "s10", "rf16", 10)
    assert (w.frame_offset, w.slot) == (1, 0)
    for m in FX["si_messages"]:
        assert occasions.in_si_window(m, w), m


def assemble(tb_hex):
    return sib19_stage.assemble(load_pipeline().stage("sib19"), {"ok": True, "bits": {"tb_hex_list": [tb_hex]}, "measurements": {}}, Ctx(capture={}))


def test_oai_orbit_is_physical_and_consecutive_sib19_follow_two_body_motion():
    """OAI가 160 ms마다 새로 방송한 위성 위치가, 앞의 값을 이 도구의 궤도 전파로 옮긴 위치와 5 m 안에서 같다.
    위치(1.3 m)·속도(0.06 m/s) 단위와 epochTime 해석이 맞다는 독립적인 확인이다."""
    results = [assemble(h) for h in FX["si_tb_hex_list"]]
    assert len(results) == 4 and all(r.status == "ok" for r in results)
    fields = [tracking.sib19_fields(r.next_inputs) for r in results]
    assert [f["epoch_sfn"] for f in fields] == [465, 481, 497, 513]
    for prev, new in zip(fields, fields[1:], strict=False):
        assert tracking.position_jump_km(prev, new) < 0.005
    eph = results[0].next_inputs["ephemeris"]
    pos, vel = tuple(eph["pos_m"]), tuple(eph["vel_mps"])
    alt = ntn.ecef_to_geodetic(pos)[2] / 1e3
    assert 590 < alt < 620
    assert ntn.norm(vel) == pytest.approx(ntn.circular_speed(ntn.norm(pos)), rel=2e-3)


def test_oai_common_ta_drift_matches_the_change_between_broadcasts():
    """ta-Common이 160 ms 사이에 변한 양 = ta-CommonDrift x 0.16 s. 두 필드의 단위(4.072e-3 µs, 0.2e-3 µs/s)가 서로 맞는다."""
    vals = []
    for h in FX["si_tb_hex_list"]:
        r = assemble(h)
        vals.append({v.key: getattr(v.value, "root", v.value) for v in r.values})
    for a, b in zip(vals, vals[1:], strict=False):
        assert (b["ta_common"] - a["ta_common"]) == pytest.approx(a["ta_drift"] * 0.16, abs=0.01)
    assert vals[0]["k_offset"] == 40 and vals[0]["validity"] == 5


def test_oai_ntn_calculation_under_the_satellite_and_from_far_away():
    """OAI가 방송한 궤도로 위성 계산: 위성 바로 아래에서는 정상, 지구 반대편(한국)에서는 '지평선 아래' 이상 징후가 뜬다."""
    from nrtrail.stages import ntn as ntn_stage

    first = assemble(FX["si_tb_hex_list"][0])
    pos = tuple(first.next_inputs["ephemeris"]["pos_m"])
    lat, lon, _ = ntn.ecef_to_geodetic(pos)
    assert (round(lat, 1), round(lon, 1)) == (66.3, -90.0)
    common = dict(sib19=first.next_inputs, n_ta_offset=0, mib={"sfn": 465, "half_frame": 0}, cfo_hz=None, carrier_hz=2_488_850_000.0,
                  t_offset_s=0.0, thresholds={})
    under = ntn_stage.assemble(load_pipeline().stage("ntn"), location={"lat": lat, "lon": lon, "alt_m": 0.0}, **common)
    val = {v.key: getattr(v.value, "root", v.value) for v in under.values}
    assert under.status == "ok" and val["elevation"] > 89 and val["range"] == pytest.approx(val["altitude"], abs=1.0)
    assert val["k_offset_ok"] is True and 20 < val["ta_total"] < 40          # 공통 지연 18.8 ms + 서비스 링크 왕복 4.1 ms < K_offset 40 ms
    far = ntn_stage.assemble(load_pipeline().stage("ntn"), location={"lat": 36.35, "lon": 127.38, "alt_m": 60.0}, **common)
    assert "BELOW_HORIZON" in {d.code for d in far.diagnostics if d.level == "warn"}
