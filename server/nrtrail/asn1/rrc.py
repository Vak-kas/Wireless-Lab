"""RRC ASN.1 해석(UPER). pycrate에 들어 있는 TS 38.331 정의(Rel-18, SIB19-r17 포함)를 쓴다.

pycrate의 ASN.1 객체는 전역 하나를 돌려 쓰므로 스레드 안전하지 않다. 그래서 잠금을 건다.
값 표현(get_val): SEQUENCE=dict, CHOICE=(이름, 값), BIT STRING=(정수, 비트 수), OCTET STRING=bytes.
"""

from __future__ import annotations

import json
import threading
from typing import Any

from pycrate_asn1dir.RRCNR import NR_RRC_Definitions as _D

_lock = threading.Lock()

MESSAGES = {
    "BCCH-BCH-Message": _D.BCCH_BCH_Message,
    "BCCH-DL-SCH-Message": _D.BCCH_DL_SCH_Message,
    "DL-CCCH-Message": _D.DL_CCCH_Message,
    "SIB1": _D.SIB1,
    "SIB19-r17": _D.SIB19_r17,
}


class Asn1Error(ValueError):
    pass


def encode(message: str, value: Any) -> bytes:
    """값을 UPER 바이트로. 바이트 경계까지 0으로 채운다."""
    obj = MESSAGES[message]
    with _lock:
        try:
            obj.set_val(value)
            return obj.to_uper()
        except Exception as e:  # pycrate는 여러 종류의 예외를 던진다
            raise Asn1Error(f"{message} 인코드 실패: {e}") from e


def decode(message: str, data: bytes) -> tuple[Any, Any]:
    """UPER 바이트를 풀어 (파이썬 값, JSON으로 옮길 수 있는 트리)를 돌려준다."""
    obj = MESSAGES[message]
    with _lock:
        try:
            obj.from_uper(data)
            return obj.get_val(), json.loads(obj.to_jer())
        except Exception as e:
            raise Asn1Error(f"{message} 해석 실패: {e}") from e


def bits_to_int(value: tuple[int, int]) -> int:
    return value[0]


def find_path(value: Any, *path: str | int) -> Any:
    """중첩된 값에서 경로를 따라간다. 없으면 None. CHOICE는 (이름, 값)이므로 이름이 맞으면 값으로 들어간다."""
    cur = value
    for key in path:
        if cur is None:
            return None
        if isinstance(cur, tuple) and len(cur) == 2 and isinstance(cur[0], str):
            cur = cur[1] if cur[0] == key else None
            continue
        if isinstance(cur, dict):
            cur = cur.get(key)  # type: ignore[arg-type]
        elif isinstance(cur, list) and isinstance(key, int):
            cur = cur[key] if -len(cur) <= key < len(cur) else None
        else:
            return None
    return cur
