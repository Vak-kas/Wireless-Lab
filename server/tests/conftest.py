"""공개판만 받은 경우(비공개 덧붙임과 내부 문서가 없음) 그것에 기대는 테스트를 건너뛴다.

비공개 덧붙임: MATLAB 합성 캡처와 정답(pipeline/golden/*/capture.*, cfg.json, truth.json), MATLAB 엔진.
내부 문서: DESIGN-*.md (디자인 토큰의 원본. 생성물 tokens.css 는 공개판에 들어 있다).
"""

from __future__ import annotations

import pytest
from nrtrail.paths import GOLDEN, ROOT

NEEDS_CAPTURE = (
    "test_simulated_device_streams_a_file_to_sigmf",
    "test_device_session_end_to_end_with_simulated_device",
    "test_live_device_input_stops_at_broadcast_information",
    "test_narrowband_device_is_limited_to_spectrum",
    "test_ra_is_refused_for_live_device_and_unmarked_files",
    "test_decoded_values_match_matlab_truth",
    "test_sib1_decoded_by_matlab_equals_what_python_encoded",
    "test_sib19_decoded_by_matlab_equals_what_python_encoded",
    "test_recording_makes_the_session_replayable_with_identical_results",
)
NEEDS_DESIGN_DOCS = ("test_contrast_pairs_meet_4_5",)


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    has_capture = (GOLDEN / "ntn-leo-n256" / "capture.sigmf-meta").exists()
    has_design = (ROOT / "DESIGN-apple.md").exists() and (ROOT / "DESIGN-extensions.md").exists()
    for item in items:
        name = item.name.split("[")[0]
        if not has_capture and name in NEEDS_CAPTURE:
            item.add_marker(pytest.mark.skip(reason="비공개 덧붙임(합성 캡처·정답 데이터)이 있어야 하는 테스트"))
        if not has_design and name in NEEDS_DESIGN_DOCS:
            item.add_marker(pytest.mark.skip(reason="디자인 문서(DESIGN-*.md)가 있어야 하는 테스트"))
