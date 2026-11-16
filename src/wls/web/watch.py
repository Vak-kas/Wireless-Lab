# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 서민재
"""Watch the Wi-Fi connection while the web UI is running and log its events.

Reading signal and channel is cheap and done every second. Asking for the
network identity (SSID, BSSID) can be expensive, so it is asked only when
something suggests a change, and every few seconds as a safety net.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections import deque
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path

from wls.core.roaming import LinkEvent, LinkObservation, LinkTracker
from wls.probes.wifi_link import LinkReading, Reader

Identity = Callable[[], tuple[str | None, str | None]]

POLL_SECONDS = 1.0
IDENTITY_EVERY = 6.0  # ask at least this often
RSSI_JUMP_DB = 8.0  # a sudden change of signal suggests another access point
KEEP_EVENTS = 200


class WifiWatch:
    def __init__(self, reader: Reader, identity: Identity, log_path: str | Path) -> None:
        self._reader = reader
        self._identity = identity
        self._log_path = Path(log_path)
        self._tracker = LinkTracker()
        self._events: deque[LinkEvent] = deque(maxlen=KEEP_EVENTS)
        self._previous: LinkReading | None = None
        self._first = True
        self._ssid: str | None = None
        self._bssid: str | None = None
        self._identity_at = float("-inf")
        self._task: asyncio.Task[None] | None = None
        self.started_at: float | None = None
        self._load()

    # --- log file -----------------------------------------------------------

    def _load(self) -> None:
        try:
            lines = self._log_path.read_text(encoding="utf-8").splitlines()[-KEEP_EVENTS:]
        except OSError:
            return
        for line in lines:
            try:
                self._events.append(LinkEvent(**json.loads(line)))
            except (ValueError, TypeError):
                continue  # a damaged line is skipped, the rest is kept

    def _append(self, event: LinkEvent) -> None:
        self._events.append(event)
        try:
            self._log_path.parent.mkdir(parents=True, exist_ok=True)
            with self._log_path.open("a", encoding="utf-8") as log:
                log.write(json.dumps(asdict(event), ensure_ascii=False) + "\n")
        except OSError:
            pass  # still shown from memory

    # --- watching -----------------------------------------------------------

    def _needs_identity(self, reading: LinkReading | None, now: float) -> bool:
        previous = self._previous
        if self._first or now - self._identity_at >= IDENTITY_EVERY:
            return True
        if (reading is None) != (previous is None):
            return True
        if reading is None or previous is None:
            return False
        return (
            reading.channel != previous.channel
            or abs(reading.rssi_dbm - previous.rssi_dbm) >= RSSI_JUMP_DB
        )

    async def step(self, now: float | None = None) -> list[LinkEvent]:
        """Take one observation; returns the events it produced."""
        now = time.time() if now is None else now
        reading = self._reader()
        if reading is not None and self._needs_identity(reading, now):
            self._ssid, self._bssid = await asyncio.to_thread(self._identity)
            self._identity_at = now
        self._first = False
        self._previous = reading
        if reading is None:
            observation = LinkObservation(now, False)
        else:
            observation = LinkObservation(
                now, True, self._ssid, self._bssid, reading.channel, reading.rssi_dbm
            )
        events = self._tracker.observe(observation)
        for event in events:
            self._append(event)
        return events

    async def _run(self) -> None:
        while True:
            try:
                await self.step()
            except Exception:  # a failing read must not end the watch
                pass
            await asyncio.sleep(POLL_SECONDS)

    def start(self) -> None:
        if self._task is None:
            self.started_at = time.time()
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    def snapshot(self) -> dict:
        return {
            "watching": self._task is not None,
            "watching_since": self.started_at,
            "identity_known": self._bssid is not None,
            "events": [asdict(e) for e in reversed(self._events)],
        }
