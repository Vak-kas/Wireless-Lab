"""세션: 입력 소스 하나를 따라가는 한 번의 작업. 실행 데이터는 sessions/<id>/ 아래에 둔다.

    sessions/<id>/session.json           입력 소스, 엔진, 생성 시각, 단계별 현재 실행 번호
    sessions/<id>/captures/<n>.sigmf-*   IQ (장비 수신·기록 시)
    sessions/<id>/results/<stage>-<n>.json      StageResult
    sessions/<id>/results/<stage>-<n>.raw.json  엔진 원시 결과 (다음 단계 입력, 재실행 비교용)
"""

from __future__ import annotations

import json
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import sigmf
from .contracts_gen import StageResult
from .paths import GOLDEN, PIPELINE, sessions_dir
from .pipeline import Pipeline
from .runner import RunState

DEFAULT_SETTINGS: dict[str, Any] = {
    "location": {"lat": 36.35, "lon": 127.38, "alt_m": 60.0},
    "cfo_search_hz": 15_000,
    "cfo_search_ntn_hz": 50_000,
    "thresholds": {
        "doppler_residual_hz": 5_000, "ta_mismatch_us": 50, "altitude_min_km": 200, "altitude_max_km": 40_000,
        "speed_tolerance_pct": 10, "jump_position_km": 5,
    },
    "device": {},
    "lang": "ko",
}


class SessionError(ValueError):
    """사용자에게 그대로 보여줄 수 있는 문구를 담는다."""


def load_scenarios() -> list[dict[str, Any]]:
    data: dict[str, Any] = json.loads((PIPELINE / "scenarios.json").read_text(encoding="utf-8"))
    scenarios: list[dict[str, Any]] = data["scenarios"]
    return scenarios


def load_settings() -> dict[str, Any]:
    path = sessions_dir() / "settings.json"
    saved: dict[str, Any] = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    merged = {**DEFAULT_SETTINGS, **saved}
    merged["thresholds"] = {**DEFAULT_SETTINGS["thresholds"], **saved.get("thresholds", {})}
    merged["location"] = {**DEFAULT_SETTINGS["location"], **saved.get("location", {})}
    return merged


def save_settings(settings: dict[str, Any]) -> dict[str, Any]:
    path = sessions_dir() / "settings.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(settings, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return load_settings()


class Session:
    def __init__(self, sid: str, name: str, created_at: str, source: dict[str, Any], engine: str, practice: bool,
                 state: RunState, runs: dict[str, int] | None = None, current: dict[str, int] | None = None):
        self.id = sid
        self.name = name
        self.created_at = created_at
        self.source = source
        self.engine = engine
        self.practice = practice
        self.state = state
        self.runs: dict[str, int] = runs or {}          # 단계별 실행 횟수
        self.current: dict[str, int] = current or {}    # 지금 유효한 결과의 실행 번호
        self.job: tuple[str, str] | None = None         # (job_id, stage)
        self.recording = False
        self.tracking = False

    @property
    def dir(self) -> Path:
        return sessions_dir() / self.id

    # --- 화면용 ---
    def public(self, pipeline: Pipeline) -> dict[str, Any]:
        stages = []
        for s in pipeline.stages:
            result = self.state.results.get(s.id)
            ready = all(self.state.done(r) for r in s.requires)
            if self.job and self.job[1] == s.id:
                st = "running"
            elif result is not None and result.status != "fail":
                st = "done"
            else:
                st = "next" if ready else "locked"
            entry: dict[str, Any] = {"stage": s.id, "state": st, "runs": self.runs.get(s.id, 0)}
            if result is not None:
                entry["last_status"] = result.status
            if st == "locked":
                entry["locked_reason"] = s.data.get("locked_reason", "")
            if st == "running" and self.job:
                entry["job_id"] = self.job[0]
            stages.append(entry)
        out: dict[str, Any] = {
            "id": self.id, "name": self.name, "created_at": self.created_at, "source": self.source, "engine": self.engine,
            "stages": stages, "practice": self.practice, "recording": self.recording, "tracking": self.tracking,
        }
        if self.state.cell:
            out["selected_cell"] = {"gscn": self.state.cell.get("gscn"), "pci": self.state.cell.get("pci")}
        return out

    # --- 저장 ---
    def save(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        data = {"id": self.id, "name": self.name, "created_at": self.created_at, "source": self.source, "engine": self.engine,
                "practice": self.practice, "runs": self.runs, "current": self.current, "cell": self.state.cell,
                "capture": self.state.capture, "scenario": self.state.scenario, "band": self.state.band, "testbed": self.state.testbed}
        (self.dir / "session.json").write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def result_path(self, stage: str, n: int, raw: bool = False) -> Path:
        return self.dir / "results" / f"{stage}-{n}{'.raw' if raw else ''}.json"

    def record_result(self, stage: str, pipeline: Pipeline) -> StageResult:
        """run_stage 가 state 에 넣어 둔 결과를 디스크에 남기고, 무효가 된 뒤 단계의 현재 번호를 지운다."""
        n = self.runs.get(stage, 0) + 1
        self.runs[stage] = n
        for later in pipeline.order[pipeline.order.index(stage):]:
            self.current.pop(later, None)
        result = self.state.results[stage]
        self.current[stage] = n
        path = self.result_path(stage, n)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(result.model_dump(mode="json", exclude_none=True), ensure_ascii=False) + "\n", encoding="utf-8")
        raw = self.state.raws.get(stage)
        if raw is not None:
            self.result_path(stage, n, raw=True).write_text(json.dumps(raw, ensure_ascii=False) + "\n", encoding="utf-8")
        self.save()
        return result

    def load_result(self, stage: str, n: int | None = None) -> StageResult | None:
        if n is None:
            return self.state.results.get(stage)
        path = self.result_path(stage, n)
        return StageResult.model_validate_json(path.read_text(encoding="utf-8")) if path.exists() else None


def _capture_for(source: dict[str, Any]) -> tuple[dict[str, Any], str | None, str | None, bool]:
    """입력 소스 → (capture 정보, 시나리오 id, 대역, testbed 여부)."""
    kind = source.get("kind")
    if kind == "synthetic":
        sc = next((s for s in load_scenarios() if s["id"] == source.get("scenario")), None)
        if sc is None:
            raise SessionError("없는 연습 시나리오입니다.")
        capture: dict[str, Any] = {"center_freq_hz": sc["center_freq_hz"], "sample_rate_hz": sc["sample_rate_hz"], "source_kind": "synthetic"}
        meta = GOLDEN / sc["id"] / "capture.sigmf-meta"
        if meta.exists():  # MATLAB 엔진으로 같은 합성 파형을 실제 처리할 때 쓴다
            cap = sigmf.read_meta(meta)
            capture |= {"meta": str(cap.meta_path), "data": str(cap.data_path), "center_freq_hz": cap.center_freq_hz,
                        "sample_rate_hz": cap.sample_rate_hz}
        return capture, sc["id"], sc.get("band"), False
    if kind == "file":
        try:
            cap = sigmf.read_meta(source.get("path") or "")
        except sigmf.SigmfError as e:
            raise SessionError(str(e)) from e
        testbed = bool(source.get("testbed")) or cap.testbed
        return ({"center_freq_hz": cap.center_freq_hz, "sample_rate_hz": cap.sample_rate_hz, "source_kind": "file",
                 "meta": str(cap.meta_path), "data": str(cap.data_path), "num_samples": cap.num_samples},
                None, source.get("band"), testbed)
    if kind == "device":
        return ({"center_freq_hz": source.get("center_freq_hz"), "sample_rate_hz": source.get("sample_rate_hz"),
                 "source_kind": "device", "device": source.get("device")}, None, source.get("band"), False)
    raise SessionError("입력 소스 종류가 올바르지 않습니다.")


class SessionStore:
    def __init__(self, pipeline: Pipeline):
        self.pipeline = pipeline
        self.sessions: dict[str, Session] = {}
        self._load_all()

    def _load_all(self) -> None:
        root = sessions_dir()
        if not root.exists():
            return
        for path in sorted(root.glob("*/session.json")):
            try:
                self._load(path)
            except (OSError, ValueError, KeyError):
                continue  # 깨진 세션 폴더는 건너뛴다(지우지 않는다)

    def _load(self, path: Path) -> None:
        d = json.loads(path.read_text(encoding="utf-8"))
        state = RunState(capture=d["capture"], scenario=d.get("scenario"), band=d.get("band"), testbed=d.get("testbed", False),
                         cell=d.get("cell") or {}, settings=load_settings())
        s = Session(d["id"], d["name"], d["created_at"], d["source"], d["engine"], d.get("practice", False), state,
                    runs=d.get("runs", {}), current=d.get("current", {}))
        for stage, n in s.current.items():
            rp = s.result_path(stage, n)
            if rp.exists():
                state.results[stage] = StageResult.model_validate_json(rp.read_text(encoding="utf-8"))
            raw = s.result_path(stage, n, raw=True)
            if raw.exists():
                state.raws[stage] = json.loads(raw.read_text(encoding="utf-8"))
        self.sessions[s.id] = s

    def create(self, source: dict[str, Any], engine: str, name: str | None = None, practice: bool | None = None) -> Session:
        capture, scenario, band, testbed = _capture_for(source)
        sid = uuid.uuid4().hex[:10]
        title = name or (next((s["title"] for s in load_scenarios() if s["id"] == scenario), None) if scenario else None) \
            or (Path(source["path"]).name if source.get("path") else source.get("device_label") or source.get("kind", "session"))
        state = RunState(capture=capture, scenario=scenario, band=band, testbed=testbed, settings=load_settings())
        source = {**source, "testbed": testbed} if source.get("kind") == "file" else source
        s = Session(sid, str(title), datetime.now(timezone.utc).isoformat(timespec="seconds"), source, engine,
                    source.get("kind") == "synthetic" if practice is None else practice, state)
        s.save()
        self.sessions[sid] = s
        return s

    def get(self, sid: str) -> Session:
        return self.sessions[sid]

    def list(self) -> list[Session]:
        return sorted(self.sessions.values(), key=lambda s: s.created_at, reverse=True)

    def delete(self, sid: str) -> None:
        s = self.sessions.pop(sid)
        # 세션 폴더만 지운다. 폴더가 sessions 루트 바로 아래인지 한 번 더 확인한다.
        if s.dir.parent == sessions_dir() and s.dir.name == sid:
            shutil.rmtree(s.dir, ignore_errors=True)
