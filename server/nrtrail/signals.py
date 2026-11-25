"""실시간 그림의 줄(주파수별 세기)에서 "지금 어떤 신호가 보이는가"를 찾아 이름을 붙인다. 풀지는 않는다(모양만 본다).

하는 일
  1. 줄 하나에서 바닥보다 충분히 솟은 주파수 구간(span)들을 찾는다.
  2. 구간의 폭과 위치로 종류를 **추정**한다: Wi-Fi 20 MHz, 블루투스 계열, 좁은 신호, 받는 폭보다 넓은 신호 …
  3. 최근 몇 초의 줄들을 모아, 같은 자리에 되풀이해 보이는 것을 한 신호로 묶고 "얼마나 자주 보였는지"를 센다.

이것은 추정이다
    폭이 20 MHz 라고 Wi-Fi 인 것은 아니다. 여기서 붙인 이름은 "모양이 그렇다"는 뜻이고,
    실제로 그 신호인지는 풀이(streams 의 wifi·ble 풀이)가 프레임을 풀어야 확인된다. 화면은 둘을 구분해 보여 준다.

종류를 더 넣으려면 guess() 에 규칙을 한 줄 더한다(폭의 범위와 주파수 대역).

단위: 주파수는 Hz, 세기는 dBFS(장비가 표현할 수 있는 최대 크기를 0 dB 로 본 값. 절대 전력이 아니다).
"""

from __future__ import annotations

from collections import deque
from typing import Any

import numpy as np

from . import survey

RISE_DB = 12.0             # 바닥보다 이만큼 솟아야 신호로 본다
FLOOR_PERCENT = 10         # 줄 하나의 바닥: 평균 줄에서 아래쪽 10% 자리의 값(신호가 폭의 대부분을 채워도 빈 가장자리가 잡힌다)
MERGE_HZ = 400e3           # 이보다 좁은 틈은 한 신호로 잇는다(OFDM 신호 가운데의 빈 부반송파 등)
WINDOW_ROWS = 100          # 최근 이만큼의 줄을 본다(줄 하나가 50 ms 면 5 초)
MAX_SIGNALS = 6            # 화면에 내놓는 신호 수(자주·세게 보인 것부터)
MIN_SEEN = 0.05            # 최근 줄의 이 비율보다 적게 보였고 지금도 안 보이면 내놓지 않는다(스쳐 간 것)
EDGE_BINS = 3              # 받는 범위의 양 끝 이만큼 안에만 있는 좁은 것은 버린다(장비 필터의 가장자리에서 생기는 잡티)

WIFI_BANDS = ((2400e6, 2500e6), (5150e6, 5900e6), (5925e6, 7125e6))
ISM_2G4 = (2400e6, 2483.5e6)


def row_floor(mean: list[float]) -> float:
    """줄 하나에서 본 바닥(잡음 수준)."""
    return float(np.percentile(np.asarray(mean, dtype=np.float64), FLOOR_PERCENT)) if len(mean) else 0.0


def spans(mean: list[float], peak: list[float], center_hz: float, rate_hz: float, floor: float | None = None) -> list[dict[str, float]]:
    """줄 하나에서 솟은 구간들: [{"lo_hz", "hi_hz", "peak_db", "floor_db"}]. peak 는 그 줄 동안 가장 셌던 값의 줄이다.
    floor 를 주지 않으면 이 줄만 보고 바닥을 잡는다. Tracker 는 최근 줄들 가운데 가장 조용했던 때의 값을 준다."""
    top = np.asarray(peak, dtype=np.float64)
    bins = len(top)
    if bins == 0:
        return []
    if floor is None:
        floor = row_floor(mean)
    step = rate_hz / bins
    over = top > floor + RISE_DB
    edges = np.diff(np.concatenate([[0], over.astype(np.int8), [0]]))
    begins, ends = np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)        # 구간은 [begin, end)
    merged: list[list[int]] = []
    for b, e in zip(begins, ends, strict=True):
        if merged and (b - merged[-1][1]) * step <= MERGE_HZ:
            merged[-1][1] = int(e)
        else:
            merged.append([int(b), int(e)])
    left = center_hz - rate_hz / 2
    inside = [(b, e) for b, e in merged if not (e <= EDGE_BINS or b >= bins - EDGE_BINS)]
    return [{"lo_hz": left + b * step, "hi_hz": left + e * step, "peak_db": float(top[b:e].max()), "floor_db": floor} for b, e in inside]


def wifi_channel(center_hz: float) -> str | None:
    """이 주파수가 Wi-Fi 20 MHz 채널의 가운데에서 2.5 MHz 안이면 그 채널 이름."""
    best: tuple[float, str] | None = None
    for plan in ("wifi-2g4", "wifi-5g", "wifi-6g"):
        for name, freq, _ in survey.PLANS[plan]["channels"]:
            off = abs(freq - center_hz)
            if off <= 2.5e6 and (best is None or off < best[0]):
                best = (off, str(name))
    return best[1] if best else None


def ble_channel(center_hz: float) -> int | None:
    """이 주파수가 블루투스 LE 의 RF 채널(2402 + 2k MHz)에서 0.6 MHz 안이면 그 채널 번호."""
    k = round((center_hz - 2402e6) / 2e6)
    if 0 <= k <= 39 and abs(center_hz - (2402e6 + 2e6 * k)) <= 0.6e6:
        return int(survey.BLE_INDEX[k])
    return None


def guess(lo_hz: float, hi_hz: float, center_hz: float, rate_hz: float) -> dict[str, Any]:
    """구간 하나의 종류를 모양으로 추정한다. {"kind", "channel"?}.

    kind: "dc"     받는 장비 자체의 가운데 주파수 누설(신호가 아니다)
          "wifi"   Wi-Fi 대역에서 폭 15 ~ 22 MHz
          "bt"     2.4 GHz 대역에서 폭 0.5 ~ 3 MHz (블루투스·BLE·지그비 계열)
          "wide"   받는 폭을 거의 다 채운다(실제 신호는 더 넓을 수 있다)
          "narrow" 폭 0.5 MHz 미만
          "unknown" 그 밖
    """
    mid, width = (lo_hz + hi_hz) / 2, hi_hz - lo_hz
    step = rate_hz / 256
    if abs(mid - center_hz) <= 1.5 * step and width <= 3 * step:
        return {"kind": "dc"}
    in_wifi = any(a <= mid <= b for a, b in WIFI_BANDS)
    if in_wifi and 15e6 <= width <= 22e6:
        return {"kind": "wifi", "channel": wifi_channel(mid)}
    if width >= 0.9 * rate_hz:
        return {"kind": "wide", "channel": wifi_channel(center_hz) if in_wifi else None}
    if ISM_2G4[0] <= mid <= ISM_2G4[1] and 0.5e6 <= width <= 3e6:
        return {"kind": "bt", "channel": ble_channel(mid)}
    if width < 0.5e6:
        return {"kind": "narrow"}
    return {"kind": "unknown"}


class Tracker:
    """최근 줄들에서 본 구간을 모아, 같은 자리에 되풀이해 보이는 것을 한 신호로 묶는다."""

    def __init__(self, center_hz: float, rate_hz: float):
        self.center_hz = center_hz
        self.rate_hz = rate_hz
        self._rows: deque[list[dict[str, float]]] = deque(maxlen=WINDOW_ROWS)
        self._floors: deque[float] = deque(maxlen=WINDOW_ROWS)

    def add(self, mean: list[float], peak: list[float]) -> None:
        # 바닥은 최근 줄들 가운데 가장 조용했던 때의 것을 쓴다: 신호가 받는 폭을 다 채운 줄에서도 "솟았다"고 볼 수 있게.
        # (끊이지 않고 폭 전체를 채우는 신호는 조용한 때가 없어서 찾지 못한다 — 그것이 이 방법의 한계다.)
        self._floors.append(row_floor(mean))
        self._rows.append(spans(mean, peak, self.center_hz, self.rate_hz, min(self._floors)))

    def snapshot(self) -> list[dict[str, Any]]:
        """지금 보이는 신호들. seen 은 최근 줄 가운데 이 신호가 보인 비율(0 ~ 1), now 는 마지막 줄에도 보였는가."""
        rows = list(self._rows)
        if not rows:
            return []
        groups: list[dict[str, Any]] = []
        for index, row in enumerate(rows):
            for s in row:
                mid, width = (s["lo_hz"] + s["hi_hz"]) / 2, s["hi_hz"] - s["lo_hz"]
                home = next((g for g in groups if abs(g["mid"] - mid) <= max(0.5e6, 0.25 * g["width"]) and 0.6 * g["width"] <= width <= 1.7 * g["width"]), None)
                if home is None:
                    home = {"mid": mid, "width": width, "lo": [], "hi": [], "peak": [], "rows": set()}
                    groups.append(home)
                home["lo"].append(s["lo_hz"])
                home["hi"].append(s["hi_hz"])
                home["peak"].append(s["peak_db"])
                home["rows"].add(index)
        floor = float(np.median([s["floor_db"] for row in rows for s in row])) if any(rows) else 0.0
        out = []
        for g in groups:
            lo, hi = float(np.median(g["lo"])), float(np.median(g["hi"]))
            out.append({"lo_hz": round(lo), "hi_hz": round(hi), "center_hz": round((lo + hi) / 2), "width_hz": round(hi - lo),
                        "peak_db": round(max(g["peak"]), 1), "above_floor_db": round(max(g["peak"]) - floor, 1),
                        "seen": round(len(g["rows"]) / len(rows), 2), "now": (len(rows) - 1) in g["rows"],
                        **guess(lo, hi, self.center_hz, self.rate_hz)})
        out.sort(key=lambda s: (s["kind"] == "dc", -s["seen"] * max(s["above_floor_db"], 1.0)))
        # 같은 종류·같은 채널로 추정된 것은 가장 뚜렷한 하나로 합친다(폭이 조금씩 달리 잡혀 둘로 나뉜 것)
        kept: list[dict[str, Any]] = []
        for sig in out:
            twin = next((k for k in kept if sig.get("channel") is not None and k["kind"] == sig["kind"] and k.get("channel") == sig.get("channel")), None)
            if twin is not None:
                twin["seen"] = round(min(1.0, twin["seen"] + sig["seen"]), 2)
                twin["now"] = twin["now"] or sig["now"]
            elif sig["seen"] >= MIN_SEEN or sig["now"]:
                kept.append(sig)
        return kept[:MAX_SIGNALS]
