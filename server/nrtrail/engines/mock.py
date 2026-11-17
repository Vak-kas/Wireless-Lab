"""MockEngine — 저장해 둔 원시 결과(JSON)를 재생한다. MATLAB이 없어도 화면과 서버가 전부 동작하게 한다.

찾는 순서: pipeline/golden/<시나리오>/<단계>.json (MATLAB이 합성 파형을 실제로 처리한 결과)
          → pipeline/mock/<시나리오>/<단계>.json (tools/gen_mock.py가 지어낸 값)
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from ..paths import GOLDEN, PIPELINE
from ..pipeline import load_pipeline
from .base import Progress, failed

MOCK = PIPELINE / "mock"


class MockEngine:
    name = "mock"

    def __init__(self, delay_s: float = 0.35):
        self.delay_s = delay_s  # 진행 표시가 보이도록 문구마다 쉬는 시간. 테스트는 0으로 둔다.

    def available(self) -> bool:
        return True

    def find(self, scenario: str, stage: str) -> Path | None:
        for base in (GOLDEN, MOCK):
            p = base / scenario / f"{stage}.json"
            if p.exists():
                return p
        return None

    def run_raw(self, stage: str, inputs: dict[str, Any], progress: Progress) -> dict[str, Any]:
        scenario = inputs.get("scenario")
        path = self.find(scenario, stage) if scenario else None
        keys = list(load_pipeline().stage(stage).data.get("progress", {}))
        for i, key in enumerate(keys):
            progress(i / max(len(keys), 1), key)
            if self.delay_s:
                time.sleep(self.delay_s)
        if path is None:
            return failed(stage, "INTERNAL", "mock engine can only replay practice scenarios")
        raw: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        raw["stage"] = stage
        return raw
