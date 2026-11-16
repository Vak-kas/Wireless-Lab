# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 서민재
"""Build, install and call the macOS helper app.

macOS gives Wi-Fi network names only to an application bundle that the user
allowed to use Location Services. The helper is that bundle; this module
builds it from the Swift source shipped with the package (needs the Xcode
command line tools), asks for the permission once, and reads its JSON output.

The helper is signed ad hoc, for this computer only. Distributing a prebuilt
helper to other people needs an Apple Developer ID signature.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

APP = Path.home() / "Library" / "Application Support" / "WirelessLab" / "WirelessLabHelper.app"
_SOURCE = Path(__file__).parent / "macos_helper_src"
_CACHE_SECONDS = 5.0
_cache: dict[tuple[str, ...], tuple[float, dict]] = {}


class HelperError(RuntimeError):
    pass


def binary(app: Path = APP) -> Path:
    return app / "Contents" / "MacOS" / "WirelessLabHelper"


def installed(app: Path = APP) -> bool:
    return binary(app).is_file()


def build(app: Path = APP) -> None:
    """Compile and sign the helper. Raises HelperError with a readable reason."""
    if shutil.which("swiftc") is None:
        raise HelperError(
            "the Swift compiler was not found; install the Xcode command line tools "
            "(xcode-select --install)"
        )
    target = binary(app)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(_SOURCE / "Info.plist", app / "Contents" / "Info.plist")
    for command in (
        ["swiftc", "-O", str(_SOURCE / "main.swift"), "-o", str(target)],
        ["codesign", "--force", "--sign", "-", str(app)],
    ):
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            raise HelperError(f"{command[0]} failed: {result.stderr.strip()[-400:]}")
    _cache.clear()


def run(command: str, *args: str, timeout: float = 20.0, app: Path = APP) -> dict:
    """Run one helper command and return its JSON answer.

    The helper is started through ``open`` (Launch Services), not executed
    directly: macOS attributes a directly executed binary to the program that
    started it, and then withholds network names even though the helper itself
    is allowed.
    """
    if not installed(app):
        raise HelperError("the helper is not installed")
    with tempfile.TemporaryDirectory(prefix="wls-helper-") as folder:
        output = Path(folder) / "answer.json"
        try:
            subprocess.run(
                ["open", "-W", "-n", str(app), "--stdout", str(output), "--args", command, *args],
                capture_output=True, timeout=timeout, check=False, stdin=subprocess.DEVNULL,
            )  # fmt: skip
            text = output.read_text(encoding="utf-8") if output.exists() else ""
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise HelperError(f"the helper did not answer: {exc}") from None
    try:
        answer = json.loads(text.strip().splitlines()[-1])
    except (IndexError, ValueError):
        raise HelperError(f"unexpected helper output: {text[-200:]!r}") from None
    if "error" in answer:
        raise HelperError(str(answer["error"]))
    return answer


def cached(command: str, *args: str) -> dict:
    """Like ``run`` for cheap, frequently repeated questions."""
    key = (command, *args)
    hit = _cache.get(key)
    if hit and time.monotonic() - hit[0] < _CACHE_SECONDS:
        return hit[1]
    answer = run(command, *args)
    _cache[key] = (time.monotonic(), answer)
    return answer


def request_permission(app: Path = APP, timeout: float = 150.0) -> str:
    """Show the macOS permission question (once) and return the resulting status."""
    _cache.clear()
    try:
        answer = run("authorize", timeout=timeout, app=app)
    except HelperError:
        answer = run("status", app=app)
    _cache.clear()
    return str(answer.get("location", "unknown"))


def setup(app: Path = APP) -> str:
    """Build if needed, ask for permission if needed. Returns the location status."""
    if not installed(app):
        build(app)
    status = str(run("status", app=app).get("location", "unknown"))
    if status == "not_determined":
        status = request_permission(app)
    return status


STATUS_HELP = {
    "authorized": "",
    "not_determined": "the permission question has not been answered yet",
    "denied": (
        "Location Services is turned off for Wireless Lab Helper; allow it in "
        "System Settings > Privacy & Security > Location Services"
    ),
    "restricted": "Location Services is restricted on this Mac",
    "services_off": (
        "Location Services is turned off; turn it on in "
        "System Settings > Privacy & Security > Location Services"
    ),
}
