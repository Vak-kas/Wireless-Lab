# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 서민재
"""Download and upload throughput over HTTP.

The probe alternates a download phase and an upload phase and emits the
current rate (``down_mbps`` or ``up_mbps``) several times per second, so the
result is a time series like every other probe. It needs an HTTP server that
serves a large download and accepts an upload; the URLs are configurable.

Upload bytes are counted when handed to the operating system, so the first
upload sample can be slightly high.
"""

from __future__ import annotations

import asyncio
import http.client
import os
import threading
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urlsplit

from wls import __version__
from wls.core.devices import Capability
from wls.core.interfaces import Emit
from wls.providers.host import HOST_ID

DEFAULT_DOWN_URL = "https://speed.cloudflare.com/__down?bytes=50000000"
DEFAULT_UP_URL = "https://speed.cloudflare.com/__up"
_HEADERS = {"User-Agent": f"wls/{__version__}", "Accept-Encoding": "identity"}
_CHUNK = 64 * 1024


def check_url(url: str) -> None:
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError(f"not an http(s) URL: {url!r}")


class _Transfer:
    """State shared between the worker thread and the sampling loop."""

    def __init__(self) -> None:
        self.bytes = 0
        self.stop = threading.Event()
        self.connection: http.client.HTTPConnection | None = None

    def open(self, url: str) -> tuple[http.client.HTTPConnection, str]:
        parts = urlsplit(url)
        factory = (
            http.client.HTTPSConnection if parts.scheme == "https" else http.client.HTTPConnection
        )
        self.connection = factory(parts.hostname, parts.port, timeout=10)
        path = parts.path or "/"
        return self.connection, path + (f"?{parts.query}" if parts.query else "")

    def abort(self) -> None:
        self.stop.set()
        connection = self.connection
        if connection is not None:
            try:
                connection.close()
            except OSError:
                pass


def _download(url: str, transfer: _Transfer) -> None:
    while not transfer.stop.is_set():
        connection, path = transfer.open(url)
        connection.request("GET", path, headers=_HEADERS)
        response = connection.getresponse()
        if response.status != 200:
            raise RuntimeError(f"download server answered HTTP {response.status}")
        received = 0
        while not transfer.stop.is_set():
            chunk = response.read(_CHUNK)
            if not chunk:
                break
            received += len(chunk)
            transfer.bytes += len(chunk)
        connection.close()
        if received == 0:
            raise RuntimeError("download server sent no data")


def _upload(url: str, transfer: _Transfer, size: int) -> None:
    block = os.urandom(_CHUNK)  # random, so nothing on the path can compress it

    def body():
        sent = 0
        while sent < size and not transfer.stop.is_set():
            part = block[: min(_CHUNK, size - sent)]
            sent += len(part)
            transfer.bytes += len(part)
            yield part

    headers = _HEADERS | {
        "Content-Length": str(size),
        "Content-Type": "application/octet-stream",
    }
    while not transfer.stop.is_set():
        connection, path = transfer.open(url)
        connection.request("POST", path, body=body(), headers=headers)
        if transfer.stop.is_set():
            break
        response = connection.getresponse()
        response.read()
        if response.status not in (200, 201, 204):
            raise RuntimeError(f"upload server answered HTTP {response.status}")
        connection.close()


def _guarded(work: Callable[..., None], transfer: _Transfer, *args: object) -> None:
    try:
        work(*args)
    except Exception:
        if not transfer.stop.is_set():  # errors caused by our own abort are expected
            raise


@dataclass
class SpeedProbe:
    down_url: str = DEFAULT_DOWN_URL
    up_url: str = DEFAULT_UP_URL
    name: str = "speed"
    device_id: str = HOST_ID
    requires: frozenset[Capability] = frozenset({Capability.NET_PROBE})
    phase_seconds: float = 5.0
    interval: float = 0.5
    upload_bytes: int = 10_000_000  # size of one upload request
    on_cycle: Callable[[], None] | None = None  # called after each download+upload

    async def run(self, emit: Emit) -> None:
        check_url(self.down_url)
        check_url(self.up_url)
        while True:
            await self._phase(emit, "down_mbps", _download, self.down_url)
            await self._phase(emit, "up_mbps", _upload, self.up_url, self.upload_bytes)
            if self.on_cycle is not None:
                self.on_cycle()

    async def _phase(self, emit: Emit, key: str, work: Callable[..., None], *args: object) -> None:
        loop = asyncio.get_running_loop()
        transfer = _Transfer()
        url, *extra = args
        worker = asyncio.ensure_future(
            asyncio.to_thread(_guarded, work, transfer, url, transfer, *extra)
        )
        try:
            last_bytes, last_time = 0, loop.time()
            end = last_time + self.phase_seconds
            while loop.time() < end:
                await asyncio.wait({worker}, timeout=min(self.interval, end - loop.time()))
                if worker.done():
                    worker.result()  # raises the transfer error, if any
                    raise RuntimeError("transfer ended unexpectedly")
                now, total = loop.time(), transfer.bytes
                if now > last_time:
                    emit({key: (total - last_bytes) * 8 / (now - last_time) / 1e6})
                last_bytes, last_time = total, now
        finally:
            transfer.abort()
            await asyncio.gather(worker, return_exceptions=True)
