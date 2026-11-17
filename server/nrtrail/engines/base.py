"""엔진 인터페이스. 엔진은 신호처리만 해서 원시 결과(raw)를 돌려주고, 조립은 runner가 한다.

구현: MockEngine(저장된 raw 재생), MatlabEngine(MATLAB +nrtrail 호출), NativeEngine(자리만).
어떤 엔진도 SDR 송신 경로를 부르지 않는다.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

# progress(진행률 0~1, 문구 키)
Progress = Callable[[float, str], None]

# 단계 id -> 엔진(MATLAB) 쪽 단계 이름
ENGINE_STAGE = {"scan": "scan", "ssb": "ssb", "mib": "mib", "sib1": "sib1", "sib19": "si", "ra": "ra"}


class Engine(Protocol):
    name: str

    def available(self) -> bool: ...

    def run_raw(self, stage: str, inputs: dict[str, Any], progress: Progress) -> dict[str, Any]:
        """inputs: {"capture": {"meta", "data"}, "params", "prior", "scenario"} -> docs/engine-contract.md 의 출력 JSON"""
        ...


def failed(stage: str, code: str, detail: str = "") -> dict[str, Any]:
    return {"stage": stage, "ok": False, "error_code": code, "error_detail": detail,
            "measurements": {}, "bits": {}, "soft": {}, "plots": {}}
