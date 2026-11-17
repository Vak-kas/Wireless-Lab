"""대역 표(pipeline/bands.json)와 스캔 후보 나열."""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

from ..paths import PIPELINE
from . import raster
from . import ssb as nrssb


@lru_cache(maxsize=1)
def load_bands() -> list[dict[str, Any]]:
    return json.loads((PIPELINE / "bands.json").read_text(encoding="utf-8"))["bands"]


def band_by_id(band_id: str) -> dict[str, Any] | None:
    return next((b for b in load_bands() if b["id"] == band_id), None)


def bands_for_freq(freq_hz: float) -> list[dict[str, Any]]:
    """주파수가 속한 대역들. 좁은 대역(더 구체적인 것)을 먼저."""
    hits = [b for b in load_bands() if b["dl_lo_mhz"] * 1e6 <= freq_hz <= b["dl_hi_mhz"] * 1e6]
    return sorted(hits, key=lambda b: b["dl_hi_mhz"] - b["dl_lo_mhz"])


def cell_info(ss_ref_hz: float, gscn: int, ssb_scs_khz: int, pattern: str, band_id: str | None = None) -> dict[str, Any]:
    """따라갈 셀 하나에 대해 이후 단계가 쓰는 정보를 모은다."""
    band = (band_by_id(band_id) if band_id else None) or next(iter(bands_for_freq(ss_ref_hz)), None)
    paired = bool(band["paired"]) if band else True
    return {
        "gscn": gscn, "ss_ref_hz": ss_ref_hz, "ssb_scs_khz": ssb_scs_khz, "pattern": pattern,
        "band": band["id"] if band else None, "paired": paired,
        "min_bw_mhz": band["min_bw_mhz"] if band else 5, "ntn": bool(band["ntn"]) if band else False,
        "lmax": nrssb.lmax(pattern, ss_ref_hz, paired),
    }


def scan_candidates(center_hz: float, sample_rate_hz: float, band_id: str | None = None) -> list[dict[str, Any]]:
    """캡처 대역 안에 SSB 전체(240 부반송파)가 들어오는 GSCN 후보. 대역이 정한 SSB SCS·배치마다 하나씩."""
    usable = 0.9 * sample_rate_hz  # 가장자리는 필터 때문에 쓰지 않는다
    out: list[dict[str, Any]] = []
    for g in raster.gscn_range(center_hz - usable / 2, center_hz + usable / 2):
        band = (band_by_id(band_id) if band_id else None) or next(iter(bands_for_freq(g.ss_ref_hz)), None)
        options: list[dict[str, Any]] = band["ssb"] if band else [{"scs_khz": 15, "pattern": "A"}, {"scs_khz": 30, "pattern": "C"}]
        for opt in options:
            half = raster.ssb_bandwidth_hz(opt["scs_khz"]) / 2
            if abs(g.ss_ref_hz - center_hz) + half <= usable / 2:
                out.append({"gscn": g.gscn, "ss_ref_hz": g.ss_ref_hz, "ssb_scs_khz": opt["scs_khz"], "pattern": opt["pattern"]})
    return out
