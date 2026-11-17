"""단계 조립: 저장된 원시 결과(MATLAB 정답 + mock)로 MATLAB 없이 돈다."""

import json

import pytest
from nrtrail.contracts_gen import StageResult
from nrtrail.engines.mock import MockEngine
from nrtrail.paths import GOLDEN, PIPELINE
from nrtrail.pipeline import load_pipeline
from nrtrail.result import ContractError, ResultBuilder
from nrtrail.runner import RunState, StageLocked, StageNotAllowed, check_allowed, run_stage

SCENARIOS = {s["id"]: s for s in json.loads((PIPELINE / "scenarios.json").read_text(encoding="utf-8"))["scenarios"]}


def new_state(sid: str) -> RunState:
    sc = SCENARIOS[sid]
    return RunState(capture={"center_freq_hz": sc["center_freq_hz"], "sample_rate_hz": sc["sample_rate_hz"],
                             "source_kind": "synthetic"}, scenario=sid, band=sc["band"])


def run_all(sid: str) -> dict[str, StageResult]:
    state, pipe, eng = new_state(sid), load_pipeline(), MockEngine(delay_s=0)
    for stage in pipe.order:
        try:
            run_stage(eng, pipe, stage, state)
        except StageLocked:
            break
    return state.results


def test_ntn_scenario_goes_to_the_end():
    r = run_all("ntn-leo-n256")
    assert [r[s].status for s in ("scan", "ssb", "mib", "sib1", "sib19")] == ["ok"] * 5
    assert any(v.key == "has_sib19" and v.value.root is True for v in r["sib1"].values)
    alt = next(v for v in r["sib19"].values if v.key == "altitude")
    assert 590 < alt.value.root < 620


def test_terrestrial_has_no_sib19_and_weak_fails_at_mib():
    r = run_all("terrestrial-n78")
    assert r["sib1"].status == "ok" and r["sib19"].status == "fail"
    assert r["sib19"].diagnostics[0].code == "NOT_SCHEDULED" and r["sib19"].diagnostics[0].action
    r = run_all("weak-n256")
    assert r["ssb"].status == "partial" and r["mib"].status == "fail" and "sib1" not in r
    assert all(d.action for d in r["mib"].diagnostics)


@pytest.mark.parametrize("sid", list(SCENARIOS))
def test_every_shown_value_has_a_source(sid):
    for result in run_all(sid).values():
        ids = {d.id for d in result.derivations}
        for v in result.values:
            if v.kind == "derived":
                assert v.derivation_id in ids, f"{result.stage}.{v.key}"
            if v.kind == "decoded":
                assert v.source, f"{result.stage}.{v.key}"
        for d in result.derivations:
            assert d.formula_tex and d.inputs and d.steps and d.spec_ref.startswith(("TS ", "TR ")), d.id


def test_builder_rejects_derived_value_without_derivation():
    b = ResultBuilder(load_pipeline().stage("scan"))
    b.derived("best_pci", 1, "scan.nope")
    with pytest.raises(ContractError):
        b.build("ok", count=1, freq_mhz=1, gscn=1, pci=1, pnr=1)


@pytest.mark.parametrize("sid", ["ntn-leo-n256", "terrestrial-n78"])
def test_decoded_values_match_matlab_truth(sid):
    """합성 파형의 정답(truth.json)과 Python이 푼 값이 정확히 같아야 한다."""
    truth = json.loads((GOLDEN / sid / "truth.json").read_text(encoding="utf-8"))["config"]
    r = run_all(sid)
    val = {v.key: v.value.root for v in r["mib"].values}
    assert val["k_ssb"] == truth["mib"]["k_ssb"] and val["pdcch_config_sib1"] == truth["mib"]["pdcch_config_sib1"]
    assert val["dmrs_typea_pos"] == truth["mib"]["dmrs_typea_pos"]
    assert next(v.value.root for v in r["ssb"].values if v.key == "pci") == truth["ncellid"]
    # 수신기는 캡처 안의 어느 프레임의 SSB에든 동기될 수 있다. 읽은 SFN과 프레임 시작 위치가 합성기의 시간축과 맞는지 본다:
    # 합성기는 SFN = mib.sfn 인 프레임을 캡처 샘플 timing_offset_samples 에서 시작한다.
    frame_len = 0.010 * truth["carrier"]["sample_rate_hz"]
    frames_after = (val["sfn"] - truth["mib"]["sfn"]) % 1024
    assert frames_after < truth["carrier"]["n_frames"]
    diff = (val["frame_start"] - truth["channel"]["timing_offset_samples"]) % frame_len
    assert min(diff, frame_len - diff) <= 2


def test_rerun_clears_later_stages_and_lock_is_enforced():
    state, pipe, eng = new_state("ntn-leo-n256"), load_pipeline(), MockEngine(delay_s=0)
    with pytest.raises(StageLocked):
        run_stage(eng, pipe, "mib", state)
    for s in ("scan", "ssb", "mib"):
        run_stage(eng, pipe, s, state)
    run_stage(eng, pipe, "scan", state)
    assert set(state.results) == {"scan"}


def test_live_device_input_is_limited_to_broadcast_stages():
    state = RunState(capture={"center_freq_hz": 1, "sample_rate_hz": 1, "source_kind": "device"})
    check_allowed("sib19", state)
    with pytest.raises(StageNotAllowed):
        check_allowed("ra", state)
    state.capture["source_kind"] = "file"
    with pytest.raises(StageNotAllowed):
        check_allowed("ra", state)
    state.testbed = True
    check_allowed("ra", state)


@pytest.mark.parametrize("sid", ["ntn-leo-n256", "terrestrial-n78"])
def test_sib1_decoded_by_matlab_equals_what_python_encoded(sid):
    """M5 정답 일치: MATLAB이 합성 파형에서 복호한 전송 블록 = Python ASN.1 인코더가 넣은 바이트, 그리고 풀어낸 필드 = 넣은 값."""
    from nrtrail import mockraw
    from nrtrail.asn1 import rrc, samples

    path = GOLDEN / sid / "sib1.json"
    if not path.exists():
        pytest.skip("골든에 sib1.json 없음")
    raw = json.loads(path.read_text(encoding="utf-8"))
    cfg = json.loads((GOLDEN / sid / "cfg.json").read_text(encoding="utf-8"))
    assert raw["ok"] and raw["bits"]["tb_hex"] == cfg["sib1"]["tb_hex"]
    m = raw["measurements"]
    assert (m["dci"]["riv"], m["dci"]["mcs"], m["rb_len"], m["sym_start"], m["sym_len"], m["tbs"], m["n_dmrs_per_prb"]) == (
        cfg["sib1"]["dci"]["riv"], cfg["sib1"]["dci"]["mcs"], cfg["sib1"]["rb_len"], cfg["sib1"]["sym_start"], cfg["sib1"]["sym_len"],
        cfg["sib1"]["tbs"], cfg["sib1"]["n_dmrs_per_prb"])
    expected = samples.bcch_dl_sch_sib1(mockraw.sib1_value(SCENARIOS[sid]))
    decoded, _ = rrc.decode("BCCH-DL-SCH-Message", bytes.fromhex(raw["bits"]["tb_hex"]))
    assert decoded == expected
    r = run_all(sid)["sib1"]
    assert r.status == "ok" and not [d for d in r.diagnostics if d.code == "INTERNAL"]      # Python이 계산한 TBS = 엔진의 TBS
    val = {v.key: getattr(v.value, "root", v.value) for v in r.values}
    assert val["plmn"] == "001-01" and val["tbs"] == cfg["sib1"]["tbs"] and val["has_sib19"] is SCENARIOS[sid]["ntn"]


def test_sib19_decoded_by_matlab_equals_what_python_encoded():
    from nrtrail import mockraw
    from nrtrail.asn1 import rrc, samples

    sid = "ntn-leo-n256"
    path = GOLDEN / sid / "sib19.json"
    if not path.exists():
        pytest.skip("골든에 sib19.json 없음")
    raw = json.loads(path.read_text(encoding="utf-8"))
    cfg = json.loads((GOLDEN / sid / "cfg.json").read_text(encoding="utf-8"))
    assert raw["ok"] and raw["bits"]["tb_hex_list"] == [cfg["si"][0]["tb_hex"]]
    decoded, _ = rrc.decode("BCCH-DL-SCH-Message", bytes.fromhex(raw["bits"]["tb_hex_list"][0]))
    assert decoded == samples.bcch_dl_sch_si([("sib19-v1700", samples.sib19(**mockraw.SIB19_SAMPLE))])
    # SI 창: Python이 계산한 창(SFN mod 8 = 2) 안에서 찾았다
    assert raw["measurements"]["messages"][0]["sfn"] % 8 == 2
    r = run_all(sid)["sib19"]
    val = {v.key: getattr(v.value, "root", v.value) for v in r.values}
    s = mockraw.SIB19_SAMPLE
    assert (val["epoch_sfn"], val["k_offset"]) == (s["epoch_sfn"], s["k_offset"])
    assert val["pos_x"] == pytest.approx(s["position"][0] * 1.3 / 1000, abs=1e-3) and val["ta_common"] == pytest.approx(s["ta_common"] * 4.072e-3, abs=1e-5)
