"""SDR 장비 계층: 장비 찾기, 능력표, 받기. **수신 전용**이다(송신은 tx.py).

구조 — 송신의 Signal/Transmitter 와 같은 모양이다

    Receiver                 "장비 한 종류에서 받는 법" (부모 클래스)
     ├─ SimulatedReceiver    저장해 둔 파일을 장비처럼 흘려보낸다
     ├─ SoapyReceiver        SoapySDR 로 붙는 장비
     ├─ UhdReceiver          USRP — C++ 프로그램 uhdio (usrp_uhd.py)
     ├─ MatlabUsrpReceiver   USRP — MATLAB (usrp_matlab.py)
     └─ LockedUsbReceiver    꽂힌 것을 알아보기만 (usb_sdr.py)

    RECEIVERS                장비 id 의 머리말 → Receiver. 설치에 따라 끼워진다(USRP 쪽 셋)
    receiver_for(id)         장비 id 로 맡은 Receiver 를 고른다

- 위쪽(화면, 풀이)은 장비 종류를 모른다. list_devices / capture / stream 만 부르면, 여기서 맡은 Receiver 에 넘긴다.
- 받은 것은 언제나 SigMF 파일로 나온다. 그래서 누가 받았든 푸는 쪽(MATLAB, 파이썬)은 같다.
- 새 장비 종류를 더하려면 Receiver 를 하나 쓰고 RECEIVERS 에 한 줄을 넣는다.
- 장비의 능력(주파수 범위, 최대 샘플레이트, 어느 단계까지 되는지)은 devices/capabilities.json 에 있다.
- 받은 뒤의 풀이는 여기 없다. 채널 세기(survey), 블루투스(ble), Wi-Fi(wifi), 기지국(stages), 실시간 풀이(streams)가 받은 파일을 읽는다.
- IQ 가 아니라 칩이 풀어 준 결과를 주는 장비(컴퓨터의 Wi-Fi·블루투스)는 adapters.py 에 있다.
- 이 모듈은 수신(RX) 스트림만 열고, 송신(TX) 방향 상수·함수는 어디에서도 쓰지 않는다
  (server/tests/test_devices.py 가 소스에서 TX 호출이 없음을 검사한다).
- SoapySDR 이 없어도 가져올 수 있다(모듈은 장비를 쓸 때만 불러온다). 긴 수신도 메모리에 다 올리지 않고 디스크에 바로 쓴다.
"""

from __future__ import annotations

import importlib
import importlib.util
import json
import threading
import time
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, ClassVar

import numpy as np

from . import sigmf
from .paths import DEVICES, GOLDEN

CHUNK = 1 << 16
SIM_PREFIX = "simulated:"


class DeviceError(RuntimeError):
    """사용자에게 보여줄 수 있는 장비 오류."""


class Receiver:
    """장비 한 종류에서 받는 법. 받은 것을 풀 줄은 모른다(받아서 SigMF 파일로 내놓기만 한다).

    장비 종류마다 자식 클래스가 하나 있다. 위쪽(화면, 풀이)은 장비 종류를 모르고 이 클래스의 함수만 부른다.

        Receiver
         ├─ SimulatedReceiver        저장해 둔 파일을 장비처럼 흘려보낸다          (이 파일)
         ├─ SoapyReceiver            SoapySDR 로 붙는 장비                          (이 파일)
         ├─ UhdReceiver              USRP — C++ 프로그램 uhdio 가 UHD 로 직접       (usrp_uhd.py)
         ├─ MatlabUsrpReceiver       USRP — MATLAB 의 USRP 지원 패키지로            (usrp_matlab.py)
         └─ LockedUsbReceiver        꽂힌 것을 알아보기만 한다(이 설치로는 못 씀)    (usb_sdr.py)

    자식이 채우는 것
        prefix       맡는 장비 id 의 머리말("usrp:" 등). None 이면 다른 쪽이 맡지 않은 나머지 전부
        continuous   끊김 없이 계속 받을 수 있는가
        list_found   지금 연결된 장비들
        capture      정해진 길이만큼 받기
        stream       멈추라고 할 때까지 받기 — 채우지 않으면 "capture 를 되풀이"하는 기본 동작을 쓴다(조각 사이에 틈이 생긴다)
        status/reset 장비 찾기의 상태와, 연결을 처음부터 다시 하기(해당하는 자식만)

    송신 쪽의 tx.Transmitter 와 짝이 되는 클래스다.
    """

    prefix: ClassVar[str | None] = None
    continuous: ClassVar[bool] = False

    def list_found(self, force: bool = False, wait_s: float = 0.0) -> list[dict[str, Any]]:
        """연결된 장비: [{"id", "label", "driver", "serial", …}]. force 면 기억해 둔 것을 쓰지 않고 다시 찾는다."""
        raise NotImplementedError

    def capture(self, dev_id: str, req: CaptureRequest, out_meta: Path) -> sigmf.Capture:
        """req.duration_s 만큼 받아 SigMF 로 쓴다."""
        raise NotImplementedError

    def stream(self, dev_id: str, spec: StreamSpec, folder: Path, on_segment: Any, stop: threading.Event, on_spectrum: Any = None) -> dict[str, Any]:
        """stop 이 설 때까지 받아 조각마다 on_segment(Segment) 를 부른다.

        기본 동작: "조각 길이만큼 받기(capture)"를 되풀이한다. 조각 사이에 받지 않는 틈이 생기므로 Segment.continuous 가 False 다.
        끊김 없이 받을 수 있는 자식(continuous = True)은 이 함수를 새로 쓴다.
        """
        index, first = 0, 0
        while not stop.is_set():
            began = time.monotonic()
            cap = self.capture(dev_id, CaptureRequest(spec.center_freq_hz, spec.sample_rate_hz, spec.segment_s, spec.gain_db, spec.antenna,
                                                      offset_index=index), folder / f"seg-{index:06d}.sigmf-meta")
            on_segment(Segment(index=index, capture=cap, first_sample=first, lost_samples=0, overflows=0, continuous=False))
            index, first = index + 1, first + cap.num_samples
            stop.wait(max(0.0, spec.segment_s - (time.monotonic() - began)))     # 파일을 읽는 모의 장비도 실제 시간에 맞춰 낸다
        return {"stopped": True, "segments": index, "samples": first, "lost": 0, "overflows": 0}

    def status(self) -> dict[str, Any] | None:
        """장비 찾기의 상태(찾는 중인지, 마지막에 왜 못 찾았는지). 뒤에서 찾는 자식만 돌려준다."""
        return None

    def reset(self) -> None:
        """장비 연결을 처음부터 다시 한다(해당하는 자식만)."""


# 설치에 따라 끼워지는 받는 쪽: 장비 id 의 머리말 → Receiver. (모의 장비와 SoapySDR 은 언제나 있다 — _receivers 참고)
# 새 장비 종류를 더하려면 Receiver 를 하나 쓰고 여기에 넣는다. 송신 쪽의 tx.TRANSMITTERS 와 같은 자리다.
RECEIVERS: dict[str, Receiver] = {}


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


def _receivers() -> list[Receiver]:
    """받는 쪽 전부, 물어보는 순서대로. 머리말이 없는 SoapySDR 은 "나머지 전부"를 맡으므로 맨 뒤에 둔다."""
    return [SimulatedReceiver(), *RECEIVERS.values(), SoapyReceiver()]


def receiver_for(dev_id: str) -> Receiver:
    """이 장비를 맡은 받는 쪽: 장비 id 의 머리말로 고른다."""
    for receiver in _receivers():
        if receiver.prefix is None or dev_id.startswith(receiver.prefix):
            return receiver
    raise DeviceError(f"device not found: {dev_id}")


def list_devices() -> list[dict[str, Any]]:
    """인식된 장비 목록. 받는 쪽마다 찾은 것을 모으고, 능력표(capabilities.json)의 값을 붙인다."""
    out = []
    for receiver in _receivers():
        try:
            found = receiver.list_found()
        except Exception:  # noqa: BLE001 — 한 쪽의 장비 찾기가 실패해도 나머지 목록은 보여 준다
            found = []
        for f in found:
            info = _info(f["id"], f["label"], f["driver"], capability_for(f["driver"], f["label"]), f.get("serial", ""))
            if f.get("needs"):
                info["needs"] = f["needs"]      # 알아봤지만 이 설치로는 쓸 수 없는 장비(예: "pro")
            if f.get("abilities"):
                info["abilities"] = f["abilities"]   # 장비가 스스로 알려 준 능력(범위, 기준 신호, GPS 모듈)
            if f.get("limits"):
                info["limits"] = f["limits"]         # 장비가 알려 준 숫자 한도(이득·주파수). 능력표의 값보다 이것을 믿는다
            out.append(info)
    # 실제 장비를 앞에 둔다(화면이 맨 앞 장비를 기본으로 고른다). 모의 장비는 뒤로.
    return sorted(out, key=lambda d: d["driver"] == "simulated")


def search_status() -> list[dict[str, Any]]:
    """장비를 뒤에서 찾는 쪽들의 상태(찾는 중인지, 마지막에 왜 못 찾았는지)."""
    out = []
    for receiver in RECEIVERS.values():
        try:
            state = receiver.status()
        except Exception as e:  # noqa: BLE001
            state = {"backend": "?", "searching": False, "found": 0, "error": str(e)}
        if state is not None:
            out.append(state)
    return out


def rescan() -> None:
    """지금 다시 찾기 시작한다(기다리지 않는다)."""
    for receiver in RECEIVERS.values():
        try:
            receiver.list_found(force=True, wait_s=0)
        except Exception:  # noqa: BLE001, S110 — 실패 이유는 search_status 에 남는다
            pass


def reset() -> None:
    """장비 연결을 처음부터 다시 한다(뒤에서 돈다. 진행은 search_status 로 본다)."""
    for receiver in RECEIVERS.values():
        try:
            receiver.reset()
        except Exception:  # noqa: BLE001, S110 — 실패 이유는 search_status 에 남는다
            pass


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


@dataclass
class StreamSpec:
    """계속 받기의 조건. 조각(segment) 하나의 길이가 풀이에 넘기는 단위다."""
    center_freq_hz: float
    sample_rate_hz: float
    gain_db: float | None = None
    antenna: str | None = None
    segment_s: float = 0.5
    spectrum_ms: float = 0.0     # 0 보다 크면, 받는 쪽이 이 간격마다 주파수별 세기 한 줄을 바로 계산해 준다(끊김 없이 받는 장비만)


@dataclass
class Segment:
    """계속 받기의 조각 하나(SigMF 파일). 조각들을 차례로 이으면 받은 신호 전체다."""
    index: int
    capture: sigmf.Capture
    first_sample: int        # 이 조각의 첫 샘플이 처음부터 몇 번째인가
    lost_samples: int        # 이 조각 안에서 놓쳐서 0 으로 채운 샘플 수
    overflows: int           # 이 조각을 받는 동안 장비가 "넘쳤다"고 알린 횟수
    continuous: bool         # True: 앞 조각과 끊김 없이 이어진다. False: 조각 사이에 받지 않은 틈이 있다


def can_stream(dev_id: str) -> bool:
    """이 장비를 맡은 쪽이 끊김 없이 받을 수 있는가(받으면서 그림용 스펙트럼도 바로 계산해 준다)."""
    try:
        return receiver_for(dev_id).continuous
    except DeviceError:
        return False


def stream(dev_id: str, spec: StreamSpec, folder: Path, on_segment: Any, stop: threading.Event, on_spectrum: Any = None) -> dict[str, Any]:
    """stop 이 설 때까지 받아 조각마다 on_segment(Segment) 를 부른다(이 함수는 그동안 돌아오지 않는다).
    on_spectrum 을 주고 spec.spectrum_ms 가 0 보다 크면, 그 간격마다 on_spectrum({"row", "sample", "mean", "max"}) 도 부른다(끊김 없이 받는 장비만).

    그 장비를 맡은 Receiver 에 맡긴다. 끊김 없이 받는 쪽(USRP 의 uhdio)은 그렇게 받고,
    그렇지 못한 쪽은 Receiver.stream 의 기본 동작("조각 길이만큼 받기"를 되풀이)으로 받는다.
    """
    folder.mkdir(parents=True, exist_ok=True)
    return receiver_for(dev_id).stream(dev_id, spec, folder, on_segment, stop, on_spectrum)


def capture(dev_id: str, req: CaptureRequest, out_meta: Path) -> sigmf.Capture:
    """장비에서 req.duration_s 만큼 받아 SigMF로 쓴다. 그 장비를 맡은 받는 쪽에 맡긴다."""
    out_meta.parent.mkdir(parents=True, exist_ok=True)
    cap: sigmf.Capture = receiver_for(dev_id).capture(dev_id, req, out_meta)
    return cap


class SimulatedReceiver(Receiver):
    """모의 장비: 저장해 둔 연습 신호(골든 캡처)마다 하나. 장비 없이 "장비로 받는 흐름"을 시험한다."""

    prefix = SIM_PREFIX

    def list_found(self, force: bool = False, wait_s: float = 0.0) -> list[dict[str, Any]]:
        label = capability_for("simulated")["label"]
        return [{"id": f"{SIM_PREFIX}{p.parent.name}", "label": f"{label} · {p.parent.name}", "driver": "simulated"}
                for p in sorted(GOLDEN.glob("*/capture.sigmf-meta"))]

    def capture(self, dev_id: str, req: CaptureRequest, out_meta: Path) -> sigmf.Capture:
        return _capture_simulated(dev_id, req, out_meta)


class SoapyReceiver(Receiver):
    """SoapySDR 로 붙는 장비. SoapySDR 이 없으면 아무것도 찾지 않는다. 장비 id 에 정해진 머리말이 없어 "나머지 전부"를 맡는다."""

    prefix = None

    def list_found(self, force: bool = False, wait_s: float = 0.0) -> list[dict[str, Any]]:
        if not soapy_available():
            return []
        soapy = importlib.import_module("SoapySDR")
        try:
            found = [dict(kw) for kw in soapy.Device.enumerate()]
        except Exception:  # noqa: BLE001 — 드라이버 모듈 문제로 나는 오류는 종류가 여럿이다. 목록만 비운다
            found = []
        out = []
        for kw in found:
            driver = str(kw.get("driver", ""))
            args = ",".join(f"{k}={v}" for k, v in sorted(kw.items()) if k in ("driver", "serial", "uri", "addr"))
            out.append({"id": args, "label": str(kw.get("label") or kw.get("product") or driver), "driver": driver,
                        "serial": str(kw.get("serial", ""))})
        return out

    def capture(self, dev_id: str, req: CaptureRequest, out_meta: Path) -> sigmf.Capture:
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
    하나라도 못 읽으면 그 항목만 빠진다."""
    if dev_id.startswith(SIM_PREFIX) or any(dev_id.startswith(p) for p in RECEIVERS) or not soapy_available():
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
