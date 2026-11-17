"""단계 조립기 공통. 조립기는 엔진의 원시 결과(raw, docs/engine-contract.md)를 StageResult로 바꾼다."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..contracts_gen import Column as PlotColumn
from ..contracts_gen import Plot, PlotAnnotation, PlotAxis, PlotSeries, PlotTable

__all__ = ["Ctx", "Plot", "PlotAnnotation", "PlotAxis", "PlotSeries", "PlotTable", "PlotColumn", "thin"]


@dataclass
class Ctx:
    """조립에 필요한 주변 정보."""

    capture: dict[str, Any]                 # center_freq_hz, sample_rate_hz, source_kind
    cell: dict[str, Any] = field(default_factory=dict)      # 따라가는 셀: gscn, ss_ref_hz, ssb_scs_khz, pattern, band, paired, min_bw_mhz, ntn
    prior: dict[str, dict[str, Any]] = field(default_factory=dict)  # 앞 단계의 raw (decoded/resolved 포함)
    params: dict[str, Any] = field(default_factory=dict)
    settings: dict[str, Any] = field(default_factory=dict)


def thin(xs: list[float], ys: list[float], limit: int = 1200) -> tuple[list[float], list[float]]:
    """그림용 점 수 줄이기. 구간마다 가장 큰 값을 남겨 피크가 사라지지 않게 한다."""
    n = len(xs)
    if n <= limit:
        return xs, ys
    step = -(-n // limit)
    ox: list[float] = []
    oy: list[float] = []
    for i in range(0, n, step):
        j = max(range(i, min(i + step, n)), key=lambda k: ys[k])
        ox.append(xs[j])
        oy.append(ys[j])
    return ox, oy
