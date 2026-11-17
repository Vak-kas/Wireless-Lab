"""장비 입력 세션의 수신: 단계 실행 전에 IQ를 받아 세션 폴더(captures/<n>.sigmf-*)에 저장한다. 수신 전용."""

from __future__ import annotations

from typing import Any

from . import devices
from .sessions import Session

DEFAULT_DURATION_S = 0.16
RECAPTURE_HINTS = ("gain_delta_db", "duration_scale", "widen", "cover_si_period")


def is_device(session: Session) -> bool:
    return session.source.get("kind") == "device"


def wants_recapture(params: dict[str, Any]) -> bool:
    return any(k in params for k in RECAPTURE_HINTS)


def apply_hints(session: Session, params: dict[str, Any]) -> None:
    """실패 화면의 버튼("이득 +10 dB로 다시 시도" 등)이 보낸 값을 수신 설정에 반영한다."""
    src = dict(session.source)
    dev = devices.find_device(src["device"])
    if "gain_delta_db" in params:
        src["gain_db"] = float(src.get("gain_db") or 30.0) + float(params["gain_delta_db"])
    if params.get("widen"):
        src["sample_rate_hz"] = min(float(src.get("sample_rate_hz") or 0) * 2, dev["max_sample_rate_hz"])
    cap = session.state.capture
    if "duration_scale" in params:
        cap["duration_s"] = min(float(cap.get("duration_s") or DEFAULT_DURATION_S) * float(params["duration_scale"]), 20.0)
    if params.get("cover_si_period"):
        win = session.state.results["sib1"].next_inputs.get("sib19_window") if "sib1" in session.state.results else None
        if win:
            cap["duration_s"] = min(win["period_frames"] * 0.010 + 0.05, 20.0)
    session.source = src


def acquire(session: Session, index: int = 0) -> None:
    """장비에서 받아 state.capture를 새 파일로 바꾼다."""
    src = session.source
    dev = devices.find_device(src["device"])
    cap = session.state.capture
    req = devices.CaptureRequest(
        center_freq_hz=float(src.get("center_freq_hz") or cap.get("center_freq_hz") or 0),
        sample_rate_hz=float(src.get("sample_rate_hz") or cap.get("sample_rate_hz") or 0),
        duration_s=float(cap.get("duration_s") or DEFAULT_DURATION_S), gain_db=src.get("gain_db"), antenna=src.get("antenna"),
        external_clock=bool(src.get("external_clock")), offset_index=index)
    problems = devices.check_request(dev, req.center_freq_hz, req.sample_rate_hz) if dev["driver"] != "simulated" else []
    if problems:
        raise devices.DeviceError(", ".join(problems))
    n = len(list((session.dir / "captures").glob("*.sigmf-meta"))) if (session.dir / "captures").exists() else 0
    got = devices.capture(src["device"], req, session.dir / "captures" / f"{n}.sigmf-meta")
    cap.update({"meta": str(got.meta_path), "data": str(got.data_path), "num_samples": got.num_samples,
                "center_freq_hz": got.center_freq_hz, "sample_rate_hz": got.sample_rate_hz})
