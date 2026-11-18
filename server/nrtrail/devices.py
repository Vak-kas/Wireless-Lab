"""장비 계층(SPEC 9절). **수신 전용**이다.

- 실제 장비는 SoapySDR로 통일한다. 이 모듈은 수신(RX) 스트림만 열고, 송신(TX) 방향 상수·함수는 어디에서도 쓰지 않는다
  (server/tests/test_devices.py가 소스에서 TX 호출이 없음을 검사한다).
- SoapySDR이 없어도 가져올 수 있다(모듈은 장비를 쓸 때만 불러온다). 장비가 없어도 시험되도록 SimulatedDevice를 둔다.
- 받은 IQ는 SigMF(cf32_le)로 디스크에 바로 흘려 쓴다. 긴 수신도 메모리에 다 올리지 않는다.
실제 장비로는 검증하지 못했다(이 컴퓨터에 SoapySDR·장비 없음) → docs/hardware-checklist.md 로 사람이 확인한다.
"""

from __future__ import annotations

import importlib
import importlib.util
import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np

from . import sigmf
from .paths import DEVICES, GOLDEN

CHUNK = 1 << 16
SIM_PREFIX = "simulated:"


class DeviceError(RuntimeError):
    """사용자에게 보여줄 수 있는 장비 오류."""


# SoapySDR 말고 다른 방식으로 장비를 찾고 받는 쪽을 끼우는 자리(예: MATLAB 의 USRP 지원 패키지).
# id 머리말 → 모듈. 모듈은 list_found() -> [{"id","label","driver","serial"}], capture(dev_id, req, out_meta) -> Capture 를 갖는다.
BACKENDS: dict[str, Any] = {}


@lru_cache(maxsize=1)
def capabilities() -> list[dict[str, Any]]:
    data: dict[str, Any] = json.loads((DEVICES / "capabilities.json").read_text(encoding="utf-8"))
    caps: list[dict[str, Any]] = data["devices"]
    return caps


def capability_for(driver: str, label: str = "") -> dict[str, Any]:
    """드라이버 이름(과 장비 표시 이름)으로 능력표 항목을 찾는다. 더 구체적인 항목이 먼저 온다."""
    text = f"{driver}:{label}".lower()
    for cap in capabilities():
        if any(m in text for m in cap["match"]):
            return cap
    return next(c for c in capabilities() if c["id"] == "unknown")


def soapy_available() -> bool:
    return importlib.util.find_spec("SoapySDR") is not None


def _info(dev_id: str, label: str, driver: str, cap: dict[str, Any], serial: str = "") -> dict[str, Any]:
    out = {"id": dev_id, "label": label, "driver": driver, "max_sample_rate_hz": cap["max_sample_rate_hz"],
           "freq_min_hz": cap["freq_min_hz"], "freq_max_hz": cap["freq_max_hz"], "bits": cap["bits"],
           "stages": cap["stages"], "note": cap["note"], "clock_ppm": cap["clock_ppm"], "capability": cap["id"]}
    if serial:
        out["serial"] = serial
    return out


def list_devices() -> list[dict[str, Any]]:
    """인식된 장비 목록. 모의 장비(골든 캡처마다 하나)가 항상 들어 있다."""
    sim = capability_for("simulated")
    out = [_info(f"{SIM_PREFIX}{p.parent.name}", f"{sim['label']} · {p.parent.name}", "simulated", sim)
           for p in sorted(GOLDEN.glob("*/capture.sigmf-meta"))]
    if soapy_available():
        soapy = importlib.import_module("SoapySDR")
        try:
            found = [dict(kw) for kw in soapy.Device.enumerate()]
        except Exception:  # noqa: BLE001 — 드라이버 모듈 문제로 나는 오류는 종류가 여럿이다. 목록만 비운다
            found = []
        for kw in found:
            driver = str(kw.get("driver", ""))
            label = str(kw.get("label") or kw.get("product") or driver)
            args = ",".join(f"{k}={v}" for k, v in sorted(kw.items()) if k in ("driver", "serial", "uri", "addr"))
            out.append(_info(args, label, driver, capability_for(driver, label), str(kw.get("serial", ""))))
    for backend in BACKENDS.values():
        try:
            found = backend.list_found()
        except Exception:  # noqa: BLE001 — 장비 찾기가 실패해도 나머지 목록은 보여 준다
            found = []
        for f in found:
            out.append(_info(f["id"], f["label"], f["driver"], capability_for(f["driver"], f["label"]), f.get("serial", "")))
    # 실제 장비를 앞에 둔다(화면이 맨 앞 장비를 기본으로 고른다). 모의 장비는 뒤로.
    return sorted(out, key=lambda d: d["driver"] == "simulated")


def find_device(dev_id: str) -> dict[str, Any]:
    for d in list_devices():
        if d["id"] == dev_id:
            return d
    raise DeviceError(f"device not found: {dev_id}")


def check_request(dev: dict[str, Any], center_hz: float, rate_hz: float) -> list[str]:
    """요구 조건과 능력표를 비교해 문제 코드를 돌려준다(빈 목록이면 괜찮음)."""
    problems = []
    if not dev["freq_min_hz"] <= center_hz <= dev["freq_max_hz"]:
        problems.append("FREQ_OUT_OF_RANGE")
    if rate_hz > dev["max_sample_rate_hz"]:
        problems.append("RATE_TOO_HIGH")
    return problems


def cfo_search_hz(dev: dict[str, Any], center_hz: float, base_hz: float) -> float:
    """장비 클럭 오차(ppm)로 생길 수 있는 주파수 오차까지 덮도록 CFO 탐색 범위를 넓힌다 (SPEC 16절)."""
    return max(base_hz, base_hz + dev.get("clock_ppm", 0) * 1e-6 * center_hz)


@dataclass
class CaptureRequest:
    center_freq_hz: float
    sample_rate_hz: float
    duration_s: float
    gain_db: float | None = None
    antenna: str | None = None
    external_clock: bool = False
    offset_index: int = 0   # 모의 장비: 몇 번째 수신인지(파일의 뒤쪽 구간을 흘려보낸다)


def capture(dev_id: str, req: CaptureRequest, out_meta: Path) -> sigmf.Capture:
    """장비에서 req.duration_s 만큼 받아 SigMF로 쓴다."""
    out_meta.parent.mkdir(parents=True, exist_ok=True)
    if dev_id.startswith(SIM_PREFIX):
        return _capture_simulated(dev_id, req, out_meta)
    for prefix, backend in BACKENDS.items():
        if dev_id.startswith(prefix):
            cap: sigmf.Capture = backend.capture(dev_id, req, out_meta)
            return cap
    return _capture_soapy(dev_id, req, out_meta)


def _capture_simulated(dev_id: str, req: CaptureRequest, out_meta: Path) -> sigmf.Capture:
    """SimulatedDevice: 저장 파일을 조각내어 장비처럼 흘려보낸다. 중심 주파수·샘플레이트는 파일의 것을 따른다."""
    src_meta = GOLDEN / dev_id[len(SIM_PREFIX):] / "capture.sigmf-meta"
    if not src_meta.exists():
        raise DeviceError(f"device not found: {dev_id}")
    src = sigmf.read_meta(src_meta)
    want = min(src.num_samples, max(1, round(req.duration_s * src.sample_rate_hz)))
    data_path = sigmf.data_path_for(out_meta)
    with data_path.open("wb") as f:
        done = 0
        while done < want:
            n = min(CHUNK, want - done)
            f.write(np.asarray(src.read(done, n), dtype="<c8").tobytes())
            done += n
    sigmf.write_meta(out_meta, sample_rate_hz=src.sample_rate_hz, center_freq_hz=src.center_freq_hz, datatype="cf32_le",
                     source="device", extra={"nrtrail:device": dev_id})
    return sigmf.read_meta(out_meta)


def _capture_soapy(dev_id: str, req: CaptureRequest, out_meta: Path) -> sigmf.Capture:
    if not soapy_available():
        raise DeviceError("SoapySDR is not installed")
    soapy = importlib.import_module("SoapySDR")
    rx = soapy.SOAPY_SDR_RX  # 수신 방향만 쓴다
    dev = soapy.Device(dict(kv.split("=", 1) for kv in dev_id.split(",") if "=" in kv))
    stream = None
    try:
        if req.external_clock:
            dev.setClockSource("external")
        dev.setSampleRate(rx, 0, req.sample_rate_hz)
        dev.setFrequency(rx, 0, req.center_freq_hz)
        if req.gain_db is not None:
            dev.setGain(rx, 0, req.gain_db)
        if req.antenna:
            dev.setAntenna(rx, 0, req.antenna)
        rate = float(dev.getSampleRate(rx, 0))
        centre = float(dev.getFrequency(rx, 0))
        stream = dev.setupStream(rx, soapy.SOAPY_SDR_CF32)
        dev.activateStream(stream)
        want = round(req.duration_s * rate)
        buf = np.zeros(CHUNK, dtype=np.complex64)
        got, errors = 0, 0
        with sigmf.data_path_for(out_meta).open("wb") as f:
            while got < want:
                sr = dev.readStream(stream, [buf], min(CHUNK, want - got), timeoutUs=1_000_000)
                if sr.ret > 0:
                    f.write(buf[:sr.ret].tobytes())
                    got += sr.ret
                else:
                    errors += 1
                    if errors > 50:
                        raise DeviceError(f"device stopped delivering samples (code {sr.ret})")
    finally:
        if stream is not None:
            dev.deactivateStream(stream)
            dev.closeStream(stream)
    sigmf.write_meta(out_meta, sample_rate_hz=rate, center_freq_hz=centre, datatype="cf32_le", source="device",
                     extra={"nrtrail:device": dev_id, "nrtrail:gain_db": req.gain_db})
    return sigmf.read_meta(out_meta)


def probe(dev_id: str) -> dict[str, Any]:
    """장비가 직접 알려 주는 값(하드웨어 정보, 안테나, 이득·샘플레이트·주파수 범위, 클럭 원천). 수신 쪽만 묻는다.
    하나라도 못 읽으면 그 항목만 빠진다. 실제 장비로는 검증하지 못했다."""
    if dev_id.startswith(SIM_PREFIX) or any(dev_id.startswith(p) for p in BACKENDS) or not soapy_available():
        return {}
    soapy = importlib.import_module("SoapySDR")
    rx = soapy.SOAPY_SDR_RX  # 수신 방향만 쓴다
    try:
        dev = soapy.Device(dict(kv.split("=", 1) for kv in dev_id.split(",") if "=" in kv))
    except Exception as e:  # noqa: BLE001 — 드라이버마다 오류 종류가 다르다
        return {"error": str(e)}
    out: dict[str, Any] = {}

    def put(key: str, fn: Any) -> None:
        try:
            out[key] = fn()
        except Exception:  # noqa: BLE001, S110 — 못 읽는 항목은 건너뛴다
            pass

    put("hardware", lambda: {str(k): str(v) for k, v in dict(dev.getHardwareInfo()).items()})
    put("hardware_key", lambda: str(dev.getHardwareKey()))
    put("rx_channels", lambda: int(dev.getNumChannels(rx)))
    put("antennas", lambda: [str(a) for a in dev.listAntennas(rx, 0)])
    put("gain_range_db", lambda: [float(dev.getGainRange(rx, 0).minimum()), float(dev.getGainRange(rx, 0).maximum())])
    put("sample_rate_range_hz", lambda: [min(float(r.minimum()) for r in dev.getSampleRateRange(rx, 0)),
                                         max(float(r.maximum()) for r in dev.getSampleRateRange(rx, 0))])
    put("freq_range_hz", lambda: [min(float(r.minimum()) for r in dev.getFrequencyRange(rx, 0)),
                                  max(float(r.maximum()) for r in dev.getFrequencyRange(rx, 0))])
    put("clock_sources", lambda: [str(c) for c in dev.listClockSources()])
    return out
