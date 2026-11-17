"""주파수 상태 보기: 채널별 세기 계산과 모의 장비 경로."""
import numpy as np
import pytest
from nrtrail import devices, survey

RATE = 20e6


def tone_plus_noise(offset_hz: float, amp: float, n: int = 400_000, noise: float = 1e-3) -> np.ndarray:
    rng = np.random.default_rng(1)
    t = np.arange(n) / RATE
    x = amp * np.exp(2j * np.pi * offset_hz * t)
    return (x + noise * (rng.standard_normal(n) + 1j * rng.standard_normal(n)) / np.sqrt(2)).astype(np.complex64)


def test_power_of_a_tone_lands_in_its_channel_and_matches_its_amplitude():
    iq = tone_plus_noise(4e6, 0.1)
    spectra = survey.block_spectra(iq, RATE)
    hit = survey.measure_channel(spectra, -20.0, survey.Channel("a", 1e9 + 4e6, 2e6), 1e9, RATE)
    miss = survey.measure_channel(spectra, -20.0, survey.Channel("b", 1e9 - 4e6, 2e6), 1e9, RATE)
    assert hit["measured"] and abs(hit["mean_dbfs"] - (-20.0)) < 0.3      # 0.1² = −20 dB
    assert abs(hit["median_dbfs"] - hit["mean_dbfs"]) < 0.3                # 계속 나오는 신호는 평균 = 중앙값
    assert miss["mean_dbfs"] < hit["mean_dbfs"] - 30


def test_all_bins_add_up_to_the_total_power():
    iq = tone_plus_noise(1e6, 0.05, noise=0.02)
    total = float(survey.block_spectra(iq, RATE).sum(axis=1).mean())
    x = iq[: (len(iq) // survey.NFFT) * survey.NFFT]
    assert abs(10 * np.log10(total / float(np.mean(np.abs(x - x.mean()) ** 2)))) < 0.2


def test_bursty_signal_pulls_the_mean_up_but_not_the_median():
    iq = tone_plus_noise(0.0, 0.0, noise=1e-3)
    n = len(iq)
    burst = 0.2 * np.exp(2j * np.pi * 3e6 * np.arange(n // 10) / RATE)
    iq[: n // 10] += burst.astype(np.complex64)
    row = survey.measure_channel(survey.block_spectra(iq, RATE), -10.0, survey.Channel("a", 1e9 + 3e6, 2e6), 1e9, RATE)
    assert row["mean_dbfs"] - row["median_dbfs"] > 10


def test_channel_outside_the_received_band_is_not_measured():
    spectra = survey.block_spectra(tone_plus_noise(0, 0.1), RATE)
    row = survey.measure_channel(spectra, -20.0, survey.Channel("far", 1e9 + 30e6, 20e6), 1e9, RATE)
    assert not row["measured"] and "mean_dbfs" not in row
    edge = survey.measure_channel(spectra, -20.0, survey.Channel("edge", 1e9 + 9e6, 4e6), 1e9, RATE)
    assert not edge["measured"] and edge["coverage"] == 0.75


def test_wifi_channel_numbers_map_to_centre_frequencies():
    two = dict((c[0], c[1]) for c in survey.PLANS["wifi-2g4"]["channels"])
    five = dict((c[0], c[1]) for c in survey.PLANS["wifi-5g"]["channels"])
    assert two["ch1"] == 2412e6 and two["ch6"] == 2437e6 and two["ch13"] == 2472e6
    assert five["ch36"] == 5180e6 and five["ch100"] == 5500e6 and five["ch165"] == 5825e6
    assert len(five) == 25


def simulated_id() -> str:
    sims = [d for d in devices.list_devices() if d["driver"] == "simulated"]
    if not sims:
        pytest.skip("모의 장비용 저장 신호가 없는 배포판")
    return str(sims[0]["id"])


def test_simulated_device_surveys_the_band_in_its_file(tmp_path, monkeypatch):
    monkeypatch.setattr(survey, "sessions_dir", lambda: tmp_path)
    dev = simulated_id()
    info = survey.describe(dev)
    assert {p["id"]: p["available"] for p in info["plans"]} == {"capture": True, "wifi-2g4": False, "wifi-5g": False, "custom": False}
    assert info["capture"]["sample_rate_hz"] > 0
    out = survey.run(dev, "capture")
    rows = out["channels"]
    assert out["unit"] == "dBFS" and out["fixed_tuning"] and len(rows) == 16 and all(r["measured"] for r in rows)
    span = rows[-1]["center_hz"] - rows[0]["center_hz"] + rows[0]["width_hz"]
    assert abs(span - info["capture"]["sample_rate_hz"]) < 1
    assert max(r["mean_dbfs"] for r in rows) - min(r["mean_dbfs"] for r in rows) > 3   # 신호가 있는 칸과 없는 칸이 갈린다
    assert not list(tmp_path.rglob("*.sigmf-data"))                                        # 임시 파일을 남기지 않는다
    # 파일에 없는 대역은 "잴 수 없음"
    assert not any(r["measured"] for r in survey.run(dev, "wifi-5g")["channels"])


def test_bad_requests_are_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(survey, "sessions_dir", lambda: tmp_path)
    with pytest.raises(survey.SurveyError):
        survey.run("no-such-device", "wifi-5g")
    dev = simulated_id()
    with pytest.raises(survey.SurveyError):
        survey.run(dev, "nope")
    with pytest.raises(survey.SurveyError):
        survey.run(dev, "custom", center_hz=1e9, span_hz=100e6, step_hz=1e6)


def test_survey_and_probe_use_receive_calls_only():
    import re
    from pathlib import Path
    banned = re.compile(r"SOAPY_SDR_TX|writeStream|tx_stream|\.transmit\(|\bsend_iq\b", re.I)
    for name in ("survey.py", "devices.py"):
        assert not banned.search((Path(survey.__file__).parent / name).read_text(encoding="utf-8"))


def test_spectrum_view_of_simulated_device_matches_its_file(tmp_path, monkeypatch):
    monkeypatch.setattr(survey, "sessions_dir", lambda: tmp_path)
    dev = simulated_id()
    file = survey.describe(dev)["capture"]
    out = survey.spectrum(dev)
    assert out["fixed_tuning"] and out["center_hz"] == file["center_freq_hz"] and out["sample_rate_hz"] == file["sample_rate_hz"]
    n = survey.VIEW_POINTS
    assert len(out["freq_hz"]) == len(out["mean_db"]) == len(out["max_db"]) == n
    assert abs(out["freq_hz"][0] - (file["center_freq_hz"] - file["sample_rate_hz"] / 2 + out["bin_hz"] / 2)) < 1
    assert abs((out["freq_hz"][-1] - out["freq_hz"][0]) - (file["sample_rate_hz"] - out["bin_hz"])) < 1
    assert all(mx >= mean - 0.01 for mx, mean in zip(out["max_db"], out["mean_db"], strict=True))
    # 점들의 세기를 다 더하면 전체 세기
    assert abs(10 * np.log10(sum(10 ** (v / 10) for v in out["mean_db"])) - out["total_dbfs"]) < 0.1
    fall = out["waterfall"]
    assert len(fall["values"]) == fall["rows"] and all(len(r) == fall["cols"] for r in fall["values"])
    flat = [v for r in fall["values"] for v in r]
    assert min(flat) == 0 and max(flat) == 1


def test_spectrum_view_checks_what_a_real_device_can_do(monkeypatch):
    dev = {"id": "driver=x", "driver": "x", "freq_min_hz": 70e6, "freq_max_hz": 6e9, "max_sample_rate_hz": 56e6}
    monkeypatch.setattr(devices, "find_device", lambda _id: dev)
    for kw, word in (({}, "넣어"), ({"center_hz": 7e9, "bandwidth_hz": 20e6}, "주파수"), ({"center_hz": 2.4e9, "bandwidth_hz": 80e6}, "최대 56"),
                     ({"center_hz": 2.4e9, "bandwidth_hz": 1e3}, "이상")):
        with pytest.raises(survey.SurveyError, match=word):
            survey.spectrum("driver=x", **kw)


def test_spectrum_view_of_a_tuned_device_reports_what_the_device_actually_used(tmp_path, monkeypatch):
    """실제 장비 경로: 요청한 값이 아니라 장비가 실제로 맞춘 가운데 주파수·샘플레이트로 축을 만든다."""
    from nrtrail import sigmf
    monkeypatch.setattr(survey, "sessions_dir", lambda: tmp_path)
    dev = {"id": "driver=x", "driver": "x", "freq_min_hz": 70e6, "freq_max_hz": 6e9, "max_sample_rate_hz": 56e6}
    monkeypatch.setattr(devices, "find_device", lambda _id: dev)
    asked = []
    TONE = 5e6 + RATE / survey.VIEW_POINTS / 2   # 그림의 한 점 한가운데에 오도록(경계에 걸치면 두 점으로 갈린다)

    def fake_capture(_dev_id, req, out_meta):
        asked.append((req.center_freq_hz, req.sample_rate_hz, req.gain_db))
        sigmf.write_capture(out_meta, tone_plus_noise(TONE, 0.1), sample_rate_hz=RATE, center_freq_hz=2.4371e9, source="device")
        return sigmf.read_meta(out_meta)

    monkeypatch.setattr(devices, "capture", fake_capture)
    out = survey.spectrum("driver=x", center_hz=2.437e9, bandwidth_hz=20e6, gain_db=30)
    assert asked == [(2.437e9, 20e6, 30)]
    assert out["center_hz"] == 2.4371e9 and not out["fixed_tuning"]
    best = out["freq_hz"][int(np.argmax(out["mean_db"]))]
    assert abs(best - (2.4371e9 + TONE)) <= out["bin_hz"] / 2 + 1
    assert abs(max(out["mean_db"]) - (-20.0)) < 0.5
