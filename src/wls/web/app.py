# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 서민재
"""HTTP API and static page of the local web UI.

The server is meant to be bound to 127.0.0.1 and has no login. Because any
web page the user visits could try to call a local server, requests are
accepted only when addressed to a local host name, and state-changing
requests only from this page itself.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Callable, Iterable
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from wls import __version__
from wls.core.devices import Capability, DeviceManager, DeviceProvider
from wls.analysis.diagnosis import diagnose_samples
from wls.core.runs import list_runs, load_run, run_path
from wls.core.storage import read_run
from wls.measurements import PlanError, pick_wifi, wifi_backend
from wls.probes.wifi_link import WifiBackend
from wls.web.live import Busy, LiveManager, kinds

_STATIC = Path(__file__).parent / "static"
_LOCAL_HOSTS = {"127.0.0.1", "localhost", "[::1]", "testserver"}


class MeasureRequest(BaseModel):
    kind: str = Field(max_length=32)
    target: str | None = Field(default=None, max_length=253)
    duration: float | None = Field(default=None, gt=0, le=3600)


def _hostname(value: str) -> str:
    value = value.split("://", 1)[-1]
    if value.startswith("["):
        return value.split("]", 1)[0] + "]"
    return value.rsplit(":", 1)[0] if ":" in value else value


_AUTO = object()


def create_app(
    runs_dir: str | Path,
    providers: Callable[[], Iterable[DeviceProvider]],
    wifi: WifiBackend | None | object = _AUTO,
) -> FastAPI:
    live = LiveManager(runs_dir)
    backend: WifiBackend | None = wifi_backend() if wifi is _AUTO else wifi  # type: ignore[assignment]
    scan_lock = asyncio.Lock()

    async def wifi_interface() -> tuple[str, str, bool, str] | None:
        """(interface, device name, names available, why not) of the Wi-Fi device, if any."""
        if backend is None:
            return None
        manager = DeviceManager([backend.provider])  # type: ignore[list-item]
        for device in await manager.refresh():
            if device.id.startswith(backend.id_prefix):
                identity = device.support(Capability.WIFI_IDENTITY)
                name = device.id.removeprefix(backend.id_prefix)
                return name, device.name, identity.supported, identity.reason
        return None

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        await live.shutdown()

    app = FastAPI(
        title="Wireless Lab", version=__version__, docs_url=None, redoc_url=None, lifespan=lifespan
    )
    app.state.live = live

    @app.middleware("http")
    async def local_only(request: Request, call_next):
        if _hostname(request.headers.get("host", "")) not in _LOCAL_HOSTS:
            return JSONResponse({"detail": "this server answers local requests only"}, 403)
        origin = request.headers.get("origin")
        if request.method != "GET" and origin is not None:
            if origin.split("://", 1)[-1] != request.headers.get("host", ""):
                return JSONResponse({"detail": "cross-site request refused"}, 403)
        return await call_next(request)

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(_STATIC / "index.html", headers={"Cache-Control": "no-store"})

    @app.get("/api/info")
    def info() -> dict:
        return {"version": __version__, "runs_dir": str(Path(runs_dir).resolve())}

    @app.get("/api/devices")
    async def devices() -> dict:
        manager = DeviceManager(providers())
        found = await manager.refresh()
        return {
            "devices": [
                {
                    "id": d.id,
                    "kind": d.kind.value,
                    "name": d.name,
                    "capabilities": [
                        {"name": c.value, "supported": s.supported, "reason": s.reason}
                        for c, s in d.capabilities.items()
                    ],
                }
                for d in found
            ],
            "provider_errors": manager.provider_errors,
        }

    @app.get("/api/runs")
    def runs() -> dict:
        active = live.current.name if live.running and live.current else None
        return {"runs": [asdict(r) for r in list_runs(runs_dir) if r.name != active]}

    @app.get("/api/runs/{name}")
    def run(name: str) -> dict:
        path = run_path(runs_dir, name)
        if path is None:
            raise HTTPException(404, "no such run")
        detail = load_run(path)
        diagnosis = None
        if detail.info.kind == "diagnose":
            result = diagnose_samples(read_run(path)[1])
            diagnosis = {
                "verdict": result.verdict.value,
                "headline": result.headline,
                "details": list(result.details),
                "wifi_suspect": result.wifi_suspect,
            }
        return {
            **asdict(detail.info),
            "diagnosis": diagnosis,
            "duration": detail.duration,
            "series": [asdict(s) for s in detail.series],
            "events": [asdict(e) for e in detail.events],
        }

    # --- Wi-Fi right now ---------------------------------------------------------

    @app.get("/api/wifi")
    async def wifi_now() -> dict:
        found = await wifi_interface()
        if found is None:
            reason = "no Wi-Fi interface" if backend else "Wi-Fi is not supported on this system yet"
            return {"supported": False, "reason": reason, "link": None}
        interface, name, names, why = found
        reading = backend.link_reader(interface)()  # type: ignore[union-attr]
        return {
            "supported": True,
            "reason": "",
            "interface": interface,
            "name": name,
            "names_available": names,
            "names_reason": why,
            "link": reading.values() if reading else None,
        }

    @app.get("/api/wifi/scan")
    async def wifi_scan() -> dict:
        found = await wifi_interface()
        if found is None:
            raise HTTPException(404, "no Wi-Fi interface to scan with")
        interface = found[0]
        async with scan_lock:  # one scan at a time; a scan takes several seconds
            try:
                entries = await asyncio.to_thread(backend.scanner(interface))  # type: ignore[union-attr]
            except RuntimeError as exc:
                raise HTTPException(503, str(exc)) from None
        return {
            "networks": [asdict(e) for e in entries],
            "names_hidden": bool(entries) and all(e.ssid is None for e in entries),
            "names_reason": found[3],
        }

    # --- live measurement -------------------------------------------------------

    @app.get("/api/kinds")
    def measurement_kinds() -> dict:
        return {"kinds": kinds()}

    @app.get("/api/measure")
    def measure_status() -> dict:
        return live.status()

    @app.post("/api/measure")
    async def measure_start(body: MeasureRequest) -> dict:
        try:
            await live.start(body.kind, body.target, body.duration)
        except Busy as exc:
            raise HTTPException(409, str(exc)) from None
        except PlanError as exc:
            raise HTTPException(400, str(exc)) from None
        return live.status()

    @app.post("/api/measure/stop")
    def measure_stop() -> dict:
        live.stop()
        return live.status()

    @app.get("/api/measure/stream")
    async def measure_stream() -> StreamingResponse:
        current = live.current
        if current is None:
            raise HTTPException(404, "no measurement has been started")

        async def events() -> AsyncIterator[str]:
            async for message in current.stream():
                yield f"data: {json.dumps(message)}\n\n"

        return StreamingResponse(
            events(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
        )

    return app
