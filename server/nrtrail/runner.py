"""단계 하나를 실행한다: 입력 준비 → 엔진 → 조립(StageResult).

여기서 "앞 단계가 성공해야 다음 단계가 열린다"와 범위 제한(실시간 장비 입력은 방송 정보까지만)을 지킨다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .contracts_gen import StageResult
from .engines.base import Engine, Progress, failed
from .nr import bands
from .pipeline import Pipeline
from .stages import mib, scan, sib1, sib19, ssb
from .stages.base import Ctx

ASSEMBLERS = {"scan": scan.assemble, "ssb": ssb.assemble, "mib": mib.assemble, "sib1": sib1.assemble, "sib19": sib19.assemble}

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
        scale = float(user.get("cfo_search_scale", 1))
        return {"ss_ref_hz": cell["ss_ref_hz"], "ssb_scs_khz": cell["ssb_scs_khz"], "pattern": cell["pattern"], "lmax": cell["lmax"],
                "cfo_search_hz": search * scale, "pci_hint": cell.get("pci")} | user
    if stage == "mib":
        return {"lmax": cell["lmax"]} | user
    return dict(user)


def precheck(stage: str, state: RunState) -> dict[str, Any] | None:
    """엔진을 부르기 전에 답이 정해지는 경우."""
    if stage == "sib1" and not state.raws.get("mib", {}).get("resolved", {}).get("sib1_present", True):
        return failed(stage, "NO_PDCCH", "k_SSB > 23")
    if stage == "sib19":
        ni = state.results["sib1"].next_inputs
        if not ni.get("has_sib19"):
            return failed(stage, "NOT_SCHEDULED")
    return None


def run_stage(engine: Engine, pipeline: Pipeline, stage_id: str, state: RunState, user_params: dict[str, Any] | None = None,
              progress: Progress = lambda p, key: None) -> StageResult:
    stage = pipeline.stage(stage_id)
    check_allowed(stage_id, state)
    for req in stage.requires:
        if not state.done(req):
            raise StageLocked(stage_id)
    # 이 단계를 다시 돌리면 뒤 단계의 결과는 더 이상 맞지 않는다.
    for later in pipeline.order[pipeline.order.index(stage_id):]:
        state.raws.pop(later, None)
        state.results.pop(later, None)
    if stage_id == "ssb" and not state.cell:
        select_cell(state, state.results["scan"].next_inputs["selected_gscn"])

    params = build_params(stage_id, state, user_params or {})
    raw = precheck(stage_id, state)
    if raw is None:
        raw = engine.run_raw(stage_id, {"capture": {"meta": state.capture.get("meta"), "data": state.capture.get("data")},
                                        "params": params, "prior": state.raws, "scenario": state.scenario}, progress)
    ctx = Ctx(capture=state.capture, cell=state.cell, prior=state.raws, params=params, settings=state.settings)
    result = ASSEMBLERS[stage_id](stage, raw, ctx)
    state.results[stage_id] = result
    if result.status != "fail":
        state.raws[stage_id] = raw
    return result
