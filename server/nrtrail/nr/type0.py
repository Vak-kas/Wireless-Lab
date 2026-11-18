"""CORESET0와 Type0-PDCCH 감시 시점 (SIB1을 어디서 찾는가).

근거: TS 38.213 13절. 표는 tools/extract_38213.py 가 원문에서 뽑은 pipeline/tables/ts38213_13.json 을 쓴다.
FR1, 다중화 패턴 1만 다룬다(FR2와 패턴 2·3은 범위 밖).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from math import floor

from ..paths import PIPELINE


@lru_cache(maxsize=1)
def tables() -> dict:
    return json.loads((PIPELINE / "tables" / "ts38213_13.json").read_text(encoding="utf-8"))


@dataclass(frozen=True)
class Coreset0:
    table: str
    index: int
    pattern: int
    n_rb: int
    n_sym: int
    offset_rb: int
    scs_khz: int

    @property
    def bandwidth_hz(self) -> int:
        return self.n_rb * 12 * self.scs_khz * 1000


class Type0Error(ValueError):
    pass


def coreset0_table_name(ssb_scs_khz: int, pdcch_scs_khz: int, min_channel_bw_mhz: int) -> str:
    """{SSB SCS, PDCCH SCS}와 대역의 최소 채널 대역폭으로 쓸 표를 고른다. TS 38.213 13 (표 13-1 ~ 13-6의 제목)."""
    cond = "min_bw_40" if min_channel_bw_mhz >= 40 else "min_bw_5_or_10"
    for name, t in tables()["coreset0"].items():
        if (t["ssb_scs_khz"], t["pdcch_scs_khz"]) == (ssb_scs_khz, pdcch_scs_khz) and (
                t["condition"] == cond or ssb_scs_khz == 15):
            return name
    raise Type0Error(f"지원하지 않는 SCS 조합: SSB {ssb_scs_khz} kHz, PDCCH {pdcch_scs_khz} kHz")


def coreset0(index: int, ssb_scs_khz: int, pdcch_scs_khz: int, min_channel_bw_mhz: int = 5) -> Coreset0:
    name = coreset0_table_name(ssb_scs_khz, pdcch_scs_khz, min_channel_bw_mhz)
    row = tables()["coreset0"][name]["rows"][index]
    if row is None:
        raise Type0Error(f"표 {name}의 {index}번은 예약(Reserved) 값입니다")
    if row["pattern"] != 1:
        raise Type0Error("다중화 패턴 1만 지원합니다")
    return Coreset0(name, index, row["pattern"], row["n_rb"], row["n_sym"], row["offset_rb"], pdcch_scs_khz)


@dataclass(frozen=True)
class Monitoring:
    index: int
    o: float
    sets_per_slot: int
    m: float
    first_symbol: int
    slot: int          # n0
    frame_parity: int  # SFN_C mod 2
    slots_per_frame: int


def monitoring(index: int, ssb_index: int, pdcch_scs_khz: int, n_sym_coreset: int) -> Monitoring:
    """표 13-11과 n0 = (O*2^mu + floor(i*M)) mod N_slot^frame,mu. 감시는 n0부터 연속 두 슬롯. TS 38.213 13."""
    row = tables()["monitoring_pattern1_fr1"][index]
    mu = {15: 0, 30: 1, 60: 2}[pdcch_scs_khz]
    n_slots = 10 * 2 ** mu
    x = row["o"] * 2 ** mu + floor(ssb_index * row["m"])
    first = row["first_symbol"]
    if first == "alt":  # 짝수 i는 0, 홀수 i는 N_symb^CORESET
        first = 0 if ssb_index % 2 == 0 else n_sym_coreset
    return Monitoring(index, row["o"], row["sets_per_slot"], row["m"], int(first),
                      int(x) % n_slots, int(x // n_slots) % 2, n_slots)


def crb_grid_from_ssb(ss_ref_hz: float, ssb_scs_khz: int, k_ssb: int, offset_rb: int, pdcch_scs_khz: int) -> dict[str, float]:
    """SSB 위치에서 CORESET0의 주파수 위치를 구한다.

    SSB의 가장 낮은 부반송파는 SS_REF - 120*SCS_SSB. k_SSB는 '공통 RB N_CRB^SSB의 부반송파 0'에서
    'SSB의 부반송파 0'까지의 부반송파 수(FR1에서는 15 kHz 단위, TS 38.211 7.4.3.1).
    CORESET0의 가장 낮은 RB는 SSB의 첫 RB와 겹치는 공통 RB에서 offset_rb(PDCCH SCS 기준)만큼 아래다 (TS 38.213 13).
    """
    ssb_low = ss_ref_hz - 120 * ssb_scs_khz * 1000
    crb_ssb_low = ssb_low - k_ssb * 15_000
    coreset_low = crb_ssb_low - offset_rb * 12 * pdcch_scs_khz * 1000
    return {"ssb_low_hz": ssb_low, "crb_ssb_low_hz": crb_ssb_low, "coreset0_low_hz": coreset_low}
