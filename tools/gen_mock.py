#!/usr/bin/env python3
"""연습 시나리오의 예시 데이터를 만든다.

1) pipeline/mock/<시나리오>/<단계>.json      — 지어낸 원시 결과(raw). MockEngine이 재생한다.
2) web/src/mock/fixtures/…                   — 화면 개발·테스트용 StageResult와 단계 정의(생성물, 손으로 고치지 말 것)

사용: python tools/gen_mock.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))

from nrtrail import mockraw  # noqa: E402
from nrtrail.engines.mock import MOCK, MockEngine  # noqa: E402
from nrtrail.paths import PIPELINE, ROOT, WEB  # noqa: E402
from nrtrail.pipeline import load_glossary, load_pipeline  # noqa: E402
from nrtrail.runner import RunState, StageLocked, run_stage  # noqa: E402

FIXTURES = WEB / "src" / "mock" / "fixtures"


def dump(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")


def main() -> int:
    scenarios = json.loads((PIPELINE / "scenarios.json").read_text(encoding="utf-8"))["scenarios"]
    pipeline = load_pipeline()
    engine = MockEngine(delay_s=0)
    for sc in scenarios:
        for stage, gen in mockraw.GENERATORS.items():
            dump(MOCK / sc["id"] / f"{stage}.json", gen(sc))
        state = RunState(capture={"center_freq_hz": sc["center_freq_hz"], "sample_rate_hz": sc["sample_rate_hz"],
                                  "source_kind": "synthetic"}, scenario=sc["id"], band=sc["band"])
        line = []
        for stage in pipeline.order:
            try:
                result = run_stage(engine, pipeline, stage, state)
            except StageLocked:
                break
            dump(FIXTURES / sc["id"] / f"{stage}.json", result.model_dump(mode="json", exclude_none=True))
            line.append(f"{stage}={result.status}")
        print(f"{sc['id']}: " + ", ".join(line))
    dump(FIXTURES / "pipeline.json", pipeline.public())
    dump(FIXTURES / "glossary.json", load_glossary())
    dump(FIXTURES / "scenarios.json", [{k: s[k] for k in ("id", "title", "description", "band") if k in s} | {"recommended": s.get("recommended", False)}
                                       for s in scenarios])
    print(f"생성: {MOCK.relative_to(ROOT)}/, {FIXTURES.relative_to(ROOT)}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
