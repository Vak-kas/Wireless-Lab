# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 서민재
"""Latency and loss by running the system ``ping`` once per sample.

Using the system command needs no administrator rights and works on macOS,
Windows and Linux. Each sample is ``{"rtt_ms": x, "lost": 0}`` or
``{"lost": 1}``. Jitter and loss rate are derived later from these samples.
"""

from __future__ import annotations

import asyncio
import math
import platform
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from wls.core.devices import Capability
from wls.core.interfaces import Emit
from wls.providers.host import HOST_ID

# "time=11.2 ms" (Linux, macOS), "time=12ms" / "time<1ms" (Windows, any language)
_REPLY_TIME = re.compile(r"[=<]\s*([0-9]+(?:[.,][0-9]+)?)\s*ms", re.IGNORECASE)

Runner = Callable[[list[str], float], Awaitable[str]]


def ping_command(host: str, timeout: float, system: str | None = None) -> list[str]:
    if not host or host.startswith("-") or any(c.isspace() for c in host):
        raise ValueError(f"invalid host: {host!r}")
    system = system or platform.system()
    if system == "Windows":
        return ["ping", "-n", "1", "-w", str(int(timeout * 1000)), host]
    if system == "Darwin":
        return ["ping", "-n", "-c", "1", "-W", str(int(timeout * 1000)), host]
    return ["ping", "-n", "-c", "1", "-W", str(max(1, math.ceil(timeout))), host]


def parse_rtt_ms(output: str) -> float | None:
    """Round-trip time of the reply, or None when there was no reply."""
    match = _REPLY_TIME.search(output)
    if match is None:
        return None
    return float(match.group(1).replace(",", "."))


async def run_command(command: list[str], timeout: float) -> str:
    """Run a command and return its output; empty string if it had to be killed."""
    process = await asyncio.create_subprocess_exec(
        *command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
        stdin=asyncio.subprocess.DEVNULL,
    )
    try:
        async with asyncio.timeout(timeout):
            stdout, _ = await process.communicate()
        return stdout.decode(errors="replace")
    except TimeoutError:
        return ""
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()


@dataclass
class PingProbe:
    host: str
    name: str = "ping"
    device_id: str = HOST_ID
    requires: frozenset[Capability] = frozenset({Capability.NET_PROBE})
    interval: float = 1.0
    timeout: float = 1.0
    runner: Runner = run_command

    async def run(self, emit: Emit) -> None:
        command = ping_command(self.host, self.timeout)
        loop = asyncio.get_running_loop()
        next_at = loop.time()
        while True:
            output = await self.runner(command, self.timeout + 1.0)
            rtt = parse_rtt_ms(output)
            emit({"lost": 1.0} if rtt is None else {"rtt_ms": rtt, "lost": 0.0})
            # Fixed rate without drift; skip ahead if a sample took too long.
            next_at = max(next_at + self.interval, loop.time())
            await asyncio.sleep(next_at - loop.time())
