"""기본 5단계 밖의 기능을 앱에 붙인다: NTN 계산, 추적, 기록, 리포트, 휴대폰.

아직 구현되지 않은 것은 501 과 이유를 돌려준다(화면이 그 문구를 그대로 보여준다).
"""

from __future__ import annotations

import asyncio
import importlib
from collections.abc import Callable
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from .pipeline import Pipeline
from .sessions import Session, SessionStore


class NtnBody(BaseModel):
    lat: float
    lon: float
    alt_m: float = 0.0
    t_offset_s: float = 0.0


class TrackStart(BaseModel):
    interval_s: float = 5.0


class RecordBody(BaseModel):
    on: bool


class SurveyBody(BaseModel):
    device: str
    plan: str
    gain_db: float | None = None
    center_hz: float | None = None
    span_hz: float | None = None
    step_hz: float | None = None


class MonitorBody(BaseModel):
    device: str
    plan: str
    channels: list[str] | None = None
    gain_db: float | None = None
    center_hz: float | None = None
    span_hz: float | None = None
    step_hz: float | None = None
    auto: bool = True
    stat: str = "median_dbfs"


class MonitorPatch(BaseModel):
    auto: bool | None = None
    stat: str | None = None
    baseline: str | None = None      # "save" | "clear"


class BleBody(BaseModel):
    device: str
    channel: int = 37
    gain_db: float | None = None
    seconds: float = 0.25


class SpectrumBody(BaseModel):
    device: str
    center_hz: float | None = None
    bandwidth_hz: float | None = None
    gain_db: float | None = None


def register(app: FastAPI, store: SessionStore, pipeline: Pipeline, hub: Any, session: Callable[[str], Session]) -> None:
    @app.post("/api/sessions/{sid}/ntn")
    def post_ntn(sid: str, body: NtnBody) -> dict[str, Any]:
        s = session(sid)
        if not (-90 <= body.lat <= 90 and -180 <= body.lon <= 180):
            raise HTTPException(422, "위치 값이 올바르지 않습니다.")
        if not s.state.done("sib19"):
            raise HTTPException(409, "위성 계산에는 SIB19가 필요합니다.")
        try:
            from .stages import ntn as ntn_stage
        except ImportError:
            raise HTTPException(501, "위성 계산은 아직 구현되지 않았습니다 (M6).") from None
        result = ntn_stage.compute(s, body.lat, body.lon, body.alt_m, body.t_offset_s)
        return result.model_dump(mode="json", exclude_none=True)

    @app.get("/api/phone/cells")
    async def phone_cells() -> dict[str, Any]:
        try:
            from .phone import read_phone
        except ImportError:
            raise HTTPException(501, "휴대폰 연동은 아직 구현되지 않았습니다 (M9).") from None
        return await asyncio.to_thread(read_phone)

    survey_lock = asyncio.Lock()

    @app.get("/api/survey/device")
    async def survey_device(id: str) -> dict[str, Any]:  # noqa: A002 — 주소의 ?id= 와 이름을 맞춘다
        from . import survey
        try:
            return await asyncio.to_thread(survey.describe, id)
        except survey.SurveyError as e:
            raise HTTPException(404, str(e)) from e

    @app.post("/api/survey/run")
    async def survey_run(body: SurveyBody) -> dict[str, Any]:
        from . import survey
        if survey_lock.locked():
            raise HTTPException(409, "이미 재는 중입니다.")
        async with survey_lock:
            try:
                return await asyncio.to_thread(survey.run, body.device, body.plan, gain_db=body.gain_db, center_hz=body.center_hz,
                                               span_hz=body.span_hz, step_hz=body.step_hz)
            except survey.SurveyError as e:
                raise HTTPException(400, str(e)) from e

    @app.post("/api/survey/spectrum")
    async def survey_spectrum(body: SpectrumBody) -> dict[str, Any]:
        from . import survey
        if survey_lock.locked():
            raise HTTPException(409, "이미 재는 중입니다.")
        async with survey_lock:
            try:
                return await asyncio.to_thread(survey.spectrum, body.device, center_hz=body.center_hz, bandwidth_hz=body.bandwidth_hz,
                                               gain_db=body.gain_db)
            except survey.SurveyError as e:
                raise HTTPException(400, str(e)) from e

    from . import monitor as monitor_mod
    monitors = monitor_mod.Registry()

    @app.post("/api/monitor")
    async def monitor_start(body: MonitorBody) -> dict[str, Any]:
        from . import survey
        try:
            m = monitor_mod.Monitor(body.device, body.plan, body.channels, gain_db=body.gain_db, center_hz=body.center_hz,
                                    span_hz=body.span_hz, step_hz=body.step_hz, auto=body.auto, stat=body.stat)
        except survey.SurveyError as e:
            raise HTTPException(400, str(e)) from e
        return monitors.add(m).state()

    @app.post("/api/monitor/{mid}/sweep")
    async def monitor_sweep(mid: str) -> dict[str, Any]:
        from . import survey
        try:
            m = monitors.get(mid)
        except survey.SurveyError as e:
            raise HTTPException(404, str(e)) from e
        if survey_lock.locked():
            raise HTTPException(409, "이미 재는 중입니다.")
        async with survey_lock:
            try:
                return await asyncio.to_thread(m.sweep)
            except survey.SurveyError as e:
                raise HTTPException(400, str(e)) from e

    @app.patch("/api/monitor/{mid}")
    async def monitor_patch(mid: str, body: MonitorPatch) -> dict[str, Any]:
        from . import survey
        try:
            m = monitors.get(mid)
            m.configure(auto=body.auto, stat=body.stat)
        except survey.SurveyError as e:
            raise HTTPException(404, str(e)) from e
        if body.baseline == "save":
            m.save_baseline()
        elif body.baseline == "clear":
            m.clear_baseline()
        return m.state()

    @app.delete("/api/monitor/{mid}", status_code=204)
    async def monitor_stop(mid: str) -> None:
        monitors.remove(mid)

    try:
        from . import usrp_matlab
    except ImportError:
        pass
    else:
        usrp_matlab.install()   # MATLAB 엔진이 있으면 USRP 를 장비 목록에 끼운다

    @app.post("/api/ble/scan")
    async def ble_scan(body: BleBody) -> dict[str, Any]:
        from . import ble
        if survey_lock.locked():
            raise HTTPException(409, "이미 재는 중입니다.")
        async with survey_lock:
            try:
                return await asyncio.to_thread(ble.scan, body.device, body.channel, body.gain_db, body.seconds)
            except ble.BleError as e:
                raise HTTPException(400, str(e)) from e

    try:
        from . import wifi
    except ImportError:
        @app.get("/api/wifi")
        def wifi_unavailable() -> dict[str, Any]:
            return {"available": False}
    else:
        wifi.register(app, survey_lock)

    try:
        from . import tx
    except ImportError:
        @app.get("/api/tx")
        def tx_unavailable() -> dict[str, Any]:
            return {"available": False}
    else:
        tx.register(app, survey_lock)

    try:
        from . import testbed_oai
    except ImportError:
        @app.get("/api/testbed/oai")
        def oai_unavailable() -> dict[str, Any]:
            return {"available": False, "ready": False, "running": False, "reason": ""}
    else:
        testbed_oai.register(app)

    try:
        from . import report
    except ImportError:
        pass
    else:
        report.register(app, store, pipeline, session)

    tracking: Any
    try:
        tracking = importlib.import_module(".tracking", __package__)
    except ImportError:
        tracking = None

    if tracking is not None:
        tracking.register(app, store, pipeline, hub, session)
    else:
        @app.get("/api/sessions/{sid}/track/timeseries")
        def track_empty(sid: str) -> dict[str, Any]:
            session(sid)
            return {"running": False, "interval_s": 5, "series": [], "points": []}

        @app.get("/api/sessions/{sid}/track/changes")
        def track_changes_empty(sid: str) -> list[dict[str, Any]]:
            session(sid)
            return []

        @app.post("/api/sessions/{sid}/track/start")
        def track_start(sid: str, body: TrackStart) -> None:
            raise HTTPException(501, "추적은 아직 구현되지 않았습니다 (M7).")

        @app.post("/api/sessions/{sid}/track/stop")
        def track_stop(sid: str) -> None:
            raise HTTPException(501, "추적은 아직 구현되지 않았습니다 (M7).")

        @app.post("/api/sessions/{sid}/record")
        def record(sid: str, body: RecordBody) -> None:
            raise HTTPException(501, "기록은 아직 구현되지 않았습니다 (M7).")
