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
    assert val["sfn"] == truth["mib"]["sfn"] and val["k_ssb"] == truth["mib"]["k_ssb"]
    assert val["pdcch_config_sib1"] == truth["mib"]["pdcch_config_sib1"]
    assert val["dmrs_typea_pos"] == truth["mib"]["dmrs_typea_pos"]
    assert next(v.value.root for v in r["ssb"].values if v.key == "pci") == truth["ncellid"]
    # 프레임 시작 위치: 합성기의 timing_offset_samples(프레임이 시작하는 캡처 샘플)와 2샘플 안에서 같다
    frame_len = 0.010 * truth["carrier"]["sample_rate_hz"]
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
