# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 서민재
"""HTTP API and static page of the local web UI.

Read-only for now: devices and recorded runs. The server is meant to be bound
to 127.0.0.1; it has no authentication.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

from wls import __version__
from wls.core.devices import DeviceManager, DeviceProvider
from wls.core.runs import list_runs, load_run, run_path

_STATIC = Path(__file__).parent / "static"


def create_app(
    runs_dir: str | Path, providers: Callable[[], Iterable[DeviceProvider]]
) -> FastAPI:
    app = FastAPI(title="Wireless Lab", version=__version__, docs_url=None, redoc_url=None)

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
        return {"runs": [asdict(r) for r in list_runs(runs_dir)]}

    @app.get("/api/runs/{name}")
    def run(name: str) -> dict:
        path = run_path(runs_dir, name)
        if path is None:
            raise HTTPException(404, "no such run")
        detail = load_run(path)
        return {
            **asdict(detail.info),
            "duration": detail.duration,
            "series": [asdict(s) for s in detail.series],
            "events": [asdict(e) for e in detail.events],
        }

    return app
