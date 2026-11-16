# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 서민재
"""Contracts between the controller and what it drives.

Measurement (Probe) and test (TestAction) know nothing about each other.
They only meet on the recorded timeline.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Protocol

from wls.core.devices import Capability

Emit = Callable[[Mapping[str, float]], None]


class Probe(Protocol):
    """Produces samples until cancelled.

    ``run`` must be restartable (a repeated run calls it again) and must stop
    promptly when cancelled. Returning or raising while not cancelled counts
    as a failure of the measurement.
    """

    name: str
    device_id: str
    requires: frozenset[Capability]

    async def run(self, emit: Emit) -> None: ...


class TestAction(Protocol):
    """Something done on purpose during a measurement to observe its effect.

    ``start`` returning is the confirmation that the test is active.
    ``revert`` restores the device to its normal state; it must be idempotent
    and safe to call at any time, including after a failed or cancelled start.
    """

    __test__ = False  # not a pytest test class

    name: str
    device_id: str
    requires: frozenset[Capability]

    async def start(self) -> None: ...

    async def stop(self) -> None: ...

    async def revert(self) -> None: ...


@dataclass(frozen=True, slots=True)
class Sample:
    probe: str
    t_ns: int  # monotonic clock
    values: Mapping[str, float]


@dataclass(frozen=True, slots=True)
class Event:
    t_ns: int  # monotonic clock
    kind: str
    data: Mapping[str, object] = field(default_factory=dict)


class Recorder(Protocol):
    def sample(self, sample: Sample) -> None: ...

    def event(self, event: Event) -> None: ...


class MemoryRecorder:
    """Keeps everything in memory. Persistent storage is a later unit."""

    def __init__(self) -> None:
        self.samples: list[Sample] = []
        self.events: list[Event] = []

    def sample(self, sample: Sample) -> None:
        self.samples.append(sample)

    def event(self, event: Event) -> None:
        self.events.append(event)

    def kinds(self) -> list[str]:
        return [e.kind for e in self.events]

    def of_kind(self, kind: str) -> list[Event]:
        return [e for e in self.events if e.kind == kind]
