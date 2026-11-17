"""자원 할당과 시간표 계산: RIV, locationAndBandwidth, SI 창, 단위 환산.

근거와 대조 상태
- RIV: TS 38.214 5.1.2.2.2 (원문 미대조. MATLAB 5G Toolbox 결과와 교차 확인은 M5에서)
- SI 창: TS 38.331 5.2.2.3.2 (원문 미대조)
- q-RxLevMin, n-TimingAdvanceOffset: TS 38.331 필드 설명, TS 38.133 표 7.1.2-2 (원문 미대조)
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from ..paths import PIPELINE

SI_PERIOD_FRAMES = {"rf8": 8, "rf16": 16, "rf32": 32, "rf64": 64, "rf128": 128, "rf256": 256, "rf512": 512}
SI_WINDOW_SLOTS = {"s5": 5, "s10": 10, "s20": 20, "s40": 40, "s80": 80, "s160": 160, "s320": 320, "s640": 640, "s1280": 1280}
N_TA_OFFSET = {"n0": 0, "n25600": 25600, "n39936": 39936}
SCS_KHZ = {"kHz15": 15, "kHz30": 30, "kHz60": 60, "kHz120": 120}
SSB_PERIOD_MS = {"ms5": 5, "ms10": 10, "ms20": 20, "ms40": 40, "ms80": 80, "ms160": 160}


def riv_decode(riv: int, n_bwp: int) -> tuple[int, int]:
    """RIV -> (RB_start, L_RBs). TS 38.214 5.1.2.2.2:
    L-1 <= floor(N/2) 이면 RIV = N(L-1) + RB_start, 아니면 RIV = N(N-L+1) + (N-1-RB_start)."""
    length = riv // n_bwp + 1
    start = riv % n_bwp
    if start + length > n_bwp:
        length = n_bwp - length + 2
        start = n_bwp - 1 - start
    return start, length


def riv_encode(start: int, length: int, n_bwp: int) -> int:
    if length - 1 <= n_bwp // 2:
        return n_bwp * (length - 1) + start
    return n_bwp * (n_bwp - length + 1) + (n_bwp - 1 - start)


@dataclass(frozen=True)
class SiWindow:
    x: int            # 창 시작까지의 슬롯 수
    slot: int         # a = x mod N
    frame_offset: int  # SFN mod T = floor(x / N)
    period_frames: int
    window_slots: int
    slots_per_frame: int


def si_window(order_or_position: int, window: str, period: str, slots_per_frame: int) -> SiWindow:
    """SI 창의 시작. x = (n-1)*w, a = x mod N, SFN mod T = floor(x/N). TS 38.331 5.2.2.3.2.

    schedulingInfoList의 메시지는 n = 목록 안의 순서(1부터),
    schedulingInfoList2-r17의 메시지는 n = si-WindowPosition-r17.
    """
    w = SI_WINDOW_SLOTS[window]
    t = SI_PERIOD_FRAMES[period]
    x = (order_or_position - 1) * w
    return SiWindow(x, x % slots_per_frame, x // slots_per_frame, t, w, slots_per_frame)


def plmn_string(mcc: list[int], mnc: list[int]) -> str:
    return "".join(map(str, mcc)) + "-" + "".join(map(str, mnc))


@lru_cache(maxsize=1)
def prach_tables() -> dict[str, Any]:
    data: dict[str, Any] = json.loads((PIPELINE / "tables" / "ts38211_prach.json").read_text(encoding="utf-8"))
    return data


def prach_config(index: int, paired: bool) -> dict[str, Any]:
    """prach-ConfigurationIndex -> 시간 영역 PRACH 기회. TS 38.211 표 6.3.3.2-2(FR1 FDD/SUL), 6.3.3.2-3(FR1 TDD). 원문에서 추출한 표."""
    key = "fr1_paired" if paired else "fr1_unpaired"
    row: dict[str, Any] = prach_tables()[key][index]
    return row | {"table": "6.3.3.2-2" if paired else "6.3.3.2-3"}


def point_a_hz(crb_ssb_low_hz: float, offset_to_point_a: int) -> float:
    """Point A = (SSB와 겹치는 가장 낮은 RB의 부반송파 0) - offsetToPointA x 12 x 15 kHz (FR1). TS 38.211 4.4.4.2 (원문 대조함)."""
    return crb_ssb_low_hz - offset_to_point_a * 12 * 15_000
