"""컴퓨터의 블루투스로 BLE 광고를 듣고 결과를 JSON 한 줄로 찍는다 (adapters.ble_scan 이 따로 띄운다).

    python -m nrtrail.ble_host <초>

광고(누구나 받으라고 내보내는 방송)만 모은다. 어느 기기에도 연결하지 않고, 아무것도 보내지 않는다(수동 찾기를 요청한다.
운영체제가 수동 찾기를 못 하면 능동 찾기로 내려가는데, 그때는 운영체제가 표준의 SCAN_REQ 를 보낼 수 있다).
"""

from __future__ import annotations

import asyncio
import json
import sys
from typing import Any

from .ble import COMPANIES


async def listen(seconds: float) -> list[dict[str, Any]]:
    from bleak import BleakScanner

    seen: dict[str, dict[str, Any]] = {}

    def on_adv(dev: Any, adv: Any) -> None:
        row = seen.setdefault(dev.address, {"address": dev.address, "count": 0})
        row["count"] += 1
        row["name"] = adv.local_name or row.get("name") or ""
        row["rssi_dbm"] = int(adv.rssi)
        ids = sorted(adv.manufacturer_data.keys())
        row["company"] = next((COMPANIES[i] for i in ids if i in COMPANIES), row.get("company", ""))
        row["company_ids"] = ids
        row["services"] = len(adv.service_uuids)
        if adv.tx_power is not None:
            row["tx_power_dbm"] = int(adv.tx_power)

    try:
        scanner = BleakScanner(on_adv, scanning_mode="passive")
        await scanner.start()
    except Exception:  # noqa: BLE001 — 수동 찾기를 지원하지 않는 운영체제·어댑터가 있다
        scanner = BleakScanner(on_adv)
        await scanner.start()
    try:
        await asyncio.sleep(seconds)
    finally:
        await scanner.stop()
    return list(seen.values())


def main() -> None:
    seconds = float(sys.argv[1]) if len(sys.argv) > 1 else 4.0
    try:
        print(json.dumps({"devices": asyncio.run(listen(seconds))}))
    except Exception as e:  # noqa: BLE001 — 어댑터 꺼짐·권한 없음 등은 문구로 돌려준다
        print(json.dumps({"devices": [], "error": f"{type(e).__name__}: {e}"}))


if __name__ == "__main__":
    main()
