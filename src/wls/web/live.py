# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 서민재
"""One measurement at a time, started from the web UI and streamed live."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

from wls.core.interfaces import Event, Sample
from wls.core.state_machine import State
from wls.core.storage import SqliteRecorder
from wls.measurements import (
    Plan,
    PlanError,
    plan_bt_track,
    plan_demo,
    plan_diagnose,
    plan_ping,
    plan_speed,
    plan_wifi,
    run_plan,
    wifi_backend,
)

MAX_DURATION = 3600.0
_ERROR_KINDS = ("probe_error", "probe_stalled", "internal_error", "stop_timeout")


class Busy(RuntimeError):
    pass


def kinds() -> list[dict]:
    """What the UI can start, with defaults and availability on this computer."""
    wifi = wifi_backend() is not None
    no_wifi = "" if wifi else "Wi-Fi measurement is not supported on this system yet"
    return [
        {"kind": "diagnose", "label": "Diagnose connection", "target": "1.1.1.1",
         "duration": 10, "available": True, "reason": ""},
        {"kind": "ping", "label": "Latency (ping)", "target": "1.1.1.1",
         "duration": 30, "available": True, "reason": ""},
        {"kind": "wifi", "label": "Wi-Fi signal", "target": None,
         "duration": 30, "available": wifi, "reason": no_wifi},
        {"kind": "speed", "label": "Speed (uses data)", "target": None,
         "duration": None, "available": True, "reason": ""},
    ]  # fmt: skip


async def make_plan(kind: str, target: str | None, name: str | None = None) -> Plan:
    match kind:
        case "bt-track":
            return plan_bt_track(target or "", name)
        case "diagnose":
            return await plan_diagnose(target or "1.1.1.1")
        case "ping":
            if not target:
                raise PlanError("ping needs an address")
            return plan_ping(target)
        case "wifi":
            return await plan_wifi()
        case "speed":
            return plan_speed()  # default server only: no arbitrary URLs from the browser
        case "demo":
            return plan_demo()
    raise PlanError(f"unknown measurement: {kind}")


class LiveRun:
    """Stores a run and fans its samples and state changes out to listeners."""

    def __init__(self, name: str, plan: Plan, store: SqliteRecorder) -> None:
        self.name = name
        self.kind = plan.kind
        self.title = plan.title
        self.state = State.IDLE.value
        self.finished = False
        self._store = store
        self._start_ns: int | None = None
        self._messages: list[dict] = [
            {"type": "started", "name": name, "kind": plan.kind, "title": plan.title,
             "notes": list(plan.notes)}
        ]  # fmt: skip
        self._listeners: set[asyncio.Queue[dict]] = set()

    def _t(self, t_ns: int) -> float:
        if self._start_ns is None:
            self._start_ns = t_ns
        return (t_ns - self._start_ns) / 1e9

    def publish(self, message: dict) -> None:
        self._messages.append(message)
        for queue in self._listeners:
            queue.put_nowait(message)

    # --- Recorder -----------------------------------------------------------

    def sample(self, sample: Sample) -> None:
        self._store.sample(sample)
        self.publish({"type": "sample", "probe": sample.probe, "t": self._t(sample.t_ns),
                      "values": dict(sample.values)})  # fmt: skip

    def event(self, event: Event) -> None:
        self._store.event(event)
        t = self._t(event.t_ns)
        if event.kind == "state":
            self.state = str(event.data["state"])
            self.publish({"type": "state", "t": t, "state": self.state})
        elif event.kind in _ERROR_KINDS:
            self.publish({"type": "error", "t": t, "message": str(event.data.get("error", ""))})
        for problem in event.data.get("problems", []) or []:
            self.publish({"type": "error", "t": t, "message": str(problem)})

    # --- lifecycle ----------------------------------------------------------

    def finish(self, state: str) -> None:
        self._store.close()
        self.state = state
        self.finished = True
        self.publish({"type": "finished", "name": self.name, "state": state})

    async def stream(self) -> AsyncIterator[dict]:
        """Everything so far, then live messages until the run finishes."""
        queue: asyncio.Queue[dict] = asyncio.Queue()
        backlog = list(self._messages)
        finished = self.finished
        self._listeners.add(queue)
        try:
            for message in backlog:
                yield message
            while not finished:
                message = await queue.get()
                yield message
                finished = message["type"] == "finished"
        finally:
            self._listeners.discard(queue)


class LiveManager:
    def __init__(self, runs_dir: str | Path) -> None:
        self._runs_dir = Path(runs_dir)
        self.current: LiveRun | None = None
        self._stop = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    @property
    def running(self) -> bool:
        return self.current is not None and not self.current.finished

    async def start(
        self, kind: str, target: str | None, duration: float | None, name: str | None = None
    ) -> LiveRun:
        if self.running:
            raise Busy("a measurement is already running")
        plan = await make_plan(kind, target, name)
        if self.running:  # another request won the race while the plan was built
            raise Busy("a measurement is already running")
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        name = f"{stamp}-{plan.kind}.sqlite"
        run = LiveRun(name, plan, SqliteRecorder(self._runs_dir / name))
        self.current = run
        self._stop = asyncio.Event()
        limit = min(duration, MAX_DURATION) if duration else MAX_DURATION
        self._task = asyncio.create_task(self._drive(run, plan, limit, self._stop))
        return run

    async def _drive(self, run: LiveRun, plan: Plan, duration: float, stop: asyncio.Event) -> None:
        state = State.FAILED
        try:
            state = await run_plan(plan, run, duration=duration, stop=stop)
        except Exception as exc:  # never leave a run unfinished
            run.publish({"type": "error", "t": 0.0, "message": repr(exc)})
        finally:
            run.finish(state.value)

    def stop(self) -> None:
        self._stop.set()

    def status(self) -> dict:
        run = self.current
        if run is None:
            return {"running": False, "name": None, "kind": None, "title": None, "state": None}
        return {"running": not run.finished, "name": run.name, "kind": run.kind,
                "title": run.title, "state": run.state}  # fmt: skip

    async def shutdown(self) -> None:
        self.stop()
        if self._task is not None:
            await asyncio.gather(self._task, return_exceptions=True)
