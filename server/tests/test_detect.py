"""프레임 시작 찾기(detect): numpy 계산이 맞는지, C++ 프로그램(sigfind)이 같은 답을 내는지."""
import numpy as np
import pytest
from nrtrail import detect, sigmf


def lstf(repeats: int = 10) -> np.ndarray:
    """L-STF 처럼 16 샘플짜리 무늬가 되풀이되는 신호(무늬 자체는 아무 값이나 된다)."""
    rng = np.random.default_rng(1)
    period = (rng.standard_normal(16) + 1j * rng.standard_normal(16)) * 0.1
    return np.tile(period, repeats).astype(np.complex64)


def scene() -> tuple[np.ndarray, list[int]]:
    """잡음 속에 프레임 머리 셋. 하나는 DC(가운데 주파수에 서 있는 성분) 위에 얹혀 있다."""
    rng = np.random.default_rng(7)
    x = ((rng.standard_normal(200_000) + 1j * rng.standard_normal(200_000)) * 0.005).astype(np.complex64)
    at = [20_000, 90_000, 150_000]
    for a in at:
        x[a:a + 160] += lstf()
        x[a + 160:a + 2000] += ((rng.standard_normal(1840) + 1j * rng.standard_normal(1840)) * 0.07).astype(np.complex64)   # 뒤따르는 본문
    x += 0.02                                             # DC
    return x, at


def test_numpy_finder_marks_each_repeating_preamble_and_nothing_else():
    x, at = scene()
    found = detect.wifi_starts_numpy(x)
    assert len(found) == len(at)
    for a, f in zip(at, found, strict=True):
        assert a - detect.WIN <= f <= a + 20              # 창이 무늬에 걸치기 시작할 때부터 넘으므로 조금 일찍 알린다
    assert detect.wifi_starts_numpy(x[:100]) == []        # 너무 짧으면 빈 목록
    noise = x.copy()
    for a in at:
        noise[a:a + 2000] = x[a + 3000:a + 5000]          # 프레임이 있던 자리를 옆의 잡음으로 덮는다
    assert detect.wifi_starts_numpy(noise) == []          # 잡음과 DC 만으로는 아무것도 찾지 않는다


@pytest.mark.skipif(not detect.native(), reason="sigfind 가 지어져 있지 않다")
@pytest.mark.parametrize("datatype", ["ci16_le", "cf32_le"])
def test_native_finder_gives_the_same_answer(tmp_path, datatype):
    x, _ = scene()
    cap = sigmf.write_capture(tmp_path / "x.sigmf-meta", x, sample_rate_hz=20e6, center_freq_hz=5.18e9, source="device", datatype=datatype)
    assert detect.wifi_starts(cap) == detect.wifi_starts_numpy(cap.read(0, cap.num_samples))


def test_without_the_native_program_the_numpy_path_answers(tmp_path, monkeypatch):
    x, at = scene()
    cap = sigmf.write_capture(tmp_path / "x.sigmf-meta", x, sample_rate_hz=20e6, center_freq_hz=5.18e9, source="device", datatype="ci16_le")
    monkeypatch.setattr(detect, "BINARY", tmp_path / "nope")
    assert len(detect.wifi_starts(cap)) == len(at)
