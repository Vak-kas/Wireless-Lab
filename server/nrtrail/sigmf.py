"""SigMF 입출력. IQ는 디스크에 두고 필요한 구간만 읽는다(긴 캡처를 메모리에 다 올리지 않는다).

지원 형식: cf32_le(복소 float32), ci16_le(복소 int16). 도구 전용 필드는 `nrtrail:` 접두사를 쓴다.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

DTYPES: dict[str, tuple[Any, int, float]] = {
    # 이름: (numpy 형식, 복소 샘플 하나의 바이트 수, 진폭 1.0에 해당하는 값)
    "cf32_le": (np.dtype("<f4"), 8, 1.0),
    "ci16_le": (np.dtype("<i2"), 4, 32768.0),
}


class SigmfError(ValueError):
    pass


@dataclass(frozen=True)
class Capture:
    meta_path: Path
    data_path: Path
    datatype: str
    sample_rate_hz: float
    center_freq_hz: float
    num_samples: int
    source: str | None
    testbed: bool
    extra: dict[str, Any]

    @property
    def duration_s(self) -> float:
        return self.num_samples / self.sample_rate_hz

    def read(self, start: int = 0, count: int | None = None) -> np.ndarray:
        """복소 샘플을 읽는다. 진폭은 풀스케일 1.0 기준으로 맞춘다."""
        dtype, size, scale = DTYPES[self.datatype]
        start = max(0, start)
        n = self.num_samples - start if count is None else min(count, self.num_samples - start)
        if n <= 0:
            return np.zeros(0, dtype=np.complex64)
        raw = np.fromfile(self.data_path, dtype=dtype, count=2 * n, offset=start * size)
        iq = raw.astype(np.float32).view(np.complex64)
        return iq if scale == 1.0 else iq / np.float32(scale)


def data_path_for(meta_path: Path) -> Path:
    name = meta_path.name
    if not name.endswith(".sigmf-meta"):
        raise SigmfError(".sigmf-meta 파일이 아닙니다")
    return meta_path.with_name(name[: -len(".sigmf-meta")] + ".sigmf-data")


def read_meta(meta_path: str | Path) -> Capture:
    meta_path = Path(meta_path)
    if not meta_path.is_file():
        raise SigmfError(f"파일이 없습니다: {meta_path}")
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        glob = meta["global"]
        datatype = glob["core:datatype"]
        rate = float(glob["core:sample_rate"])
        freq = float(meta["captures"][0]["core:frequency"])
    except (KeyError, IndexError, TypeError, ValueError) as e:
        raise SigmfError(f"SigMF 메타 형식이 맞지 않습니다: {e}") from e
    if datatype not in DTYPES:
        raise SigmfError(f"지원하지 않는 형식입니다: {datatype} (cf32_le, ci16_le만 지원)")
    if not rate > 0:
        raise SigmfError("core:sample_rate 가 0보다 커야 합니다")
    data = data_path_for(meta_path)
    if not data.is_file():
        raise SigmfError(f"데이터 파일이 없습니다: {data}")
    return Capture(
        meta_path=meta_path, data_path=data, datatype=datatype, sample_rate_hz=rate, center_freq_hz=freq,
        num_samples=data.stat().st_size // DTYPES[datatype][1],
        source=glob.get("nrtrail:source"), testbed=bool(glob.get("nrtrail:testbed", False)),
        extra={k: v for k, v in glob.items() if k.startswith("nrtrail:")},
    )


def write_meta(meta_path: str | Path, *, datatype: str, sample_rate_hz: float, center_freq_hz: float,
               source: str, testbed: bool = False, description: str = "", extra: dict[str, Any] | None = None) -> Path:
    """메타 파일만 쓴다. 데이터 파일은 호출한 쪽이 스트리밍으로 따로 쓴다."""
    if datatype not in DTYPES:
        raise SigmfError(f"지원하지 않는 형식입니다: {datatype}")
    meta_path = Path(meta_path)
    glob: dict[str, Any] = {
        "core:datatype": datatype, "core:sample_rate": sample_rate_hz, "core:version": "1.0.0",
        "core:description": description, "nrtrail:source": source, "nrtrail:testbed": testbed,
    }
    glob.update(extra or {})
    meta = {"global": glob, "captures": [{"core:sample_start": 0, "core:frequency": center_freq_hz}], "annotations": []}
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return meta_path


def write_capture(meta_path: str | Path, iq: np.ndarray, *, sample_rate_hz: float, center_freq_hz: float,
                  source: str, datatype: str = "cf32_le", **kw: Any) -> Capture:
    """작은 배열을 통째로 저장한다(테스트, 짧은 구간 잘라 저장)."""
    meta_path = Path(meta_path)
    dtype, _, scale = DTYPES[datatype]
    flat = np.ascontiguousarray(iq.astype(np.complex64)).view(np.float32) * np.float32(scale)
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    (np.round(flat) if datatype == "ci16_le" else flat).astype(dtype).tofile(data_path_for(meta_path))
    write_meta(meta_path, datatype=datatype, sample_rate_hz=sample_rate_hz, center_freq_hz=center_freq_hz, source=source, **kw)
    return read_meta(meta_path)
