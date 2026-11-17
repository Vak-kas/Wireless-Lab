"""로컬 서버(FastAPI). 127.0.0.1 에서만 열린다(__main__.py). 수신 전용: 송신 경로를 부르는 코드는 없다.

REST 는 요청·응답, WebSocket(/api/ws/sessions/{id})은 작업 이벤트(JobEvent)를 흘려보낸다.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections import defaultdict
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import acquire
from . import doctor as doctor_mod
from .engines.base import Engine
from .engines.mock import MockEngine
from .paths import DEVICES, WEB_DIST
from .pipeline import load_glossary, load_pipeline
from .runner import StageLocked, StageNotAllowed, run_stage, select_cell
from .sessions import Session, SessionError, SessionStore, load_scenarios, load_settings, save_settings

RUNNABLE_VIEWS = ("ra",)  # 사슬 밖에서 따로 실행하는 단계 (테스트베드 전용)


class CreateSession(BaseModel):
    source: dict[str, Any]
    name: str | None = None
    practice: bool | None = None
    engine: str | None = None


class RunBody(BaseModel):
    params: dict[str, Any] = Field(default_factory=dict)


class SelectCell(BaseModel):
    gscn: int
    pci: int | None = None


class EventHub:
    """세션별 이벤트 구독. 작업 스레드에서도 안전하게 보낼 수 있다."""

    def __init__(self) -> None:
        self.queues: dict[str, set[asyncio.Queue[dict[str, Any]]]] = defaultdict(set)
        self.loop: asyncio.AbstractEventLoop | None = None

    def subscribe(self, sid: str) -> asyncio.Queue[dict[str, Any]]:
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=1000)
        self.queues[sid].add(q)
        return q

    def unsubscribe(self, sid: str, q: asyncio.Queue[dict[str, Any]]) -> None:
        self.queues[sid].discard(q)

    def _put(self, sid: str, event: dict[str, Any]) -> None:
        for q in list(self.queues[sid]):
            if q.full():  # 받는 쪽이 멈췄으면 오래된 진행 이벤트를 버린다
                q.get_nowait()
            q.put_nowait(event)

    def publish(self, sid: str, event: dict[str, Any]) -> None:
        if self.loop is None:
            return
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is self.loop:
            self._put(sid, event)
        else:
            self.loop.call_soon_threadsafe(self._put, sid, event)


def create_app(engines: dict[str, Engine] | None = None, default_engine: str | None = None) -> FastAPI:
    pipeline = load_pipeline()
    engine_map: dict[str, Engine] = engines or {"mock": MockEngine()}
    store = SessionStore(pipeline)
    hub = EventHub()
    tasks: set[asyncio.Task[None]] = set()
    app = FastAPI(title="nrtrail", docs_url=None, redoc_url=None)
    app.state.store = store
    app.state.hub = hub
    app.state.engines = engine_map

    def session(sid: str) -> Session:
        try:
            return store.get(sid)
        except KeyError:
            raise HTTPException(404, "없는 세션입니다.") from None

    def pick_engine(source: dict[str, Any], wanted: str | None) -> str:
        """연습(합성)은 저장된 결과 재생이 기본. 파일·장비는 실제 신호처리 엔진이 필요하다."""
        if wanted:
            if wanted not in engine_map or not engine_map[wanted].available():
                raise HTTPException(400, f"엔진 '{wanted}'을(를) 쓸 수 없습니다.")
            return wanted
        if default_engine and default_engine in engine_map:
            return default_engine
        if source.get("kind") == "synthetic":
            return "mock"
        real = next((n for n, e in engine_map.items() if n != "mock" and e.available()), None)
        if real is None:
            raise HTTPException(400, "저장 파일이나 장비 신호를 처리하려면 MATLAB 엔진이 필요합니다. 설정 · 점검 화면에서 환경을 확인하세요.")
        return real

    # ---------- 읽기 전용 정보 ----------
    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {"ok": True, "engines": {n: e.available() for n, e in engine_map.items()}}

    @app.get("/api/doctor")
    async def doctor(quick: int = 0) -> dict[str, Any]:
        return await asyncio.to_thread(doctor_mod.run_checks, bool(quick))

    @app.get("/api/pipeline")
    def get_pipeline() -> dict[str, Any]:
        return pipeline.public()

    @app.get("/api/glossary")
    def glossary() -> dict[str, Any]:
        return load_glossary()

    @app.get("/api/scenarios")
    def scenarios() -> list[dict[str, Any]]:
        return [{k: s[k] for k in ("id", "title", "description", "band", "ntn") if k in s} | {"recommended": s.get("recommended", False)}
                for s in load_scenarios()]

    @app.get("/api/capabilities")
    def capabilities() -> dict[str, Any]:
        data: dict[str, Any] = json.loads((DEVICES / "capabilities.json").read_text(encoding="utf-8"))
        return data

    @app.get("/api/devices")
    async def devices() -> list[dict[str, Any]]:
        from .devices import list_devices

        return await asyncio.to_thread(list_devices)

    @app.get("/api/settings")
    def get_settings() -> dict[str, Any]:
        return load_settings()

    @app.put("/api/settings")
    def put_settings(body: dict[str, Any]) -> dict[str, Any]:
        loc = body.get("location", {})
        try:
            ok = -90 <= float(loc["lat"]) <= 90 and -180 <= float(loc["lon"]) <= 180 and float(loc["alt_m"]) == float(loc["alt_m"])
        except (KeyError, TypeError, ValueError):
            ok = False
        if not ok:
            raise HTTPException(422, "위치 값이 올바르지 않습니다.")
        saved = save_settings(body)
        for s in store.sessions.values():
            s.state.settings = saved
        return saved

    # ---------- 세션 ----------
    @app.post("/api/sessions")
    def create_session(body: CreateSession) -> dict[str, Any]:
        engine = pick_engine(body.source, body.engine)
        try:
            s = store.create(body.source, engine, body.name, body.practice)
        except SessionError as e:
            raise HTTPException(400, str(e)) from e
        return s.public(pipeline)

    @app.get("/api/sessions")
    def list_sessions() -> list[dict[str, Any]]:
        return [s.public(pipeline) for s in store.list()]

    @app.get("/api/sessions/{sid}")
    def get_session(sid: str) -> dict[str, Any]:
        return session(sid).public(pipeline)

    @app.delete("/api/sessions/{sid}", status_code=204)
    def delete_session(sid: str) -> None:
        s = session(sid)
        if s.job:
            raise HTTPException(409, "실행 중인 작업이 끝난 뒤에 삭제하세요.")
        store.delete(sid)

    @app.get("/api/sessions/{sid}/results/{stage}")
    def get_result(sid: str, stage: str, run: int | None = None) -> dict[str, Any]:
        result = session(sid).load_result(stage, run)
        if result is None:
            raise HTTPException(404, "아직 결과가 없습니다.")
        return result.model_dump(mode="json", exclude_none=True)

    @app.post("/api/sessions/{sid}/select-cell")
    def post_select_cell(sid: str, body: SelectCell) -> dict[str, Any]:
        s = session(sid)
        if "scan" not in s.state.raws:
            raise HTTPException(409, "먼저 스캔을 해야 합니다.")
        if s.job:
            raise HTTPException(409, "실행 중에는 기지국을 바꿀 수 없습니다.")
        before = s.state.cell.get("gscn")
        select_cell(s.state, body.gscn)
        if before != s.state.cell.get("gscn"):  # 다른 기지국을 고르면 뒤 단계 결과는 버린다
            for later in pipeline.order[1:]:
                s.state.raws.pop(later, None)
                s.state.results.pop(later, None)
                s.current.pop(later, None)
        s.save()
        return s.public(pipeline)

    # ---------- 단계 실행 ----------
    async def run_job(s: Session, job_id: str, stage: str, params: dict[str, Any]) -> None:
        base = {"job_id": job_id, "session_id": s.id, "stage": stage}
        stage_def = pipeline.stage(stage)
        texts: dict[str, str] = stage_def.data.get("progress", {})

        def progress(p: float, key: str) -> None:
            hub.publish(s.id, base | {"type": "job.progress", "ts": time.time(), "progress": max(0.0, min(1.0, float(p))),
                                      "message": texts.get(key, "")})

        hub.publish(s.id, base | {"type": "job.started", "ts": time.time()})
        t0 = time.time()
        try:
            chain = [stage]
            if acquire.is_device(s) and (stage == "scan" or acquire.wants_recapture(params)):
                # 새로 받으면 타이밍이 달라지므로 스캔부터 이 단계까지 이어서 다시 돌린다
                acquire.apply_hints(s, params)
                await asyncio.to_thread(acquire.acquire, s)
                chain = pipeline.order[: pipeline.order.index(stage) + 1]
            for st in chain:
                result = await asyncio.to_thread(run_stage, engine_map[s.engine], pipeline, st, s.state,
                                                 params if st == stage else {}, progress)
                s.record_result(st, pipeline)
                if result.status == "fail":
                    break
            payload = result.model_dump(mode="json", exclude_none=True)
            payload["meta"] = {"engine": s.engine, "run_index": s.runs.get(result.stage, 0), "duration_ms": round((time.time() - t0) * 1000, 1),
                               "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
            s.job = None
            hub.publish(s.id, base | {"type": "job.finished", "ts": time.time(), "progress": 1.0, "result": payload})
        except Exception as e:  # noqa: BLE001 — 어떤 오류든 화면에 알리고 세션은 계속 쓸 수 있게 둔다
            s.job = None
            hub.publish(s.id, base | {"type": "job.failed", "ts": time.time(), "error": f"{type(e).__name__}: {e}"})

    @app.post("/api/sessions/{sid}/stages/{stage}/run")
    async def post_run(sid: str, stage: str, body: RunBody) -> dict[str, str]:
        s = session(sid)
        if stage not in pipeline.order and stage not in RUNNABLE_VIEWS:
            raise HTTPException(404, "없는 단계입니다.")
        if s.job:
            raise HTTPException(409, "이미 실행 중인 단계가 있습니다.")
        if not all(s.state.done(r) for r in pipeline.stage(stage).requires):
            raise HTTPException(409, pipeline.stage(stage).data.get("locked_reason") or "앞 단계를 먼저 끝내야 합니다.")
        try:
            from .runner import check_allowed

            check_allowed(stage, s.state)
        except StageNotAllowed:
            raise HTTPException(403, pipeline.stage(stage).data.get("not_allowed") or "이 입력 소스에서는 허용되지 않는 단계입니다.") from None
        except StageLocked:
            raise HTTPException(409, "앞 단계를 먼저 끝내야 합니다.") from None
        if (s.state.capture.get("device_stages") or {}).get(stage) == "no":
            raise HTTPException(403, s.state.capture.get("device_note") or "이 장비로는 할 수 없는 단계입니다.")
        job_id = uuid.uuid4().hex[:8]
        s.job = (job_id, stage)
        task = asyncio.create_task(run_job(s, job_id, stage, body.params))
        tasks.add(task)
        task.add_done_callback(tasks.discard)
        return {"job_id": job_id}

    @app.websocket("/api/ws/sessions/{sid}")
    async def ws_events(ws: WebSocket, sid: str) -> None:
        if sid not in store.sessions:
            await ws.close(code=4404)
            return
        await ws.accept()
        hub.loop = asyncio.get_running_loop()
        q = hub.subscribe(sid)
        try:
            while True:
                await ws.send_json(await q.get())
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            hub.unsubscribe(sid, q)

    @app.on_event("startup")
    async def _startup() -> None:
        hub.loop = asyncio.get_running_loop()

    # ---------- 뒤 마일스톤의 기능은 각 모듈이 붙인다 ----------
    from . import extras

    extras.register(app, store, pipeline, hub, session)

    # ---------- 화면(빌드된 정적 파일) ----------
    if (WEB_DIST / "index.html").exists():
        app.mount("/assets", StaticFiles(directory=WEB_DIST / "assets"), name="assets")

        @app.get("/")
        def index() -> FileResponse:
            return FileResponse(WEB_DIST / "index.html")

    return app
