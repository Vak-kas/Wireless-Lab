"""주파수 상태 보기: 장비로 채널을 하나씩 받아 채널별 수신 세기를 잰다. **수신 전용**이다.

- 채널마다 짧게 받고(기본 20 ms) 주파수별 세기(PSD)를 구해, 채널 폭 안의 세기를 더한다.
- 값은 보정하지 않은 상대값(dBFS, |x| = 1 을 0 dB 로 봄)이다. dBm 이 아니다.
- 평균 / 중앙값 / 피크 세 가지를 낸다.
    평균   : 받은 시간 전체의 평균 세기
    중앙값 : 1 ms 구간별 세기의 중앙값. 띄엄띄엄 오는 신호(Wi-Fi 프레임)에는 덜 흔들리고, 계속 나오는 신호에는 평균과 같아진다.
    피크   : I/Q 중 가장 큰 샘플. 0 dB 에 가까우면 입력이 포화된 것이다.
- 모의 장비는 주파수를 바꿀 수 없다(저장 파일을 흘려보낼 뿐). 그래서 한 번 받은 것에서 채널들을 잘라 재고,
  파일에 담기지 않은 채널은 "잴 수 없음"으로 돌려준다.
채널 번호 → 중심 주파수: 2.4 GHz 는 2407 + 5·ch MHz, 5 GHz 는 5000 + 5·ch MHz (IEEE 802.11 의 채널 번호 규칙. 조항 번호는 원문으로 확인하지 못함).
실제 장비로는 검증하지 못했다.
"""

from __future__ import annotations

import math
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from . import devices, sigmf
from .paths import sessions_dir

NFFT = 1024
BLOCK_S = 1e-3            # 중앙값을 낼 때의 구간 길이
DWELL_S = 0.02            # 채널 하나를 받는 시간
MAX_SAMPLES = 1 << 20     # 채널 하나에서 계산에 쓰는 최대 샘플 수
MAX_CHANNELS = 64
MIN_COVERAGE = 0.9        # 채널 폭의 이만큼이 받은 대역 안에 있어야 잰 것으로 친다
CLIP_DBFS = -1.0
EPS = 1e-12

WIFI_5G = [*range(36, 65, 4), *range(100, 145, 4), *range(149, 166, 4)]
PLANS: dict[str, dict[str, Any]] = {
    "capture": {"simulated_only": True},
    "wifi-2g4": {"channels": [(f"ch{c}", (2407 + 5 * c) * 1e6, 20e6) for c in range(1, 14)]},
    "wifi-5g": {"channels": [(f"ch{c}", (5000 + 5 * c) * 1e6, 20e6) for c in WIFI_5G]},
    "custom": {},
}


class SurveyError(ValueError):
    """사용자에게 그대로 보여줄 문구."""


@dataclass
class Channel:
    name: str
    center_hz: float
    width_hz: float


def db(p: float) -> float:
    return round(10 * math.log10(p + EPS), 2)


def block_spectra(iq: np.ndarray, rate_hz: float) -> np.ndarray:
    """1 ms 구간마다의 주파수별 세기. 행 = 구간, 열 = 주파수 칸(낮은 주파수부터). 모든 칸을 더하면 그 구간의 평균 세기다."""
    x = np.asarray(iq, dtype=np.complex64)[:MAX_SAMPLES]
    x = x - x.mean()                                   # LO 누설로 중심 주파수에 생기는 DC 성분 제거
    n_frames = len(x) // NFFT
    if n_frames < 1:
        raise SurveyError("받은 신호가 너무 짧습니다.")
    win = np.hanning(NFFT).astype(np.float32)
    frames = x[: n_frames * NFFT].reshape(n_frames, NFFT) * win
    psd = np.abs(np.fft.fftshift(np.fft.fft(frames, axis=1), axes=1)) ** 2 / (NFFT * float(np.sum(win**2)))
    per_block = max(1, min(n_frames, round(BLOCK_S * rate_hz / NFFT)))
    n_blocks = n_frames // per_block
    out: np.ndarray = psd[: n_blocks * per_block].reshape(n_blocks, per_block, NFFT).mean(axis=1)
    return out


def measure_channel(spectra: np.ndarray, peak_dbfs: float, ch: Channel, center_hz: float, rate_hz: float) -> dict[str, Any]:
    """받은 대역(center ± rate/2)에서 채널 하나의 세기를 구한다."""
    lo, hi = ch.center_hz - ch.width_hz / 2, ch.center_hz + ch.width_hz / 2
    got_lo, got_hi = max(lo, center_hz - rate_hz / 2), min(hi, center_hz + rate_hz / 2)
    coverage = max(0.0, got_hi - got_lo) / ch.width_hz
    out: dict[str, Any] = {"name": ch.name, "center_hz": ch.center_hz, "width_hz": ch.width_hz, "coverage": round(coverage, 3),
                           "measured": coverage >= MIN_COVERAGE}
    if not out["measured"]:
        return out
    bin_hz = rate_hz / NFFT
    a = int(np.clip(math.floor((got_lo - (center_hz - rate_hz / 2)) / bin_hz), 0, NFFT - 1))
    b = int(np.clip(math.ceil((got_hi - (center_hz - rate_hz / 2)) / bin_hz), a + 1, NFFT))
    per_block = spectra[:, a:b].sum(axis=1)
    return out | {"mean_dbfs": db(float(per_block.mean())), "median_dbfs": db(float(np.median(per_block))),
                  "peak_dbfs": peak_dbfs, "clipped": peak_dbfs > CLIP_DBFS, "blocks": int(len(per_block))}


def _peak_dbfs(iq: np.ndarray) -> float:
    return round(20 * math.log10(float(max(np.abs(iq.real).max(), np.abs(iq.imag).max())) + EPS), 2)


def plans_for(dev: dict[str, Any]) -> list[dict[str, Any]]:
    """이 장비로 쓸 수 있는 측정 방식 목록."""
    sim = dev["driver"] == "simulated"
    out = []
    for pid, plan in PLANS.items():
        chans = plan.get("channels", [])
        if pid == "capture":
            ok = sim
        elif sim:
            ok = False       # 모의 장비는 파일에 담긴 대역만 볼 수 있다
        else:
            ok = all(dev["freq_min_hz"] <= c[1] <= dev["freq_max_hz"] for c in chans)
        out.append({"id": pid, "available": ok, "channels": len(chans)})
    return out


def channels_for(plan: str, dev: dict[str, Any], center_hz: float | None, span_hz: float | None, step_hz: float | None,
                 fixed: sigmf.Capture | None) -> list[Channel]:
    if plan not in PLANS:
        raise SurveyError(f"모르는 측정 방식입니다: {plan}")
    if plan == "capture":
        if fixed is None:
            raise SurveyError("이 방식은 모의 장비에서만 쓸 수 있습니다.")
        n = 16
        step = fixed.sample_rate_hz / n
        first = fixed.center_freq_hz - fixed.sample_rate_hz / 2 + step / 2
        return [Channel(f"{(first + i * step) / 1e6:.2f}", first + i * step, step) for i in range(n)]
    if plan == "custom":
        if not center_hz or not span_hz or not step_hz or span_hz <= 0 or step_hz <= 0:
            raise SurveyError("가운데 주파수, 폭, 간격을 넣어 주세요.")
        n = max(1, round(span_hz / step_hz))
        if n > MAX_CHANNELS:
            raise SurveyError(f"채널이 너무 많습니다(최대 {MAX_CHANNELS}개). 간격을 넓히세요.")
        first = center_hz - span_hz / 2 + step_hz / 2
        return [Channel(f"{(first + i * step_hz) / 1e6:.2f}", first + i * step_hz, step_hz) for i in range(n)]
    return [Channel(*c) for c in PLANS[plan]["channels"]]


def run(dev_id: str, plan: str, *, gain_db: float | None = None, center_hz: float | None = None, span_hz: float | None = None,
        step_hz: float | None = None) -> dict[str, Any]:
    """채널별 세기를 한 바퀴 잰다."""
    try:
        dev = devices.find_device(dev_id)
    except devices.DeviceError as e:
        raise SurveyError("장비를 찾을 수 없습니다.") from e
    sim = dev["driver"] == "simulated"
    work = sessions_dir() / "survey"
    work.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=work) as tmp:
        out_meta = Path(tmp) / "dwell.sigmf-meta"   # 채널마다 같은 파일에 덮어쓴다

        def receive(center: float, rate: float) -> tuple[np.ndarray, sigmf.Capture]:
            try:
                cap = devices.capture(dev_id, devices.CaptureRequest(center, rate, DWELL_S, gain_db), out_meta)
            except devices.DeviceError as e:
                raise SurveyError(f"장비에서 받지 못했습니다: {e}") from e
            return np.asarray(cap.read(0, min(cap.num_samples, MAX_SAMPLES))), cap

        fixed_iq, fixed = receive(0.0, 0.0) if sim else (None, None)
        channels = channels_for(plan, dev, center_hz, span_hz, step_hz, fixed)
        rows: list[dict[str, Any]] = []
        if fixed is not None and fixed_iq is not None:
            spectra, peak = block_spectra(fixed_iq, fixed.sample_rate_hz), _peak_dbfs(fixed_iq)
            rows = [measure_channel(spectra, peak, ch, fixed.center_freq_hz, fixed.sample_rate_hz) for ch in channels]
        else:
            for ch in channels:
                rate = min(float(dev["max_sample_rate_hz"]), max(ch.width_hz, 1e6))
                if devices.check_request(dev, ch.center_hz, rate):
                    rows.append({"name": ch.name, "center_hz": ch.center_hz, "width_hz": ch.width_hz, "coverage": 0.0, "measured": False})
                    continue
                iq, cap = receive(ch.center_hz, rate)
                rows.append(measure_channel(block_spectra(iq, cap.sample_rate_hz), _peak_dbfs(iq), ch, cap.center_freq_hz, cap.sample_rate_hz))
    return {"device": dev_id, "plan": plan, "unit": "dBFS", "dwell_s": DWELL_S, "gain_db": gain_db, "channels": rows,
            "fixed_tuning": sim}


def describe(dev_id: str) -> dict[str, Any]:
    """장비를 골랐을 때 보여줄 정보. 능력표의 값과, 장비가 직접 알려 주는 값(있으면)을 나눠 돌려준다."""
    try:
        dev = devices.find_device(dev_id)
    except devices.DeviceError as e:
        raise SurveyError("장비를 찾을 수 없습니다.") from e
    out: dict[str, Any] = {"device": dev, "plans": plans_for(dev), "reported": {}, "capture": None}
    if dev["driver"] == "simulated":
        src = sigmf.read_meta(devices.GOLDEN / dev_id[len(devices.SIM_PREFIX):] / "capture.sigmf-meta")
        out["capture"] = {"center_freq_hz": src.center_freq_hz, "sample_rate_hz": src.sample_rate_hz, "duration_s": round(src.duration_s, 3)}
    else:
        out["reported"] = devices.probe(dev_id)
    return out
