"""캡처 안에서 PDCCH를 들여다볼 시점(감시 시점)을 샘플 위치로 나열한다.

MATLAB에는 풀어낸 목록만 넘긴다(DECISIONS.md 14번). 근거: TS 38.213 13(Type0-PDCCH, 원문 대조함),
TS 38.331 5.2.2.3.2(SI 창, 원문 미대조).
"""

from __future__ import annotations

from typing import Any

from .sched import SiWindow

FRAME_S = 0.010


def slot_samples(scs_khz: int, sample_rate_hz: float) -> float:
    """슬롯 하나의 길이(샘플). 15 kHz는 1 ms, 30 kHz는 0.5 ms."""
    return sample_rate_hz * 0.001 * 15 / scs_khz


def type0(frame_start_sample: float, sfn_at_frame_start: int, n_samples: int, sample_rate_hz: float, scs_khz: int,
          slot: int, frame_parity: int, first_symbol: int, n_slots: int = 2) -> list[dict[str, Any]]:
    """Type0-PDCCH 감시 시점: SFN mod 2 = frame_parity 인 프레임의 슬롯 n0부터 연속 n_slots개.

    슬롯 전체(같은 슬롯의 PDSCH까지)가 캡처 안에 들어오는 것만 돌려준다.
    """
    frame_len = FRAME_S * sample_rate_hz
    slot_len = slot_samples(scs_khz, sample_rate_hz)
    slots_per_frame = round(frame_len / slot_len)
    out: list[dict[str, Any]] = []
    k = 0
    while frame_start_sample + k * frame_len < n_samples:
        sfn = (sfn_at_frame_start + k) % 1024
        for j in range(n_slots):
            s = slot + j
            sfn_j, slot_j = (sfn + s // slots_per_frame) % 1024, s % slots_per_frame
            if (sfn - frame_parity) % 2 != 0:
                continue
            start = frame_start_sample + k * frame_len + s * slot_len
            if start >= 0 and start + slot_len <= n_samples:
                out.append({"sfn": sfn_j, "slot": slot_j, "first_symbol": first_symbol, "start_sample": round(start, 3)})
        k += 1
    return out


def in_si_window(occ: dict[str, Any], w: SiWindow) -> bool:
    """감시 시점이 SI 창 안에 드는가. 창은 SFN mod T = frame_offset 인 프레임의 슬롯 a에서 시작해 w 슬롯 동안."""
    n = w.slots_per_frame
    pos = ((occ["sfn"] % w.period_frames) * n + occ["slot"] - (w.frame_offset * n + w.slot)) % (w.period_frames * n)
    return pos < w.window_slots
