"""단계 하나를 실행한다: 입력 준비 → 엔진 → 조립(StageResult).

여기서 "앞 단계가 성공해야 다음 단계가 열린다"와 범위 제한(실시간 장비 입력은 방송 정보까지만)을 지킨다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .contracts_gen import StageResult
from .engines.base import Engine, Progress, failed
from .nr import bands, occasions, pdsch, sched
from .pipeline import Pipeline
from .stages import mib, ra, scan, sib1, sib19, ssb
from .stages.base import Ctx

ASSEMBLERS = {"scan": scan.assemble, "ssb": ssb.assemble, "mib": mib.assemble, "sib1": sib1.assemble, "sib19": sib19.assemble,
              "ra": ra.assemble}

# 방송 정보 단계. 실시간 장비 입력으로는 이것만 처리한다 (SPEC 2절).
BROADCAST_STAGES = {"scan", "ssb", "mib", "sib1", "sib19"}


class StageLocked(Exception):
    """선행 단계가 끝나지 않았다."""


class StageNotAllowed(Exception):
    """이 입력 소스로는 허용되지 않는 단계다."""


@dataclass
class RunState:
    """세션 하나의 실행 상태. 서버의 Session이 이것을 감싼다."""

    capture: dict[str, Any]                       # center_freq_hz, sample_rate_hz, source_kind, meta, data, max_sample_rate_hz
    scenario: str | None = None
    band: str | None = None
    testbed: bool = False
    cell: dict[str, Any] = field(default_factory=dict)
    raws: dict[str, dict[str, Any]] = field(default_factory=dict)       # 성공한 단계의 raw
    results: dict[str, StageResult] = field(default_factory=dict)       # 단계별 마지막 결과
    settings: dict[str, Any] = field(default_factory=dict)

    def done(self, stage: str) -> bool:
        r = self.results.get(stage)
        return r is not None and r.status != "fail"


def check_allowed(stage: str, state: RunState) -> None:
    if stage in BROADCAST_STAGES:
        return
    kind = state.capture.get("source_kind")
    if kind == "synthetic" or (kind == "file" and state.testbed):
        return
    raise StageNotAllowed(stage)


def select_cell(state: RunState, gscn: int) -> dict[str, Any]:
    """스캔에서 찾은 셀 가운데 따라갈 것을 고른다."""
    cells = state.raws["scan"]["measurements"]["cells"]
    c = next((c for c in cells if c["gscn"] == gscn), cells[0])
    state.cell = bands.cell_info(c["ss_ref_hz"], c["gscn"], c["ssb_scs_khz"], c["pattern"], state.band) | {"pci": c["pci"]}
    return state.cell


def build_params(stage: str, state: RunState, user: dict[str, Any]) -> dict[str, Any]:
    cap, cell = state.capture, state.cell
    if stage == "scan":
        return {"candidates": bands.scan_candidates(cap["center_freq_hz"], cap["sample_rate_hz"], state.band),
                "cfo_search_hz": state.settings.get("cfo_search_hz", 50_000), "duration_ms": 40,
                "detect_threshold_db": state.settings.get("detect_threshold_db", 8)} | user
    if stage == "ssb":
        search = state.settings.get("cfo_search_ntn_hz", 50_000) if cell.get("ntn") else state.settings.get("cfo_search_hz", 15_000)
        search += float(cap.get("clock_ppm") or 0) * 1e-6 * float(cell["ss_ref_hz"])  # 장비 클럭 오차만큼 넓힌다 (SPEC 16절)
        scale = float(user.get("cfo_search_scale", 1))
        return {"ss_ref_hz": cell["ss_ref_hz"], "ssb_scs_khz": cell["ssb_scs_khz"], "pattern": cell["pattern"], "lmax": cell["lmax"],
                "cfo_search_hz": search * scale, "pci_hint": cell.get("pci")} | user
    if stage == "mib":
        return {"lmax": cell["lmax"]} | user
    if stage in ("sib1", "sib19"):
        return pdcch_params(stage, state) | user
    if stage == "ra":
        out = pdcch_params("ra", state)
        prach = state.results["sib1"].next_inputs.get("prach")
        if prach:
            out["rnti_inputs"] = ra.rnti_inputs(prach, int(state.results["sib1"].next_inputs.get("msg1_scs_khz") or out.get("scs_khz", 15)))
        return out | user
    return dict(user)


def pdcch_params(stage: str, state: RunState) -> dict[str, Any]:
    """SIB1·SI 메시지 수신에 필요한 값을 표준 표에서 풀어 엔진에 넘긴다 (docs/engine-contract.md)."""
    res = state.raws.get("mib", {}).get("resolved", {})
    cs, mon = res.get("coreset0"), res.get("monitoring")
    if not cs or not mon:
        return {}
    cap = state.capture
    fs = float(cap["sample_rate_hz"])
    n_samples = int(cap.get("num_samples") or 0.16 * fs)
    occ = occasions.type0(res["frame_start_sample"], res["sfn_at_frame_start"], n_samples, fs, cs["scs_khz"],
                          mon["slot"], mon["frame_parity"], mon["first_symbol"])
    out: dict[str, Any] = {
        "si_rnti": pdsch.SI_RNTI, "ncellid": res["ncellid"], "scs_khz": cs["scs_khz"], "dmrs_typea_pos": res["dmrs_typea_pos"],
        "coreset0": {"n_rb": cs["n_rb"], "n_sym": cs["n_sym"], "low_hz": cs["low_hz"]},
        "aggregation_levels": [4, 8, 16],
        "tdra_table": [{"row": t.row, "mapping_type": t.mapping_type, "k0": t.k0, "s": t.s, "l": t.length}
                       for t in pdsch.tdra_default_a(res["dmrs_typea_pos"])],
        "mcs_table": [{"index": i, "qm": qm, "rate_x1024": r} for i, (qm, r) in enumerate(pdsch.MCS_TABLE_1)],
    }
    if stage == "sib1":
        return out | {"si_indicator": 0, "occasions": occ}
    ni = state.results["sib1"].next_inputs if "sib1" in state.results else {}
    # SIB1 본문만 DM-RS 기준점이 CORESET0의 가장 낮은 RB다. SI 메시지와 RA 응답의 PDSCH DM-RS는 CRB 0(Point A)이 기준이다
    # (TS 38.211 7.4.1.1.2, 원문 대조함). CORESET0의 RB 0이 몇 번째 CRB인지 넘긴다.
    if ni.get("point_a_hz") is not None:
        out["pdsch_crb_offset_rb"] = round((cs["low_hz"] - ni["point_a_hz"]) / (12 * cs["scs_khz"] * 1000))
    if ni.get("pdsch_tdra_list"):
        # SIB1(Type0)만 항상 기본 표 A. SI 메시지와 RA 응답은 pdsch-ConfigCommon의 목록이 있으면 그것을 쓴다
        out["tdra_table"] = ni["pdsch_tdra_list"]
        out["tdra_source"] = "pdsch-ConfigCommon"
    spaces = ni.get("search_spaces") or {}
    ss_id = int(spaces.get("ra" if stage == "ra" else "other_si") or 0)
    if ss_id:
        # SIB1이 따로 정해 준 공통 탐색 공간 (searchSpaceOtherSystemInformation / ra-SearchSpace). TS 38.213 10.1
        rule = (spaces.get("list") or {}).get(str(ss_id))
        if rule is None or rule["coreset_id"] != 0:
            return out | {"occasions": [], "unsupported": "search space uses a CORESET other than CORESET0" if rule else "search space not found"}
        occ = occasions.search_space(res["frame_start_sample"], res["sfn_at_frame_start"], n_samples, fs, cs["scs_khz"], rule)
        out |= {"search_space": rule, "aggregation_levels": sorted(rule["candidates"]) or out["aggregation_levels"], "candidates": rule["candidates"]}
    if stage == "ra":
        return out | {"occasions": occ}
    win = ni.get("sib19_window")
    if win:
        w = sched.SiWindow(0, win["slot"], win["frame_offset"], win["period_frames"], win["window_slots"], win["slots_per_frame"])
        occ = [o for o in occ if occasions.in_si_window(o, w)]
        out["window"] = win
    return out | {"si_indicator": 1, "occasions": occ}


def precheck(stage: str, state: RunState) -> dict[str, Any] | None:
    """엔진을 부르기 전에 답이 정해지는 경우."""
    if stage == "sib1" and not state.raws.get("mib", {}).get("resolved", {}).get("sib1_present", True):
        return failed(stage, "NO_PDCCH", "k_SSB > 23")
    if stage == "sib19":
        ni = state.results["sib1"].next_inputs
        if not ni.get("has_sib19"):
            return failed(stage, "NOT_SCHEDULED")
    return None


def precheck_params(stage: str, params: dict[str, Any]) -> dict[str, Any] | None:
    """입력을 만든 뒤에 답이 정해지는 경우: 볼 시점이 캡처 안에 없거나, 지원하지 않는 탐색 공간."""
    if stage in ("sib1", "sib19", "ra") and "occasions" in params:
        if params.get("unsupported"):
            return failed(stage, "UNSUPPORTED_SEARCH_SPACE", params["unsupported"])
        if not params["occasions"]:
            return failed(stage, "NO_OCCASION")
    return None


def run_stage(engine: Engine, pipeline: Pipeline, stage_id: str, state: RunState, user_params: dict[str, Any] | None = None,
              progress: Progress = lambda p, key: None) -> StageResult:
    stage = pipeline.stage(stage_id)
    check_allowed(stage_id, state)
    for req in stage.requires:
        if not state.done(req):
            raise StageLocked(stage_id)
    # 이 단계를 다시 돌리면 뒤 단계의 결과는 더 이상 맞지 않는다.
    for later in (pipeline.order[pipeline.order.index(stage_id):] if stage_id in pipeline.order else [stage_id]):
        state.raws.pop(later, None)
        state.results.pop(later, None)
    if stage_id in ("sib1", "mib", "ssb", "scan"):
        state.raws.pop("ra", None)
        state.results.pop("ra", None)
    if stage_id == "ssb" and not state.cell:
        select_cell(state, state.results["scan"].next_inputs["selected_gscn"])

    params = build_params(stage_id, state, user_params or {})
    raw = precheck(stage_id, state) or precheck_params(stage_id, params)
    if raw is None and stage_id == "ra":
        raw = run_ra(engine, state, params, progress)
    if raw is None:
        raw = engine.run_raw(stage_id, {"capture": {"meta": state.capture.get("meta"), "data": state.capture.get("data")},
                                        "params": params, "prior": state.raws, "scenario": state.scenario}, progress)
    ctx = Ctx(capture=state.capture, cell=state.cell, prior=state.raws, params=params, settings=state.settings)
    result = ASSEMBLERS[stage_id](stage, raw, ctx)
    state.results[stage_id] = result
    if result.status != "fail":
        state.raws[stage_id] = raw
    return result


def run_ra(engine: Engine, state: RunState, params: dict[str, Any], progress: Progress) -> dict[str, Any]:
    """RA 관측은 엔진을 두 번 부른다: RA-RNTI로 Msg2(RAR)를 찾고, 거기 적힌 TC-RNTI로 Msg4를 찾는다."""
    from .nr import ra as ra_math

    ids = params.get("rnti_inputs")
    if not ids:
        return {"stage": "ra", "ok": False, "error_code": "NO_PRACH_CONFIG", "msg2": {}, "msg4": {}}
    base = {"capture": {"meta": state.capture.get("meta"), "data": state.capture.get("data")}, "prior": state.raws, "scenario": state.scenario}
    msg2 = engine.run_raw("ra", base | {"params": params | {"rnti": ra_math.ra_rnti(**ids), "dci_format": "ra"}}, progress)
    if "msg2" in msg2:   # 저장된 결과 재생(MockEngine)은 두 메시지를 한 파일에 담고 있다
        return msg2
    msg4: dict[str, Any] = {}
    for hexstr in (msg2.get("bits") or {}).get("tb_hex_list") or []:
        try:
            tc = ra_math.parse_rar_pdu(bytes.fromhex(hexstr)).rars[0].tc_rnti
        except (ValueError, IndexError):
            continue
        msg4 = engine.run_raw("ra", base | {"params": params | {"rnti": tc, "dci_format": "tc"}}, progress)
        break
    return {"stage": "ra", "ok": bool(msg2.get("ok")), "error_code": msg2.get("error_code", ""), "msg2": msg2, "msg4": msg4}
