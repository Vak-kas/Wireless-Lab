"""꽂혀 있는 SDR 을 USB 번호만 보고 알아본다 (장비를 열지 않는다. 드라이버도 MATLAB 도 필요 없다).

이 설치에 그 장비를 쓰는 길(Pro 의 MATLAB 연결)이 없을 때, 장비 목록에 "알아봤지만 쓰려면 Pro 가 필요함"으로 보여 주기 위한 것이다.
여기서 나온 장비로는 받을 수 없다(capture 는 항상 거절한다).

USB 번호(제조사:제품): 2500:0020 USRP B200/B210, 2500:0021 B200mini, 2500:0022 B205mini,
3923:7813 NI USRP-2900(B200), 3923:7814 NI USRP-2901(B210) — UHD 의 b200 장치 표와 같은 값.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from . import devices, sigmf

PREFIX = "locked:"
KNOWN = {
    (0x2500, 0x0020): ("usrp", "USRP B200/B210"),
    (0x2500, 0x0021): ("usrp", "USRP B200mini"),
    (0x2500, 0x0022): ("usrp", "USRP B205mini"),
    (0x3923, 0x7813): ("usrp", "USRP B200 (NI USRP-2900)"),
    (0x3923, 0x7814): ("usrp", "USRP B210 (NI USRP-2901)"),
}
CACHE_S = 5.0
_cache: tuple[float, list[dict[str, Any]]] | None = None


def _run(cmd: list[str], timeout: float = 10.0) -> str:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return p.stdout if p.returncode == 0 else ""


def parse_ioreg(text: str) -> list[dict[str, Any]]:
    """macOS `ioreg -p IOUSB -l -w0`: 장치마다 "+-o 이름" 줄로 시작하고 그 아래에 "키" = 값 줄이 온다."""
    out = []
    for block in re.split(r"^[\s|]*\+-o ", text, flags=re.M)[1:]:
        def num(key: str, block: str = block) -> int | None:
            m = re.search(rf'"{key}" = (\d+)', block)
            return int(m.group(1)) if m else None

        def word(*keys: str, block: str = block) -> str:
            for key in keys:
                m = re.search(rf'"{key}" = "([^"]*)"', block)
                if m:
                    return m.group(1)
            return ""

        vid, pid = num("idVendor"), num("idProduct")
        if vid is not None and pid is not None:
            out.append({"vid": vid, "pid": pid, "serial": word("USB Serial Number", "kUSBSerialNumberString"),
                        "product": word("USB Product Name", "kUSBProductString")})
    return out


def parse_pnp(text: str) -> list[dict[str, Any]]:
    r"""Windows 의 장치 ID 줄: USB\VID_2500&PID_0021\<일련번호>"""
    return [{"vid": int(m.group(1), 16), "pid": int(m.group(2), 16), "serial": m.group(3).strip(), "product": ""}
            for m in re.finditer(r"USB\\VID_([0-9A-Fa-f]{4})&PID_([0-9A-Fa-f]{4})\\([^\s\\]+)", text)]


def read_sysfs(root: Path) -> list[dict[str, Any]]:
    """Linux: /sys/bus/usb/devices/<장치>/idVendor 등."""
    out = []
    for dev in sorted(root.glob("*/idVendor")):
        def text(name: str, base: Path = dev.parent) -> str:
            try:
                return (base / name).read_text(encoding="utf-8", errors="ignore").strip()
            except OSError:
                return ""
        try:
            out.append({"vid": int(text("idVendor"), 16), "pid": int(text("idProduct"), 16), "serial": text("serial"), "product": text("product")})
        except ValueError:
            continue
    return out


def usb_devices() -> list[dict[str, Any]]:
    if sys.platform == "darwin":
        return parse_ioreg(_run(["ioreg", "-p", "IOUSB", "-l", "-w0"]))
    if os.name == "nt":
        return parse_pnp(_run(["powershell", "-NoProfile", "-Command",
                               "(Get-CimInstance Win32_PnPEntity | Where-Object { $_.DeviceID -like 'USB\\VID_*' }).DeviceID"], 20))
    return read_sysfs(Path("/sys/bus/usb/devices"))


def recognise(found: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """아는 SDR 만 골라 장비 목록의 모양으로 만든다."""
    out = []
    for d in found:
        known = KNOWN.get((d["vid"], d["pid"]))
        if known:
            serial = str(d.get("serial") or "")
            label = f"{known[1]} ({serial})" if serial else known[1]
            unique = serial or "{:04x}-{:04x}".format(d["vid"], d["pid"])
            out.append({"id": f"{PREFIX}{known[0]}:{unique}", "label": label, "driver": "uhd",
                        "serial": serial, "needs": "pro"})
    return out


def list_found(force: bool = False, wait_s: float = 0.0) -> list[dict[str, Any]]:
    global _cache
    if not force and _cache is not None and time.monotonic() - _cache[0] < CACHE_S:
        return _cache[1]
    _cache = (time.monotonic(), recognise(usb_devices()))
    return _cache[1]


def capture(dev_id: str, req: devices.CaptureRequest, out_meta: Path) -> sigmf.Capture:
    raise devices.DeviceError("이 장비를 사용하려면 Pro 판이 필요합니다.")


def install() -> None:
    """장비 계층에 끼운다. 이 설치가 그 장비를 직접 쓸 수 있으면(Pro) 부르지 않는다."""
    devices.BACKENDS[PREFIX] = sys.modules[__name__]
