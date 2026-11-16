# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 서민재
"""Experiment controller: drives probes and a test action by the state machine.

``submit`` decides a command immediately (accepted, no-op or rejected) and
starts the work in the background. The state only advances when that work
confirms through a signal. All state changes happen on the event loop thread,
one at a time, so commands cannot race each other.

Whatever happens (user stop, error, timeout), a test that touched the device
is reverted before the run ends.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Coroutine, Mapping
from dataclasses import dataclass, field
from typing import Any

from wls.core.devices import DeviceManager
from wls.core.interfaces import Event, Probe, Recorder, Sample, TestAction
from wls.core.state_machine import (
    Command,
    Decision,
    Signal,
    Snapshot,
    State,
    StopReason,
    Verdict,
    apply_signal,
    decide,
)


@dataclass(frozen=True, slots=True)
class Timeouts:
    prepare: float = 10.0
    start_measurement: float = 10.0
    start_test: float = 10.0
    stop_test: float = 10.0
    revert: float = 10.0
    stop: float = 30.0


@dataclass(frozen=True, slots=True)
class ExperimentConfig:
    probes: tuple[Probe, ...]
    test: TestAction | None = None
    recovery_window: float = 5.0  # seconds of RECOVERING before back to MEASURING
    stall_timeout: float | None = 5.0  # no sample for this long = probe stalled
    timeouts: Timeouts = field(default_factory=Timeouts)

    def __post_init__(self) -> None:
        if not self.probes:
            raise ValueError("an experiment needs at least one probe")
        names = [p.name for p in self.probes]
        if len(set(names)) != len(names):
            raise ValueError("probe names must be unique")


class Controller:
    def __init__(
        self,
        devices: DeviceManager,
        recorder: Recorder,
        clock: Callable[[], int] = time.monotonic_ns,
    ) -> None:
        self._devices = devices
        self._rec = recorder
        self._clock = clock
        self._snap = Snapshot()
        self._config: ExperimentConfig | None = None
        self._ops: set[asyncio.Task[None]] = set()  # short operations
        self._probe_tasks: set[asyncio.Task[None]] = set()  # run for the whole measurement
        self._shutdown: asyncio.Task[None] | None = None
        self._test_start: asyncio.Task[None] | None = None
        self._recovery_timer: asyncio.Task[None] | None = None
        self._test_touched = False  # the device may not be in its normal state
        self._changed = asyncio.Event()

    # --- public -------------------------------------------------------------

    @property
    def snapshot(self) -> Snapshot:
        return self._snap

    @property
    def state(self) -> State:
        return self._snap.state

    @property
    def busy(self) -> bool:
        """True while any background work is still alive."""
        shutting_down = self._shutdown is not None and not self._shutdown.done()
        return bool(self._ops or self._probe_tasks or shutting_down)

    def submit(
        self,
        command: Command,
        *,
        config: ExperimentConfig | None = None,
        label: str = "",
    ) -> Decision:
        """Decide a command now; the effect is confirmed later by a state change."""
        if command is Command.PREPARE and config is None:
            raise ValueError("PREPARE needs a config")

        old = self._snap
        no_test = self._config is None or self._config.test is None
        if command is Command.START_TEST and no_test:
            decision = Decision(Verdict.REJECTED, old, "no test is configured")
        else:
            decision = decide(old, command)
        self._log(
            "command",
            command=command.value,
            verdict=decision.verdict.value,
            reason=decision.reason,
        )
        if decision.verdict is not Verdict.ACCEPTED:
            return decision

        if command is Command.PREPARE:
            self._config = config
        elif command is Command.RESET:
            self._config = None

        self._set(decision.snapshot)

        match command:
            case Command.PREPARE | Command.REPEAT:
                self._spawn(self._do_prepare())
            case Command.START_MEASUREMENT:
                self._spawn(self._do_start_measurement())
            case Command.START_TEST:
                self._test_start = self._spawn(self._do_start_test())
            case Command.STOP_TEST:
                self._spawn(self._do_stop_test(self._test_start))
            case Command.MARK:
                self._log("mark", label=label)
        return decision

    async def wait_until(
        self, predicate: Callable[[Snapshot], bool], timeout: float = 5.0
    ) -> Snapshot:
        async with asyncio.timeout(timeout):
            while not predicate(self._snap):
                self._changed.clear()
                await self._changed.wait()
        return self._snap

    async def wait_state(self, *states: State, timeout: float = 5.0) -> Snapshot:
        return await self.wait_until(lambda s: s.state in states, timeout)

    # --- state bookkeeping --------------------------------------------------

    def _log(self, kind: str, **data: object) -> None:
        self._rec.event(Event(self._clock(), kind, data))

    def _set(self, new: Snapshot) -> None:
        old, self._snap = self._snap, new
        if new == old:
            return
        self._log(
            "state",
            state=new.state.value,
            pending=new.pending.value,
            stop_reason=new.stop_reason.value if new.stop_reason else None,
        )
        if old.state is State.RECOVERING and new.state is not State.RECOVERING:
            self._cancel_recovery_timer()
        if new.state is State.STOPPING and old.state is not State.STOPPING:
            self._shutdown = asyncio.get_running_loop().create_task(self._do_shutdown())
            self._shutdown.add_done_callback(self._on_shutdown_done)
        self._changed.set()

    def _signal(self, signal: Signal, **data: object) -> None:
        new, applied = apply_signal(self._snap, signal)
        self._log("signal", signal=signal.value, applied=applied, **data)
        if not applied:
            return
        self._set(new)
        if signal in (Signal.TEST_ENDED, Signal.TEST_FAILED):
            self._test_start = None
            self._arm_recovery_timer()

    # --- task plumbing ------------------------------------------------------

    def _spawn(
        self,
        coro: Coroutine[Any, Any, None],
        group: set[asyncio.Task[None]] | None = None,
    ) -> asyncio.Task[None]:
        group = self._ops if group is None else group
        task = asyncio.get_running_loop().create_task(coro)
        group.add(task)

        def done(t: asyncio.Task[None]) -> None:
            group.discard(t)
            if not t.cancelled() and t.exception() is not None:
                self._log("internal_error", error=repr(t.exception()))
                self._signal(Signal.FATAL_ERROR)

        task.add_done_callback(done)
        return task

    def _on_shutdown_done(self, task: asyncio.Task[None]) -> None:
        if not task.cancelled() and task.exception() is not None:
            self._log("internal_error", error=repr(task.exception()))
            self._signal(Signal.STOP_FAILED)

    @staticmethod
    async def _cancel_all(group: set[asyncio.Task[None]]) -> None:
        tasks = [t for t in group if t is not asyncio.current_task()]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    def _require_config(self) -> ExperimentConfig:
        assert self._config is not None
        return self._config

    # --- prepare --------------------------------------------------------------

    async def _do_prepare(self) -> None:
        cfg = self._require_config()
        try:
            async with asyncio.timeout(cfg.timeouts.prepare):
                await self._devices.refresh()
        except TimeoutError:
            self._signal(Signal.PREPARE_FAILED, problems=["device discovery timed out"])
            return

        problems: list[str] = []
        for item in (*cfg.probes, *((cfg.test,) if cfg.test else ())):
            device = self._devices.get(item.device_id)
            if device is None:
                problems.append(f"{item.name}: device {item.device_id} is not connected")
                continue
            support = device.check(item.requires)
            if not support.supported:
                problems.append(f"{item.name}: {device.name} lacks {support.reason}")
        if problems:
            self._signal(Signal.PREPARE_FAILED, problems=problems)
        else:
            self._signal(Signal.PREPARED)

    # --- measurement ----------------------------------------------------------

    async def _do_start_measurement(self) -> None:
        cfg = self._require_config()
        first = {p.name: asyncio.Event() for p in cfg.probes}
        for probe in cfg.probes:
            self._spawn(self._run_probe(probe, first[probe.name], cfg), self._probe_tasks)
        try:
            async with asyncio.timeout(cfg.timeouts.start_measurement):
                await asyncio.gather(*(e.wait() for e in first.values()))
        except TimeoutError:
            waiting = [name for name, e in first.items() if not e.is_set()]
            self._signal(Signal.MEASUREMENT_START_FAILED, waiting_for=waiting)
            return
        self._signal(Signal.MEASUREMENT_STARTED)

    async def _run_probe(self, probe: Probe, first: asyncio.Event, cfg: ExperimentConfig) -> None:
        loop = asyncio.get_running_loop()
        last_sample = [0.0]

        def emit(values: Mapping[str, float]) -> None:
            self._rec.sample(Sample(probe.name, self._clock(), dict(values)))
            last_sample[0] = loop.time()
            first.set()

        async def watchdog(limit: float) -> None:
            await first.wait()
            while loop.time() - last_sample[0] <= limit:
                await asyncio.sleep(limit / 4)
            raise TimeoutError(f"no sample for more than {limit} s")

        run = loop.create_task(probe.run(emit))
        watchers = {run}
        if cfg.stall_timeout is not None:
            watchers.add(loop.create_task(watchdog(cfg.stall_timeout)))
        try:
            done, _ = await asyncio.wait(watchers, return_when=asyncio.FIRST_COMPLETED)
            finished = done.pop()
            error = finished.exception()
            if finished is run and error is None:
                error = RuntimeError("probe returned without being stopped")
            kind = "probe_error" if finished is run else "probe_stalled"
            self._log(kind, probe=probe.name, error=repr(error))
            self._signal(Signal.FATAL_ERROR)
        finally:
            for task in watchers:
                task.cancel()
            await asyncio.gather(*watchers, return_exceptions=True)

    # --- test -------------------------------------------------------------------

    def _test(self) -> TestAction:
        test = self._require_config().test
        assert test is not None
        return test

    async def _do_start_test(self) -> None:
        cfg = self._require_config()
        self._test_touched = True
        self._log("test_start_requested", test=self._test().name)
        try:
            async with asyncio.timeout(cfg.timeouts.start_test):
                await self._test().start()
        except Exception as exc:  # includes the timeout; cancellation passes through
            self._log("test_error", phase="start", error=repr(exc))
            self._signal(Signal.TEST_FAILED if await self._revert() else Signal.REVERT_FAILED)
            return
        self._signal(Signal.TEST_STARTED)

    async def _do_stop_test(self, start_task: asyncio.Task[None] | None) -> None:
        if start_task is not None and not start_task.done():
            start_task.cancel()
            await asyncio.gather(start_task, return_exceptions=True)
        await self._try_test_stop()
        self._signal(Signal.TEST_ENDED if await self._revert() else Signal.REVERT_FAILED)

    async def _try_test_stop(self) -> None:
        cfg = self._require_config()
        try:
            async with asyncio.timeout(cfg.timeouts.stop_test):
                await self._test().stop()
        except Exception as exc:  # still revert afterwards
            self._log("test_error", phase="stop", error=repr(exc))

    async def _revert(self) -> bool:
        cfg = self._require_config()
        try:
            async with asyncio.timeout(cfg.timeouts.revert):
                await self._test().revert()
        except Exception as exc:
            self._log("test_error", phase="revert", error=repr(exc))
            return False
        self._test_touched = False
        self._log("test_reverted", test=self._test().name)
        return True

    def _arm_recovery_timer(self) -> None:
        self._cancel_recovery_timer()
        self._recovery_timer = self._spawn(self._do_recovery_timer())

    def _cancel_recovery_timer(self) -> None:
        timer, self._recovery_timer = self._recovery_timer, None
        if timer is not None and timer is not asyncio.current_task():
            timer.cancel()

    async def _do_recovery_timer(self) -> None:
        await asyncio.sleep(self._require_config().recovery_window)
        self._signal(Signal.RECOVERY_DONE)

    # --- shutdown ---------------------------------------------------------------

    async def _do_shutdown(self) -> None:
        cfg = self._require_config()
        try:
            async with asyncio.timeout(cfg.timeouts.stop):
                await self._cancel_all(self._ops)
                # Test first, measurement last: the revert stays visible in the data.
                if self._test_touched:
                    if self._snap.stop_reason is not StopReason.USER_ABORT:
                        await self._try_test_stop()
                    if not await self._revert():
                        self._signal(Signal.FATAL_ERROR)
                await self._cancel_all(self._probe_tasks)
        except TimeoutError:
            self._log("stop_timeout")
            self._signal(Signal.STOP_FAILED)
            return
        self._test_start = None
        self._signal(Signal.STOPPED)
