"""실시간 그림의 줄에서 신호를 찾아 종류를 추정하는 것(signals)."""
import numpy as np
from nrtrail import signals


def row(rate, center, bumps, bins=256, floor=-80.0):
    """바닥이 floor 인 줄에, (가운데 Hz, 폭 Hz, 세기 dB) 들을 솟게 한 것. (평균 줄, 최대 줄)"""
    freq = center - rate / 2 + (np.arange(bins) + 0.5) * rate / bins
    mean = np.full(bins, floor)
    peak = np.full(bins, floor + 3)
    for mid, width, level in bumps:
        inside = np.abs(freq - mid) <= width / 2
        mean[inside] = level - 6
        peak[inside] = level
    return list(mean), list(peak)


def test_spans_are_found_above_the_floor_and_small_gaps_are_joined():
    mean, peak = row(20e6, 5745e6, [(5745e6, 16.6e6, -40)])
    hole = len(peak) // 2
    peak[hole:hole + 3] = [-80.0] * 3                              # OFDM 가운데의 빈 부반송파(약 0.23 MHz)
    found = signals.spans(mean, peak, 5745e6, 20e6)
    assert len(found) == 1 and abs((found[0]["hi_hz"] - found[0]["lo_hz"]) - 16.6e6) < 0.3e6 and found[0]["peak_db"] == -40
    assert signals.spans(*row(20e6, 5745e6, []), 5745e6, 20e6) == []        # 바닥뿐이면 아무것도 없다
    two = signals.spans(*row(20e6, 2440e6, [(2434e6, 1e6, -50), (2446e6, 1e6, -50)]), 2440e6, 20e6)
    assert len(two) == 2                                            # 멀리 떨어진 것은 잇지 않는다


def test_kinds_are_guessed_from_width_and_band():
    g = signals.guess
    assert g(5745e6 - 8.3e6, 5745e6 + 8.3e6, 5745e6, 20e6) == {"kind": "wifi", "channel": "ch149"}
    assert g(2437e6 - 8.3e6, 2437e6 + 8.3e6, 2437e6, 20e6) == {"kind": "wifi", "channel": "ch6"}
    assert g(2402e6 - 0.5e6, 2402e6 + 0.5e6, 2410e6, 20e6) == {"kind": "bt", "channel": 37}          # BLE 광고 채널 37
    assert g(433.92e6 - 20e3, 433.92e6 + 20e3, 434.2e6, 2e6) == {"kind": "narrow"}
    assert g(5745e6 - 2e6, 5745e6 + 2e6, 5745e6, 4e6)["kind"] == "wide"                              # 받는 폭을 다 채운다
    assert g(900e6 - 3e6, 900e6 + 3e6, 902e6, 20e6) == {"kind": "unknown"}
    assert g(1000e6 - 50e3, 1000e6 + 50e3, 1000e6, 20e6) == {"kind": "dc"}                           # 가운데 주파수의 뾰족한 것
    assert g(900e6 - 8.3e6, 900e6 + 8.3e6, 900e6, 20e6)["kind"] == "unknown"                         # Wi-Fi 대역이 아니면 폭이 같아도 Wi-Fi 라 하지 않는다


def test_tracker_groups_repeats_and_counts_how_often_each_was_seen():
    t = signals.Tracker(2440e6, 20e6)
    assert t.snapshot() == []
    for i in range(20):
        bumps = [(2437e6, 16.6e6, -40)] if i % 2 == 0 else []       # Wi-Fi: 두 줄에 한 번
        if i >= 18:
            bumps.append((2448e6, 1e6, -55))                         # 블루투스 계열: 마지막 두 줄에만(받는 범위 2430 ~ 2450 MHz 안)
        t.add(*row(20e6, 2440e6, bumps))
    out = {s["kind"]: s for s in t.snapshot()}
    assert set(out) == {"wifi", "bt"}
    assert out["wifi"]["channel"] == "ch6" and out["wifi"]["seen"] == 0.5 and out["wifi"]["now"] is False
    assert out["bt"]["channel"] == 21 and out["bt"]["seen"] == 0.1 and out["bt"]["now"] is True
    assert 15e6 <= out["wifi"]["width_hz"] <= 16.7e6 and out["wifi"]["above_floor_db"] > 30      # 왼쪽 끝이 받는 범위에 잘린다


def test_edge_specks_brief_glimpses_and_duplicates_are_tidied_away():
    """받는 범위 가장자리의 잡티는 버리고, 스쳐 간 것은 내놓지 않고, 같은 채널로 추정된 것은 하나로 합친다."""
    rate, center = 4e6, 2402e6
    edge = signals.spans(*row(rate, center, [(center - rate / 2 + 10e3, 30e3, -50)]), center, rate)
    assert edge == []
    t = signals.Tracker(center, rate)
    for i in range(100):
        bumps = []
        if i < 30:
            bumps.append((2402e6, 1.3e6, -50))                      # 블루투스 광고 채널 37: 폭이 넓게 잡힌 때
        elif i < 40:
            bumps.append((2402e6, 0.62e6, -60))                     # 같은 채널이 좁게 잡힌 때
        if i == 50:
            bumps.append((2403.3e6, 0.2e6, -60))                    # 한 줄에만 스친 것
        t.add(*row(rate, center, bumps))
    out = t.snapshot()
    assert [(s["kind"], s["channel"], s["seen"]) for s in out] == [("bt", 37, 0.4)]
