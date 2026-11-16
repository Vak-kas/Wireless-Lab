# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 서민재
"""Pure state machine of the experiment controller.

This module has no I/O, no clock and no asyncio. It answers two questions:

* ``decide(snapshot, command)``: a user asked for something. Is it accepted,
  a no-op, or rejected, and what is the snapshot afterwards?
* ``apply_signal(snapshot, signal)``: the executor confirmed that something
  really happened (or failed). What is the snapshot afterwards?

A request and its confirmation are separate steps. Accepting START_MEASUREMENT
only sets ``pending``; the state becomes MEASURING when MEASUREMENT_STARTED
arrives. Signals that arrive too late (for example a start confirmation after
the user already stopped) are ignored, never raised as errors.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum


class State(Enum):
    IDLE = "idle"
    PREPARING = "preparing"
    READY = "ready"
    MEASURING = "measuring"
    TEST_RUNNING = "test_running"
    RECOVERING = "recovering"  # test ended, measurement continues
    STOPPING = "stopping"
    COMPLETED = "completed"
    FAILED = "failed"


class Pending(Enum):
    """A request that was accepted but is not confirmed yet."""

    NONE = "none"
    STARTING_MEASUREMENT = "starting_measurement"
    STARTING_TEST = "starting_test"
    STOPPING_TEST = "stopping_test"


class StopReason(Enum):
    USER_STOP = "user_stop"
    USER_ABORT = "user_abort"
    ERROR = "error"


class Command(Enum):
    PREPARE = "prepare"
    START_MEASUREMENT = "start_measurement"
    STOP_MEASUREMENT = "stop_measurement"
    START_TEST = "start_test"
    STOP_TEST = "stop_test"
    MARK = "mark"
    STOP = "stop"  # bring everything down safely, test first
    ABORT = "abort"  # same target state as STOP, executor skips grace periods
    RESET = "reset"
    REPEAT = "repeat"


class Signal(Enum):
    PREPARED = "prepared"
    PREPARE_FAILED = "prepare_failed"
    MEASUREMENT_STARTED = "measurement_started"
    MEASUREMENT_START_FAILED = "measurement_start_failed"
    TEST_STARTED = "test_started"
    TEST_ENDED = "test_ended"  # stopped and device state reverted
    TEST_FAILED = "test_failed"  # failed, but device state reverted
    REVERT_FAILED = "revert_failed"
    RECOVERY_DONE = "recovery_done"
    FATAL_ERROR = "fatal_error"
    STOPPED = "stopped"
    STOP_FAILED = "stop_failed"


class Verdict(Enum):
    ACCEPTED = "accepted"
    NOOP = "noop"  # already in (or on the way to) the requested condition
    REJECTED = "rejected"


_ACTIVE = frozenset(
    {State.PREPARING, State.READY, State.MEASURING, State.TEST_RUNNING, State.RECOVERING}
)
_SAMPLING = frozenset({State.MEASURING, State.TEST_RUNNING, State.RECOVERING})
_TERMINAL = frozenset({State.COMPLETED, State.FAILED})

_ALLOWED_PENDING: dict[State, frozenset[Pending]] = {
    State.READY: frozenset({Pending.NONE, Pending.STARTING_MEASUREMENT}),
    State.MEASURING: frozenset({Pending.NONE, Pending.STARTING_TEST, Pending.STOPPING_TEST}),
    State.RECOVERING: frozenset({Pending.NONE, Pending.STARTING_TEST, Pending.STOPPING_TEST}),
    State.TEST_RUNNING: frozenset({Pending.NONE, Pending.STOPPING_TEST}),
}
_ONLY_NONE = frozenset({Pending.NONE})


@dataclass(frozen=True, slots=True)
class Snapshot:
    state: State = State.IDLE
    pending: Pending = Pending.NONE
    stop_reason: StopReason | None = None

    def __post_init__(self) -> None:
        if self.pending not in _ALLOWED_PENDING.get(self.state, _ONLY_NONE):
            raise ValueError(f"pending {self.pending.name} is not valid in {self.state.name}")
        if (self.stop_reason is not None) != (self.state is State.STOPPING):
            raise ValueError("stop_reason must be set exactly while STOPPING")

    @property
    def test_in_flight(self) -> bool:
        """True while a test is active, starting or stopping."""
        return self.state is State.TEST_RUNNING or self.pending in (
            Pending.STARTING_TEST,
            Pending.STOPPING_TEST,
        )


@dataclass(frozen=True, slots=True)
class Decision:
    verdict: Verdict
    snapshot: Snapshot
    reason: str = ""


def _stopping(reason: StopReason) -> Snapshot:
    return Snapshot(State.STOPPING, Pending.NONE, reason)


def decide(s: Snapshot, command: Command) -> Decision:
    """Evaluate a user command. Never raises; never changes state on NOOP/REJECTED."""

    def accept(new: Snapshot) -> Decision:
        return Decision(Verdict.ACCEPTED, new)

    def noop(reason: str) -> Decision:
        return Decision(Verdict.NOOP, s, reason)

    def reject(reason: str) -> Decision:
        return Decision(Verdict.REJECTED, s, reason)

    st, p = s.state, s.pending

    match command:
        case Command.STOP | Command.ABORT:
            if st in _ACTIVE:
                why = StopReason.USER_STOP if command is Command.STOP else StopReason.USER_ABORT
                return accept(_stopping(why))
            if st is State.STOPPING:
                return noop("already stopping")
            return noop("nothing is running")

        case Command.PREPARE:
            if st is State.IDLE:
                return accept(Snapshot(State.PREPARING))
            if st is State.PREPARING:
                return noop("already preparing")
            return reject("an experiment is already loaded")

        case Command.RESET:
            if st in _TERMINAL:
                return accept(Snapshot(State.IDLE))
            if st is State.IDLE:
                return noop("already idle")
            return reject("stop the run first")

        case Command.REPEAT:
            if st in _TERMINAL:
                return accept(Snapshot(State.PREPARING))
            return reject("only a finished run can be repeated")

        case Command.START_MEASUREMENT:
            if st is State.READY:
                if p is Pending.STARTING_MEASUREMENT:
                    return noop("measurement is already starting")
                return accept(replace(s, pending=Pending.STARTING_MEASUREMENT))
            if st in _SAMPLING:
                return noop("already measuring")
            return reject("not ready")

        case Command.STOP_MEASUREMENT:
            if st is State.READY and p is Pending.STARTING_MEASUREMENT:
                return accept(_stopping(StopReason.USER_STOP))
            if st in _SAMPLING:
                if s.test_in_flight:
                    return reject("a test is active; stop the test first or use STOP")
                return accept(_stopping(StopReason.USER_STOP))
            if st is State.STOPPING:
                return noop("already stopping")
            return noop("not measuring")

        case Command.START_TEST:
            if st in _SAMPLING:
                if p is Pending.STOPPING_TEST:
                    return reject("the previous test is still stopping")
                if p is Pending.STARTING_TEST:
                    return noop("test is already starting")
                if st is State.TEST_RUNNING:
                    return noop("test is already running")
                return accept(replace(s, pending=Pending.STARTING_TEST))
            return reject("measurement must be running before a test")

        case Command.STOP_TEST:
            if p is Pending.STOPPING_TEST:
                return noop("test is already stopping")
            if st is State.TEST_RUNNING or p is Pending.STARTING_TEST:
                return accept(replace(s, pending=Pending.STOPPING_TEST))
            return noop("no test is active")

        case Command.MARK:
            if st in _SAMPLING:
                return accept(s)
            return reject("marks need a running measurement")

    raise AssertionError(f"unhandled command {command!r}")  # pragma: no cover


def apply_signal(s: Snapshot, signal: Signal) -> tuple[Snapshot, bool]:
    """Apply an executor confirmation. Returns (snapshot, applied).

    ``applied`` is False when the signal does not fit the current snapshot
    (typically because it arrived late); the snapshot is then unchanged.
    """
    st, p = s.state, s.pending
    new: Snapshot | None = None

    match signal:
        case Signal.PREPARED:
            if st is State.PREPARING:
                new = Snapshot(State.READY)
        case Signal.PREPARE_FAILED:
            if st is State.PREPARING:
                new = Snapshot(State.FAILED)
        case Signal.MEASUREMENT_STARTED:
            if st is State.READY and p is Pending.STARTING_MEASUREMENT:
                new = Snapshot(State.MEASURING)
        case Signal.MEASUREMENT_START_FAILED:
            if st is State.READY and p is Pending.STARTING_MEASUREMENT:
                new = _stopping(StopReason.ERROR)
        case Signal.TEST_STARTED:
            if st in (State.MEASURING, State.RECOVERING) and p is Pending.STARTING_TEST:
                new = Snapshot(State.TEST_RUNNING)
        case Signal.TEST_ENDED | Signal.TEST_FAILED:
            # Either way the device is back in a safe state and measurement
            # keeps running, so the recovery interval starts here.
            if s.test_in_flight:
                new = Snapshot(State.RECOVERING)
        case Signal.REVERT_FAILED:
            if s.test_in_flight:
                new = _stopping(StopReason.ERROR)
        case Signal.RECOVERY_DONE:
            if st is State.RECOVERING and p is Pending.NONE:
                new = Snapshot(State.MEASURING)
        case Signal.FATAL_ERROR:
            if st in _ACTIVE:
                new = _stopping(StopReason.ERROR)
            elif st is State.STOPPING and s.stop_reason is not StopReason.ERROR:
                new = _stopping(StopReason.ERROR)
        case Signal.STOPPED:
            if st is State.STOPPING:
                failed = s.stop_reason is StopReason.ERROR
                new = Snapshot(State.FAILED if failed else State.COMPLETED)
        case Signal.STOP_FAILED:
            if st is State.STOPPING:
                new = Snapshot(State.FAILED)

    if new is None:
        return s, False
    return new, True
