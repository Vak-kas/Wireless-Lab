"""주파수 상태 보기: 장비로 채널을 하나씩 받아 채널별 수신 세기를 잰다. **수신 전용**이다.

- 채널마다 짧게 받고(기본 20 ms) 주파수별 세기(PSD)를 구해, 채널 폭 안의 세기를 더한다.
- 값은 보정하지 않은 상대값(dBFS, |x| = 1 을 0 dB 로 봄)이다. dBm 이 아니다.
- 평균 / 중앙값 / 피크 세 가지를 낸다.
    평균   : 받은 시간 전체의 평균 세기
    중앙값 : 1 ms 구간별 세기의 중앙값. 띄엄띄엄 오는 신호(Wi-Fi 프레임)에는 덜 흔들리고, 계속 나오는 신호에는 평균과 같아진다.
    피크   : I/Q 중 가장 큰 샘플. 0 dB 에 가까우면 입력이 포화된 것이다.
- 모의 장비는 주파수를 바꿀 수 없다(저장 파일을 흘려보낼 뿐). 그래서 한 번 받은 것에서 채널들을 잘라 재고,
  파일에 담기지 않은 채널은 "잴 수 없음"으로 돌려준다.
채널 번호 → 중심 주파수: 2.4 GHz 는 2407 + 5·ch MHz, 5 GHz 는 5000 + 5·ch MHz, 6 GHz 는 5950 + 5·ch MHz
(IEEE 802.11 의 채널 번호 규칙).
묶음(40/80/160 MHz): 5 GHz 는 36, 100, 149 에서, 6 GHz 는 1 에서 차례로 센다. 2.4 GHz 는 채널이 5 MHz 간격으로 겹쳐서 묶지 않는다.
"""

from __future__ import annotations

import math
import tempfile
import time
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
VIEW_POINTS = 256         # 스펙트럼 그림의 가로 점 수
FALL_ROWS = 128           # 스펙트로그램의 주파수 칸 수
FALL_COLS = 100           # 스펙트로그램의 시간 칸 수(최대)
VIEW_DWELL_S = 0.1        # 들여다보기에서 한 번에 받는 시간(스펙트로그램의 가로 길이)
VIEW_MAX_SAMPLES = 1 << 22  # 들여다보기 계산에 쓰는 최대 샘플 수(넓은 대역은 앞부분만 쓴다)
SAVE_DEFAULT_S = 0.5      # 파일로 저장할 때의 기본 길이
SAVE_MAX_SAMPLES = 1 << 25  # 파일 하나의 최대 샘플 수(샘플당 4~8 바이트)
MIN_BANDWIDTH_HZ = 200e3

WIFI_5G_BLOCKS = [list(range(36, 65, 4)), list(range(100, 145, 4)), list(range(149, 166, 4))]
WIFI_5G = [c for block in WIFI_5G_BLOCKS for c in block]
WIFI_6G = list(range(1, 234, 4))
# RF 채널 k(2402 + 2k MHz) → BLE 채널 번호: 광고 채널 37, 38, 39 가 k = 0, 12, 39 에 있고 나머지에 0~36 을 차례로 매긴다
BLE_INDEX = {0: 37, 12: 38, 39: 39} | {k: k - 1 for k in range(1, 12)} | {k: k - 2 for k in range(13, 39)}
PLANS: dict[str, dict[str, Any]] = {
    "capture": {"simulated_only": True},
    "wifi-2g4": {"channels": [(f"ch{c}", (2407 + 5 * c) * 1e6, 20e6) for c in range(1, 14)], "widths": [20], "blocks": []},
    "wifi-5g": {"channels": [(f"ch{c}", (5000 + 5 * c) * 1e6, 20e6) for c in WIFI_5G], "widths": [20, 40, 80, 160],
                "blocks": WIFI_5G_BLOCKS},
    "wifi-6g": {"channels": [(f"ch{c}", (5950 + 5 * c) * 1e6, 20e6) for c in WIFI_6G], "widths": [20, 40, 80, 160],
                "blocks": [WIFI_6G]},
    # Bluetooth LE 의 RF 채널 40개(2 MHz 간격). 2402·2426·2480 MHz 가 광고 채널 37·38·39, 나머지가 데이터 채널 0~36 이다.
    "ble": {"channels": [(f"ch{BLE_INDEX[k]}", (2402 + 2 * k) * 1e6, 2e6) for k in range(40)], "widths": [2], "blocks": []},
    "custom": {},
}


def groups(plan: str, width_mhz: int) -> list[list[str]]:
    """width_mhz 폭으로 함께 쓰이는 20 MHz 채널 묶음. 묶음을 다 채우지 못하는 끝 채널(예: 5 GHz ch165)은 빠진다."""
    count = width_mhz // 20
    out: list[list[str]] = []
    for block in PLANS.get(plan, {}).get("blocks", []):
        for i in range(0, len(block) - count + 1, count):
            out.append([f"ch{c}" for c in block[i:i + count]])
    return out


class SurveyError(ValueError):
    """사용자에게 그대로 보여줄 문구."""


@dataclass
class Channel:
    name: str
    center_hz: float
    width_hz: float


def db(p: float) -> float:
    return round(10 * math.log10(p + EPS), 2)


def block_spectra(iq: np.ndarray, rate_hz: float, limit: int = MAX_SAMPLES) -> np.ndarray:
    """1 ms 구간마다의 주파수별 세기. 행 = 구간, 열 = 주파수 칸(낮은 주파수부터). 모든 칸을 더하면 그 구간의 평균 세기다."""
    x = np.asarray(iq, dtype=np.complex64)[:limit]
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
        reach = [dev["freq_min_hz"] <= c[1] <= dev["freq_max_hz"] for c in chans]
        if pid == "capture":
            ok = sim
        elif sim:
            ok = False       # 모의 장비는 파일에 담긴 대역만 볼 수 있다
        else:
            ok = any(reach) or not chans   # 일부만 닿아도 고를 수 있다. 닿지 않는 채널은 채널 맵에서 막는다
        out.append({"id": pid, "available": ok, "channels": len(chans), "widths": plan.get("widths", [20]),
                    "map": [{"name": c[0], "center_hz": c[1], "width_hz": c[2], "reachable": bool(r and not sim)}
                            for c, r in zip(chans, reach, strict=True)],
                    "groups": {str(w): groups(pid, w) for w in plan.get("widths", []) if w > 20}})
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
        step_hz: float | None = None, only: list[str] | None = None) -> dict[str, Any]:
    """채널별 세기를 한 바퀴 잰다. only 가 있으면 그 이름의 채널만 잰다."""
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
        if only is not None:
            channels = [c for c in channels if c.name in set(only)]
            if not channels:
                raise SurveyError("잴 채널을 하나 이상 고르세요.")
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
                try:
                    iq, cap = receive(ch.center_hz, rate)
                    rows.append(measure_channel(block_spectra(iq, cap.sample_rate_hz), _peak_dbfs(iq), ch, cap.center_freq_hz, cap.sample_rate_hz))
                except SurveyError as e:
                    # 채널 하나를 못 받아도(장비의 샘플 유실 등) 한 바퀴는 끝낸다. 그 채널만 "잴 수 없음"으로 둔다.
                    rows.append({"name": ch.name, "center_hz": ch.center_hz, "width_hz": ch.width_hz, "coverage": 0.0, "measured": False,
                                 "error": str(e)[:200]})
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
        fixed = sigmf.read_meta(devices.GOLDEN / dev_id[len(devices.SIM_PREFIX):] / "capture.sigmf-meta")
        for plan in out["plans"]:
            if plan["id"] == "capture":
                plan["map"] = [{"name": c.name, "center_hz": c.center_hz, "width_hz": c.width_hz, "reachable": True}
                               for c in channels_for("capture", dev, None, None, None, fixed)]
                plan["channels"] = len(plan["map"])
        src = sigmf.read_meta(devices.GOLDEN / dev_id[len(devices.SIM_PREFIX):] / "capture.sigmf-meta")
        out["capture"] = {"center_freq_hz": src.center_freq_hz, "sample_rate_hz": src.sample_rate_hz, "duration_s": round(src.duration_s, 3)}
    else:
        out["reported"] = devices.probe(dev_id)
    return out


def _check_tunable(dev: dict[str, Any], center_hz: float | None, bandwidth_hz: float | None) -> None:
    """이 장비가 그 가운데 주파수와 대역폭으로 받을 수 있는가. 못 받으면 이유를 말한다."""
    if not center_hz or not bandwidth_hz:
        raise SurveyError("가운데 주파수와 대역폭을 넣어 주세요.")
    if bandwidth_hz < MIN_BANDWIDTH_HZ:
        raise SurveyError(f"대역폭은 {MIN_BANDWIDTH_HZ / 1e6:g} MHz 이상이어야 합니다.")
    problems = devices.check_request(dev, center_hz, bandwidth_hz)
    if "FREQ_OUT_OF_RANGE" in problems:
        raise SurveyError(f"이 장비가 받을 수 있는 주파수는 {dev['freq_min_hz'] / 1e6:g} ~ {dev['freq_max_hz'] / 1e6:g} MHz 입니다.")
    if "RATE_TOO_HIGH" in problems:
        raise SurveyError(f"이 장비로 한 번에 볼 수 있는 대역폭은 최대 {dev['max_sample_rate_hz'] / 1e6:g} MHz 입니다.")


def save(dev_id: str, *, center_hz: float | None = None, bandwidth_hz: float | None = None, gain_db: float | None = None,
         seconds: float = SAVE_DEFAULT_S) -> dict[str, Any]:
    """그 대역을 seconds 동안 받아 SigMF 파일(sessions/saved/)로 남긴다. 받은 그대로이며 풀지 않는다."""
    try:
        dev = devices.find_device(dev_id)
    except devices.DeviceError as e:
        raise SurveyError("장비를 찾을 수 없습니다.") from e
    if dev["driver"] == "simulated":
        raise SurveyError("모의 장비는 이미 저장된 파일을 읽는 것이라 따로 저장하지 않습니다.")
    _check_tunable(dev, center_hz, bandwidth_hz)
    assert center_hz and bandwidth_hz
    longest = SAVE_MAX_SAMPLES / bandwidth_hz
    if not 0 < seconds <= longest:
        raise SurveyError(f"이 대역폭으로 저장할 수 있는 길이는 최대 {longest:.2f}초입니다.")
    folder = sessions_dir() / "saved"
    folder.mkdir(parents=True, exist_ok=True)
    meta = folder / f"{time.strftime('%Y%m%d-%H%M%S')}-{center_hz / 1e6:g}MHz.sigmf-meta"
    try:
        cap = devices.capture(dev_id, devices.CaptureRequest(center_hz, bandwidth_hz, seconds, gain_db), meta)
    except devices.DeviceError as e:
        raise SurveyError(f"장비에서 받지 못했습니다: {e}") from e
    return {"meta_path": str(cap.meta_path), "data_path": str(cap.data_path), "bytes": cap.data_path.stat().st_size,
            "datatype": cap.datatype, "num_samples": cap.num_samples, "seconds": round(cap.duration_s, 4),
            "center_hz": cap.center_freq_hz, "sample_rate_hz": cap.sample_rate_hz}


def spectrum(dev_id: str, *, center_hz: float | None = None, bandwidth_hz: float | None = None, gain_db: float | None = None) -> dict[str, Any]:
    """가운데 주파수와 대역폭을 정해 그 대역의 주파수별 세기를 본다(평균, 최대, 시간에 따른 변화).

    대역폭 = 받는 샘플레이트다(복소 표본이라 샘플레이트만큼의 폭이 보인다). 모의 장비는 파일의 대역 그대로다.
    """
    try:
        dev = devices.find_device(dev_id)
    except devices.DeviceError as e:
        raise SurveyError("장비를 찾을 수 없습니다.") from e
    sim = dev["driver"] == "simulated"
    if not sim:
        _check_tunable(dev, center_hz, bandwidth_hz)
    work = sessions_dir() / "survey"
    work.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=work) as tmp:
        try:
            cap = devices.capture(dev_id, devices.CaptureRequest(center_hz or 0.0, bandwidth_hz or 0.0, VIEW_DWELL_S, gain_db),
                                  Path(tmp) / "view.sigmf-meta")
        except devices.DeviceError as e:
            raise SurveyError(f"장비에서 받지 못했습니다: {e}") from e
        iq = np.asarray(cap.read(0, min(cap.num_samples, VIEW_MAX_SAMPLES)))
    rate, center = cap.sample_rate_hz, cap.center_freq_hz
    spectra = block_spectra(iq, rate, VIEW_MAX_SAMPLES)                                   # 구간 × NFFT
    group = NFFT // VIEW_POINTS
    grouped = spectra.reshape(len(spectra), VIEW_POINTS, group).sum(axis=2)   # 점 하나 = rate / VIEW_POINTS 폭의 세기
    step = rate / VIEW_POINTS
    freqs = center - rate / 2 + step * (np.arange(VIEW_POINTS) + 0.5)
    peak = _peak_dbfs(iq)
    # 워터폴: 주파수 칸 × 시간 칸, 가장 약한 칸을 0, 가장 센 칸을 1 로
    cols = min(FALL_COLS, len(spectra))
    per_col = len(spectra) // cols
    fall = spectra[: cols * per_col].reshape(cols, per_col, FALL_ROWS, NFFT // FALL_ROWS).sum(axis=3).mean(axis=1)   # 시간 × 주파수
    fall_db = 10 * np.log10(fall + EPS)
    lo, hi = float(fall_db.min()), float(fall_db.max())
    norm = (fall_db - lo) / max(hi - lo, 1e-9)
    return {
        "device": dev_id, "unit": "dBFS", "fixed_tuning": sim, "gain_db": gain_db,
        "center_hz": center, "sample_rate_hz": rate, "bin_hz": step, "dwell_s": round(len(iq) / rate, 4),
        "freq_hz": [round(float(f), 1) for f in freqs],
        "mean_db": [db(float(v)) for v in grouped.mean(axis=0)],
        "max_db": [db(float(v)) for v in grouped.max(axis=0)],
        "total_dbfs": db(float(spectra.sum(axis=1).mean())), "peak_dbfs": peak, "clipped": peak > CLIP_DBFS,
        "waterfall": {"rows": FALL_ROWS, "cols": cols, "values": [[round(float(v), 3) for v in row] for row in norm.T],
                      "col_ms": round(1e3 * per_col * max(1, round(BLOCK_S * rate / NFFT)) * NFFT / rate, 3),
                      "floor_db": round(lo, 1), "ceil_db": round(hi, 1)},
    }
