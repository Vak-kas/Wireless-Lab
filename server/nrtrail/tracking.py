"""추적 모드와 기록(SPEC 8절).

추적: 선택한 셀에 대해 단계 1~4(SSB → MIB → SIB1 → SIB19)와 NTN 계산을 일정 간격으로 되풀이하고 시계열로 남긴다.
  sessions/<id>/track/timeseries.csv   한 줄 = 한 번 반복
  sessions/<id>/track/changes.json     SIB19 값이 바뀐 기록(이전 값 → 새 값)
저장 파일·합성 신호는 같은 캡처를 다시 읽으므로 측정값은 매번 같다(결정적 처리). 그때는 지난 시간만큼
궤도를 전파해 계산값(TA, 도플러)만 변한다. 실시간 장비 입력은 반복마다 새로 수신한다(capture_hook).

기록: 지금 캡처를 세션 폴더(captures/<n>.sigmf-*)로 복사해 세션만으로 다시 실행할 수 있게 한다.
"""

from __future__ import annotations

import asyncio
import csv
import io
import json
import time
from collections.abc import Callable
from copy import copy
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from . import acquire, sigmf
from .nr import ntn as ntn_math
from .pipeline import Pipeline
from .runner import RunState, run_stage
from .sessions import Session, SessionStore
from .stages import ntn as ntn_stage
from .stages.sib19 import POS_UNIT_M

TRACK_STAGES = ["ssb", "mib", "sib1", "sib19"]
SERIES = ["cfo_hz", "timing_drift_samples", "rsrp_dbfs", "sinr_db", "doppler_pred_hz", "doppler_residual_hz",
          "ta_total_ms", "range_km", "elevation_deg", "validity_left_s"]
SIB19_FIELDS = ["epoch_sfn", "epoch_subframe", "validity_s", "k_offset", "ta_common", "ta_drift", "ta_drift_variant",
                "pos_x", "pos_y", "pos_z", "vel_x", "vel_y", "vel_z"]
MIN_INTERVAL_S = 0.2


class TrackStart(BaseModel):
    interval_s: float = Field(default=5.0, ge=MIN_INTERVAL_S, le=3600)
    max_points: int | None = Field(default=None, ge=1, le=100_000)


class RecordBody(BaseModel):
    on: bool


def sib19_fields(next_inputs: dict[str, Any]) -> dict[str, Any]:
    """SIB19 결과에서 변경 감시 대상 원시값을 뽑는다."""
    eph = next_inputs.get("ephemeris") or {}
    ta = next_inputs.get("ta_info") or {}
    epoch = next_inputs.get("epoch") or {}
    out: dict[str, Any] = {"epoch_sfn": epoch.get("sfn-r17"), "epoch_subframe": epoch.get("subFrameNR-r17"),
                           "validity_s": next_inputs.get("validity_s"), "k_offset": next_inputs.get("k_offset"),
                           "ta_common": ta.get("ta_common"), "ta_drift": ta.get("ta_drift"), "ta_drift_variant": ta.get("ta_drift_variant")}
    if eph.get("format") == "positionVelocity":
        for a, p, v in zip("xyz", eph["pos_m"], eph["vel_mps"], strict=True):
            out[f"pos_{a}"] = round(p / POS_UNIT_M)
            out[f"vel_{a}"] = round(v / 0.06)
    return out


def position_jump_km(prev: dict[str, Any], new: dict[str, Any]) -> float | None:
    """이전 SIB19의 궤도를 새 epochTime까지 전파한 위치와 새 SIB19 위치의 차(km). 궤도 운동으로 설명되지 않는 점프를 찾는다."""
    try:
        p0 = tuple(prev[f"pos_{a}"] * POS_UNIT_M for a in "xyz")
        v0 = tuple(prev[f"vel_{a}"] * 0.06 for a in "xyz")
        p1 = tuple(new[f"pos_{a}"] * POS_UNIT_M for a in "xyz")
        dt = ntn_math.epoch_delta_s(new["epoch_sfn"], prev["epoch_sfn"], prev["epoch_subframe"]) + new["epoch_subframe"] * 0.001
    except (KeyError, TypeError):
        return None
    predicted, _ = ntn_math.propagate(p0, v0, dt)  # type: ignore[arg-type]
    return ntn_math.norm(tuple(a - b for a, b in zip(p1, predicted, strict=True))) / 1e3  # type: ignore[arg-type]


class Tracker:
    """세션 하나의 추적 상태."""

    def __init__(self, session: Session, pipeline: Pipeline, engine: Any):
        self.session = session
        self.pipeline = pipeline
        self.engine = engine
        self.interval_s = 5.0
        self.points: list[dict[str, Any]] = []
        self.changes: list[dict[str, Any]] = []
        self.task: asyncio.Task[None] | None = None
        self.t0 = 0.0
        self.base_timing: float | None = None
        self.last_fields: dict[str, Any] | None = None
        self.capture_hook: Callable[[RunState, int], None] | None = None  # 장비 입력: 반복마다 새로 수신 (M8)
        self.load()

    @property
    def dir(self) -> Path:
        return self.session.dir / "track"

    @property
    def running(self) -> bool:
        return self.task is not None and not self.task.done()

    # --- 저장 ---
    def load(self) -> None:
        path = self.dir / "timeseries.csv"
        if path.exists():
            with path.open(newline="", encoding="utf-8") as f:
                self.points = [{k: (float(v) if v != "" else None) for k, v in row.items()} for row in csv.DictReader(f)]
        cpath = self.dir / "changes.json"
        if cpath.exists():
            self.changes = json.loads(cpath.read_text(encoding="utf-8"))

    def save(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / "timeseries.csv").write_text(self.csv_text(), encoding="utf-8")
        (self.dir / "changes.json").write_text(json.dumps(self.changes, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    def csv_text(self) -> str:
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=["t_s", *SERIES], lineterminator="\n")
        w.writeheader()
        for p in self.points:
            w.writerow({k: ("" if p.get(k) is None else p[k]) for k in ["t_s", *SERIES]})
        return buf.getvalue()

    # --- 한 번 반복 ---
    def iterate(self, t_s: float, index: int) -> dict[str, Any]:
        """표시 중인 결과를 건드리지 않도록 상태의 사본에서 단계 1~4를 다시 돌린다."""
        src = self.session.state
        state = copy(src)
        state.raws, state.results = dict(src.raws), dict(src.results)
        if self.capture_hook is not None:
            self.capture_hook(state, index)
        point: dict[str, Any] = {"t_s": round(t_s, 3), **dict.fromkeys(SERIES)}
        for stage in TRACK_STAGES:
            if run_stage(self.engine, self.pipeline, stage, state).status == "fail":
                return point
        m = state.raws["ssb"]["measurements"]
        if self.base_timing is None:
            self.base_timing = m["timing_offset_samples"]
        point |= {"cfo_hz": m["cfo_hz"], "timing_drift_samples": m["timing_offset_samples"] - self.base_timing,
                  "rsrp_dbfs": m["rsrp_dbfs"], "sinr_db": m["sinr_db"]}
        loc = state.settings.get("location") or ntn_stage.DEFAULT_LOCATION
        replay = self.capture_hook is None
        result = ntn_stage.compute(SimpleNamespace(state=state), loc["lat"], loc["lon"], loc["alt_m"], t_s if replay else 0.0)
        if result.status != "fail":
            ni = result.next_inputs
            point |= {"doppler_pred_hz": round(ni["doppler_hz"], 2), "ta_total_ms": round(ni["ta_total_s"] * 1e3, 5),
                      "range_km": round(ni["range_m"] / 1e3, 3), "elevation_deg": round(ni["elevation_deg"], 3),
                      "doppler_residual_hz": None if ni["residual_hz"] is None else round(ni["residual_hz"], 2),
                      "validity_left_s": None if ni["validity_left_s"] is None else round(ni["validity_left_s"], 2)}
        self.note_changes(t_s, sib19_fields(state.results["sib19"].next_inputs))
        return point

    def note_changes(self, t_s: float, fields: dict[str, Any]) -> None:
        prev = self.last_fields
        self.last_fields = fields
        if prev is None:
            return
        labels = self.pipeline.stage("track").data["fields"]
        changed = [k for k in SIB19_FIELDS if prev.get(k) != fields.get(k)]
        jump = position_jump_km(prev, fields) if changed else None
        limit = float(self.session.state.settings.get("thresholds", {}).get("jump_position_km", 5))
        for k in changed:
            self.changes.append({"t_s": round(t_s, 3), "field": k, "label": labels.get(k, k), "before": str(prev.get(k)),
                                 "after": str(fields.get(k)),
                                 "anomaly": bool(jump is not None and jump > limit and k.startswith(("pos_", "vel_")))})

    async def loop(self, max_points: int | None, publish: Callable[[dict[str, Any]], None]) -> None:
        i = 0
        try:
            while max_points is None or i < max_points:
                t_s = i * self.interval_s if self.capture_hook is None else time.monotonic() - self.t0
                point = await asyncio.to_thread(self.iterate, t_s, i)
                self.points.append(point)
                self.save()
                publish({"type": "job.progress", "job_id": "track", "session_id": self.session.id, "stage": "track",
                         "ts": time.time(), "progress": 0.0, "message": str(len(self.points))})
                i += 1
                await asyncio.sleep(self.interval_s)
        finally:
            self.session.tracking = False

    def data(self) -> dict[str, Any]:
        meta = self.pipeline.stage("track").data["values"]
        return {"running": self.running, "interval_s": self.interval_s,
                "series": [{"key": k, "label": meta[k]["label"], "unit": meta[k]["unit"]} for k in SERIES],
                "points": self.points, "replay": self.capture_hook is None}


def record_capture(session: Session) -> Path:
    """지금 캡처를 세션 폴더로 복사한다. 이미 세션 폴더 안이면 그대로 둔다."""
    cap = session.state.capture
    if not cap.get("meta"):
        raise HTTPException(409, "기록할 수신 데이터가 없습니다.")
    src = sigmf.read_meta(cap["meta"])
    dest_dir = session.dir / "captures"
    if src.meta_path.parent == dest_dir:
        return src.meta_path
    dest_dir.mkdir(parents=True, exist_ok=True)
    n = len(list(dest_dir.glob("*.sigmf-meta")))
    meta_path = dest_dir / f"{n}.sigmf-meta"
    data_path = sigmf.data_path_for(meta_path)
    # 큰 파일도 메모리에 올리지 않도록 조각으로 복사한다
    with src.data_path.open("rb") as fi, data_path.open("wb") as fo:
        while chunk := fi.read(8 << 20):
            fo.write(chunk)
    meta_path.write_bytes(src.meta_path.read_bytes())
    return meta_path


def register(app: FastAPI, store: SessionStore, pipeline: Pipeline, hub: Any, session: Callable[[str], Session]) -> None:
    trackers: dict[str, Tracker] = {}
    app.state.trackers = trackers

    def tracker(sid: str) -> Tracker:
        s = session(sid)
        if sid not in trackers:
            trackers[sid] = Tracker(s, pipeline, app.state.engines[s.engine])
            if acquire.is_device(s):
                def hook(state: RunState, index: int, s: Session = s) -> None:
                    acquire.acquire(s, index)
                    state.capture = s.state.capture

                trackers[sid].capture_hook = hook
        return trackers[sid]

    @app.get("/api/sessions/{sid}/track/timeseries")
    def timeseries(sid: str) -> dict[str, Any]:
        return tracker(sid).data()

    @app.get("/api/sessions/{sid}/track/timeseries.csv")
    def timeseries_csv(sid: str) -> PlainTextResponse:
        return PlainTextResponse(tracker(sid).csv_text(), media_type="text/csv",
                                 headers={"Content-Disposition": f'attachment; filename="nrtrail-{sid}-track.csv"'})

    @app.get("/api/sessions/{sid}/track/changes")
    def changes(sid: str) -> list[dict[str, Any]]:
        return tracker(sid).changes

    @app.post("/api/sessions/{sid}/track/start")
    async def start(sid: str, body: TrackStart) -> dict[str, Any]:
        t = tracker(sid)
        if not t.session.state.done("sib19"):
            raise HTTPException(409, pipeline.stage("track").data.get("locked_reason") or "SIB19까지 읽은 뒤에 추적할 수 있습니다.")
        if t.running:
            raise HTTPException(409, "이미 추적 중입니다.")
        t.interval_s, t.t0 = body.interval_s, time.monotonic()
        t.points, t.changes, t.base_timing, t.last_fields = [], [], None, None
        t.session.tracking = True
        t.task = asyncio.create_task(t.loop(body.max_points, lambda e: hub.publish(sid, e)))
        return t.data()

    @app.post("/api/sessions/{sid}/track/stop")
    async def stop(sid: str) -> dict[str, Any]:
        t = tracker(sid)
        if t.task is not None:
            t.task.cancel()
            try:
                await t.task
            except asyncio.CancelledError:
                pass
            t.task = None
        t.session.tracking = False
        return t.data()

    @app.post("/api/sessions/{sid}/record")
    def record(sid: str, body: RecordBody) -> dict[str, Any]:
        s = session(sid)
        if body.on:
            record_capture(s)
        s.recording = body.on
        s.save()
        return s.public(pipeline)
