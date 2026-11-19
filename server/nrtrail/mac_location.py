"""macOS 의 위치 권한을 묻거나(창을 띄운다) 지금 상태를 읽어 JSON 한 줄로 찍는다 (adapters 가 따로 띄운다).

    python -m nrtrail.mac_location [ask] [기다릴 초]

macOS 는 위치 권한이 있는 프로그램에만 주변 Wi-Fi 의 이름과 주소를 알려 준다. 이 도구는 위치 자체를 읽지 않는다
(위치 갱신을 시작하지 않는다). 권한을 물을 때 운영체제가 띄우는 창에서 사용자가 고른다.
"""

from __future__ import annotations

import json
import sys
import time
from typing import Any

STATES = {0: "undetermined", 1: "restricted", 2: "denied", 3: "authorized", 4: "authorized"}


def state_of(manager: Any) -> str:
    return STATES.get(int(manager.authorizationStatus()), "unknown")


def main() -> None:
    try:
        import CoreLocation
        from Foundation import NSDate, NSRunLoop
    except ImportError:
        print(json.dumps({"state": "unknown", "error": "pyobjc-framework-CoreLocation 이 없습니다"}))
        return
    manager = CoreLocation.CLLocationManager.alloc().init()
    if not CoreLocation.CLLocationManager.locationServicesEnabled():
        print(json.dumps({"state": "off"}))
        return
    if "ask" in sys.argv[1:] and state_of(manager) == "undetermined":
        wait_s = float(sys.argv[2]) if len(sys.argv) > 2 else 60.0
        manager.requestWhenInUseAuthorization()
        deadline = time.monotonic() + wait_s
        while state_of(manager) == "undetermined" and time.monotonic() < deadline:      # 사용자가 창에서 고를 때까지
            NSRunLoop.currentRunLoop().runUntilDate_(NSDate.dateWithTimeIntervalSinceNow_(0.2))
    print(json.dumps({"state": state_of(manager)}))


if __name__ == "__main__":
    main()
