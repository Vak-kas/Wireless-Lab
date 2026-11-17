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
