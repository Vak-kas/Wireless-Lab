# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 서민재
"""One SQLite file per run.

Samples are buffered briefly and written in batches. Every event forces a
write, so after a crash the file contains everything up to the last event.
``close`` seals the run: it stores row counts and a SHA-256 over all rows, and
``verify_run`` detects any later change.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from wls.core.interfaces import Event, Sample

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta   (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS event  (seq INTEGER PRIMARY KEY, t_ns INTEGER NOT NULL,
                                   kind TEXT NOT NULL, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sample (seq INTEGER PRIMARY KEY, t_ns INTEGER NOT NULL,
                                   probe TEXT NOT NULL, metric TEXT NOT NULL,
                                   value REAL NOT NULL);
"""
FORMAT_VERSION = "1"


class SqliteRecorder:
    def __init__(
        self,
        path: str | Path,
        *,
        flush_rows: int = 200,
        flush_interval: float = 0.5,
    ) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(self.path)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.executescript(_SCHEMA)
        self._flush_rows = flush_rows
        self._flush_interval = flush_interval
        self._samples: list[tuple[int, str, str, float]] = []
        self._events: list[tuple[int, str, str]] = []
        self._last_flush = time.monotonic()
        self._closed = False
        self._set_meta(
            format_version=FORMAT_VERSION,
            started_wall_utc=datetime.now(UTC).isoformat(),
            started_mono_ns=str(time.monotonic_ns()),  # maps t_ns to wall time
            sealed="0",
        )

    # --- Recorder -----------------------------------------------------------

    def sample(self, sample: Sample) -> None:
        for metric, value in sample.values.items():
            self._samples.append((sample.t_ns, sample.probe, metric, float(value)))
        due = time.monotonic() - self._last_flush >= self._flush_interval
        if len(self._samples) >= self._flush_rows or due:
            self.flush()

    def event(self, event: Event) -> None:
        data = json.dumps(dict(event.data), sort_keys=True, default=str, ensure_ascii=False)
        self._events.append((event.t_ns, event.kind, data))
        self.flush()

    # --- lifecycle ----------------------------------------------------------

    def flush(self) -> None:
        if self._closed:
            raise RuntimeError("recorder is closed")
        with self._db:
            self._db.executemany(
                "INSERT INTO sample (t_ns, probe, metric, value) VALUES (?, ?, ?, ?)",
                self._samples,
            )
            self._db.executemany(
                "INSERT INTO event (t_ns, kind, data) VALUES (?, ?, ?)", self._events
            )
        self._samples.clear()
        self._events.clear()
        self._last_flush = time.monotonic()

    def close(self) -> None:
        """Write what is left and seal the run. Safe to call twice."""
        if self._closed:
            return
        self.flush()
        events, samples, digest = _summarize(self._db)
        self._set_meta(
            sealed="1", event_count=str(events), sample_count=str(samples), sha256=digest
        )
        self._db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        self._db.close()
        self._closed = True

    def _set_meta(self, **values: str) -> None:
        with self._db:
            self._db.executemany(
                "INSERT INTO meta (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                values.items(),
            )


def _summarize(db: sqlite3.Connection) -> tuple[int, int, str]:
    digest = hashlib.sha256()
    events = samples = 0
    for row in db.execute("SELECT seq, t_ns, kind, data FROM event ORDER BY seq"):
        digest.update(repr(("e", *row)).encode())
        events += 1
    for row in db.execute("SELECT seq, t_ns, probe, metric, value FROM sample ORDER BY seq"):
        digest.update(repr(("s", *row)).encode())
        samples += 1
    return events, samples, digest.hexdigest()


@dataclass(frozen=True, slots=True)
class RunCheck:
    sealed: bool  # False: the run was not closed properly (crash or still running)
    intact: bool  # True only for a sealed run whose content matches its hash
    event_count: int
    sample_count: int


def verify_run(path: str | Path) -> RunCheck:
    db = sqlite3.connect(f"file:{Path(path)}?mode=ro", uri=True)
    try:
        meta = dict(db.execute("SELECT key, value FROM meta"))
        events, samples, digest = _summarize(db)
    finally:
        db.close()
    sealed = meta.get("sealed") == "1"
    intact = (
        sealed
        and meta.get("sha256") == digest
        and meta.get("event_count") == str(events)
        and meta.get("sample_count") == str(samples)
    )
    return RunCheck(sealed, intact, events, samples)


def read_meta(path: str | Path) -> dict[str, str]:
    db = sqlite3.connect(f"file:{Path(path)}?mode=ro", uri=True)
    try:
        return dict(db.execute("SELECT key, value FROM meta"))
    finally:
        db.close()


def read_run(path: str | Path) -> tuple[list[Event], list[tuple[int, str, str, float]]]:
    """Events and sample rows (t_ns, probe, metric, value) in recorded order."""
    db = sqlite3.connect(f"file:{Path(path)}?mode=ro", uri=True)
    try:
        events = [
            Event(t_ns, kind, json.loads(data))
            for t_ns, kind, data in db.execute("SELECT t_ns, kind, data FROM event ORDER BY seq")
        ]
        samples = list(
            db.execute("SELECT t_ns, probe, metric, value FROM sample ORDER BY seq")
        )
    finally:
        db.close()
    return events, samples
