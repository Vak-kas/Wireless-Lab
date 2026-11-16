# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 서민재
"""The computer this program runs on, as a device. Works on every OS."""

from __future__ import annotations

import platform
import shutil

from wls.core.devices import SUPPORTED, Capability, Device, DeviceKind, unsupported

HOST_ID = "host"


class LocalHostProvider:
    name = "host"

    async def discover(self) -> list[Device]:
        ping = shutil.which("ping")
        net = SUPPORTED if ping else unsupported("the system 'ping' command was not found")
        system = platform.system() or "unknown"
        return [
            Device(
                HOST_ID,
                DeviceKind.HOST,
                f"This computer ({system})",
                {Capability.NET_PROBE: net},
                {"system": system, "release": platform.release()},
            )
        ]
