# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 서민재
"""Find the default gateway (the router) on macOS, Linux and Windows."""

from __future__ import annotations

import ipaddress
import platform
import re
import subprocess

_COMMANDS = {
    "Darwin": ["route", "-n", "get", "default"],
    "Linux": ["ip", "-4", "route", "show", "default"],
    "Windows": ["route", "print", "-4", "0.0.0.0"],
}
_PATTERNS = {
    "Darwin": re.compile(r"^\s*gateway:\s*(\S+)", re.MULTILINE),
    "Linux": re.compile(r"^default\s+via\s+(\S+)", re.MULTILINE),
    "Windows": re.compile(r"^\s*0\.0\.0\.0\s+0\.0\.0\.0\s+(\S+)\s", re.MULTILINE),
}


def parse_gateway(output: str, system: str) -> str | None:
    pattern = _PATTERNS.get(system)
    match = pattern.search(output) if pattern else None
    if match is None:
        return None
    try:
        return str(ipaddress.ip_address(match.group(1)))
    except ValueError:  # e.g. "On-link" on Windows, or an interface name
        return None


def default_gateway() -> str | None:
    """Address of the router, or None when it cannot be determined."""
    system = platform.system()
    command = _COMMANDS.get(system)
    if command is None:
        return None
    try:
        result = subprocess.run(
            command, capture_output=True, timeout=5, check=False, stdin=subprocess.DEVNULL
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return parse_gateway(result.stdout.decode(errors="replace"), system)
