#!/usr/bin/env python3
"""연습 시나리오의 예시 데이터를 만든다.

1) pipeline/mock/<시나리오>/<단계>.json      — 지어낸 원시 결과(raw). MockEngine이 재생한다.
2) web/src/mock/fixtures/…                   — 화면 개발·테스트용 StageResult와 단계 정의(생성물, 손으로 고치지 말 것)

사용: python tools/gen_mock.py
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))

from nrtrail import doctor, mockraw, tracking  # noqa: E402
from nrtrail.engines.mock import MOCK, MockEngine  # noqa: E402
from nrtrail.paths import PIPELINE, ROOT, WEB  # noqa: E402
from nrtrail.pipeline import load_glossary, load_pipeline  # noqa: E402
from nrtrail.runner import RunState, StageLocked, run_stage  # noqa: E402
from nrtrail.sessions import DEFAULT_SETTINGS  # noqa: E402
from nrtrail.stages import ntn  # noqa: E402

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
        if state.done("sib1"):
            ra_result = run_stage(engine, pipeline, "ra", state)
            dump(FIXTURES / sc["id"] / "ra.json", ra_result.model_dump(mode="json", exclude_none=True))
            line.append(f"ra={ra_result.status}")
        if state.done("sib19"):
            loc = DEFAULT_SETTINGS["location"]
            state.settings = DEFAULT_SETTINGS
            ntn_result = ntn.compute(SimpleNamespace(state=state), loc["lat"], loc["lon"], loc["alt_m"])
            dump(FIXTURES / sc["id"] / "ntn.json", ntn_result.model_dump(mode="json", exclude_none=True))
            line.append(f"ntn={ntn_result.status}")
            with tempfile.TemporaryDirectory() as tmp:
                fake = SimpleNamespace(state=state, dir=Path(tmp), id=sc["id"])
                tracker = tracking.Tracker(fake, pipeline, engine)  # type: ignore[arg-type]
                tracker.interval_s = 2.0
                tracker.points = [tracker.iterate(i * tracker.interval_s, i) for i in range(11)]
                dump(FIXTURES / sc["id"] / "track.json", tracker.data())
                dump(FIXTURES / sc["id"] / "track-changes.json", tracker.changes)
            line.append("track=11")
        print(f"{sc['id']}: " + ", ".join(line))
    dump(FIXTURES / "pipeline.json", pipeline.public())
    report = doctor.run_checks(quick=True)
    for c in report["checks"]:  # 이 컴퓨터의 경로는 예시 데이터에 넣지 않는다
        if c["id"] == "matlab" and c["status"] == "ok":
            c["detail"] = "matlab"
    dump(FIXTURES / "doctor.json", report)
    dump(FIXTURES / "glossary.json", load_glossary())
    dump(FIXTURES / "scenarios.json", [{k: s[k] for k in ("id", "title", "description", "band") if k in s} | {"recommended": s.get("recommended", False)}
                                       for s in scenarios])
    print(f"생성: {MOCK.relative_to(ROOT)}/, {FIXTURES.relative_to(ROOT)}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
