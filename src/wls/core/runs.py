# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 서민재
"""Browse recorded runs: list a directory, load one run as time series."""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from wls.core.storage import read_meta, read_run, verify_run

# Run files are named by the program; anything else is never opened.
RUN_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*\.sqlite$")
_KIND = re.compile(r"^\d{8}T\d{6}Z-(?P<kind>[a-z0-9_-]+)\.sqlite$")
_TIMELINE_KINDS = {"state", "mark", "test_start_requested", "test_reverted", "test_error",
                   "probe_error", "probe_stalled", "stop_timeout"}  # fmt: skip


@dataclass(frozen=True, slots=True)
class RunInfo:
    name: str
    kind: str
    started_utc: str
    sealed: bool
    intact: bool
    event_count: int
    sample_count: int


@dataclass(frozen=True, slots=True)
class Series:
    probe: str
    metric: str
    points: list[tuple[float, float]]  # seconds since the run started, value


@dataclass(frozen=True, slots=True)
class TimelineEvent:
    t: float  # seconds since the run started
    kind: str
    label: str


@dataclass(frozen=True, slots=True)
class RunDetail:
    info: RunInfo
    duration: float
    series: list[Series]
    events: list[TimelineEvent]


def run_path(directory: str | Path, name: str) -> Path | None:
    """Path of a run file inside ``directory``, or None for anything suspicious."""
    if not RUN_NAME.match(name):
        return None
    path = Path(directory) / name
    return path if path.is_file() else None


def _info(path: Path) -> RunInfo:
    check = verify_run(path)
    match = _KIND.match(path.name)
    return RunInfo(
        name=path.name,
        kind=match["kind"] if match else "run",
        started_utc=read_meta(path).get("started_wall_utc", ""),
        sealed=check.sealed,
        intact=check.intact,
        event_count=check.event_count,
        sample_count=check.sample_count,
    )


def list_runs(directory: str | Path) -> list[RunInfo]:
    """All readable runs, newest first. Files that are not runs are skipped."""
    directory = Path(directory)
    if not directory.is_dir():
        return []
    runs = []
    for path in directory.glob("*.sqlite"):
        if not RUN_NAME.match(path.name):
            continue
        try:
            runs.append(_info(path))
        except sqlite3.Error:
            continue
    return sorted(runs, key=lambda r: (r.started_utc, r.name), reverse=True)


def _label(kind: str, data: dict) -> str:
    if kind == "state":
        return str(data.get("state", ""))
    if kind == "mark":
        return str(data.get("label", ""))
    return str(data.get("error") or data.get("test") or data.get("phase") or "")


def load_run(path: str | Path) -> RunDetail:
    path = Path(path)
    events, samples = read_run(path)
    stamps = [e.t_ns for e in events] + [t for t, *_ in samples]
    start = min(stamps, default=0)
    end = max(stamps, default=0)

    grouped: dict[tuple[str, str], list[tuple[float, float]]] = {}
    for t_ns, probe, metric, value in samples:
        grouped.setdefault((probe, metric), []).append(((t_ns - start) / 1e9, value))
    series = [Series(probe, metric, points) for (probe, metric), points in grouped.items()]

    timeline = [
        TimelineEvent((e.t_ns - start) / 1e9, e.kind, _label(e.kind, dict(e.data)))
        for e in events
        if e.kind in _TIMELINE_KINDS
    ]
    return RunDetail(_info(path), (end - start) / 1e9, series, timeline)
