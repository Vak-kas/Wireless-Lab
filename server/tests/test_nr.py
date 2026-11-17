"""표준 계산(래스터, SSB 배치, CORESET0, 자원 할당)의 단위 테스트."""

import pytest
from nrtrail.nr import bands, raster, sched, type0
from nrtrail.nr import ssb as nrssb


@pytest.mark.parametrize("gscn,hz", [(5460, 2_184_150_000), (5459, 2_184_050_000), (5461, 2_184_250_000),
                                     (3855, 1_542_150_000), (7852, 3_508_320_000), (7499, 3_000_000_000), (2, 1_250_000)])
def test_gscn_to_freq(gscn, hz):
    assert raster.gscn_to_freq(gscn).ss_ref_hz == hz


def test_gscn_range_is_inverse_of_gscn_to_freq():
    for g in raster.gscn_range(2_170e6, 2_200e6) + raster.gscn_range(3_300e6, 3_320e6) + raster.gscn_range(2_995e6, 3_005e6):
        assert raster.gscn_to_freq(g.gscn).ss_ref_hz == g.ss_ref_hz
    assert [g.gscn for g in raster.gscn_range(2_184_000_000, 2_184_300_000)] == [5459, 5460, 5461]


def test_arfcn():
    assert raster.arfcn_to_freq(436830) == 2_184_150_000
    assert raster.arfcn_to_freq(633888) == 3_508_320_000
    assert raster.pci(167, 1) == 502 and raster.pci(335, 2) == 1007


def test_burst_patterns_match_ts38213_4_1():
    assert nrssb.burst_start_symbols("A", 2.1e9) == [2, 8, 16, 22]
    assert nrssb.burst_start_symbols("A", 3.5e9) == [2, 8, 16, 22, 30, 36, 44, 50]
    assert nrssb.burst_start_symbols("B", 2.1e9) == [4, 8, 16, 20]
    assert nrssb.burst_start_symbols("B", 3.5e9) == [4, 8, 16, 20, 32, 36, 44, 48]
    assert nrssb.burst_start_symbols("C", 1.8e9, paired=False) == [2, 8, 16, 22]
    assert nrssb.lmax("C", 3.5e9, paired=False) == 8 and nrssb.lmax("C", 2.5e9, paired=False) == 8
    assert nrssb.lmax("C", 2.5e9, paired=True) == 4


def test_symbol_timing_adds_up_to_half_frame():
    for scs, fs in ((15, 7.68e6), (30, 15.36e6), (30, 30.72e6)):
        n = 70 * scs // 15
        assert nrssb.symbol_start_in_half_frame(n, scs, fs) == pytest.approx(0.005 * fs)
    # 15 kHz, 7.68 Msps: FFT 512, CP 36 (첫 심볼 40)
    assert nrssb.symbol_start_in_half_frame(2, 15, 7.68e6) == 40 + 512 + 36 + 512


def test_pbch_payload_helpers():
    assert nrssb.full_sfn(25, 12) == 412
    assert nrssb.k_ssb(1, 7) == 23 and nrssb.sib1_present_fr1(23) and not nrssb.sib1_present_fr1(24)
    assert nrssb.split_ibar(5, 4) == (1, 1) and nrssb.split_ibar(5, 8) == (5, None)


def test_coreset0_tables_from_original():
    c = type0.coreset0(0, 15, 15)
    assert (c.table, c.n_rb, c.n_sym, c.offset_rb) == ("13-1", 24, 2, 0)
    c = type0.coreset0(6, 15, 15)
    assert (c.n_rb, c.n_sym, c.offset_rb, c.bandwidth_hz) == (48, 1, 12, 8_640_000)
    assert type0.coreset0(2, 30, 30, 10).table == "13-4"
    assert type0.coreset0(0, 30, 30, 40).table == "13-6"
    with pytest.raises(type0.Type0Error):
        type0.coreset0(15, 15, 15)


def test_type0_monitoring():
    m = type0.monitoring(0, 0, 15, 2)
    assert (m.slot, m.frame_parity, m.first_symbol) == (0, 0, 0)
    m = type0.monitoring(4, 3, 15, 2)   # O=5, M=1 -> (5 + 3) mod 10
    assert (m.o, m.m, m.slot) == (5, 1, 8)
    m = type0.monitoring(1, 3, 30, 2)   # 슬롯당 2개, M=1/2, 홀수 i는 CORESET 길이에서 시작
    assert (m.slot, m.first_symbol) == (1, 2)
    m = type0.monitoring(4, 7, 30, 1)   # (5*2 + 7) = 17 -> 슬롯 17
    assert (m.slot, m.frame_parity) == (17, 0)


@pytest.mark.parametrize("n", [24, 48, 275])
def test_riv_roundtrip(n):
    for start in range(0, n, 5):
        for length in range(1, n - start + 1, 3):
            assert sched.riv_decode(sched.riv_encode(start, length, n), n) == (start, length)


def test_si_window():
    w = sched.si_window(2, "s20", "rf8", 10)
    assert (w.x, w.slot, w.frame_offset) == (20, 0, 2)


def test_scan_candidates_fit_in_capture():
    c = bands.scan_candidates(2_184_150_000, 7_680_000, "n256")
    assert 5460 in [x["gscn"] for x in c] and all(x["pattern"] == "A" for x in c)
    assert all(abs(x["ss_ref_hz"] - 2_184_150_000) + 1.8e6 <= 0.45 * 7.68e6 for x in c)
    assert bands.cell_info(3_508_320_000, 7852, 30, "C")["lmax"] == 8


def test_sliv_roundtrip_and_known_values():
    assert sched.sliv_decode(53) == (2, 12) and sched.sliv_decode(67) == (2, 11) and sched.sliv_decode(40) == (1, 13)
    for s in range(14):
        for length in range(1, 15 - s):
            assert sched.sliv_decode(sched.sliv_encode(s, length)) == (s, length)


def test_configured_search_space_occasions():
    from nrtrail.nr import occasions

    rule = occasions.parse_search_space({"searchSpaceId": 3, "controlResourceSetId": 0, "monitoringSlotPeriodicityAndOffset": {"sl1": None},
                                         "monitoringSymbolsWithinSlot": "8000", "nrofCandidates": {"aggregationLevel4": "n2", "aggregationLevel8": "n0"}})
    assert rule == {"id": 3, "coreset_id": 0, "period_slots": 1, "offset_slots": 0, "duration_slots": 1, "first_symbols": [0], "candidates": {4: 2}}
    occ = occasions.search_space(100.0, 458, 7680 * 25, 7.68e6, 15, rule)       # 매 슬롯
    assert [(o["sfn"], o["slot"]) for o in occ[:3]] == [(458, 0), (458, 1), (458, 2)] and occ[1]["start_sample"] == 7780.0
    every5 = occasions.parse_search_space({"monitoringSlotPeriodicityAndOffset": {"sl5": 2}, "duration": 2, "monitoringSymbolsWithinSlot": "8100"})
    assert every5["first_symbols"] == [0, 7]
    occ = occasions.search_space(0.0, 0, 7680 * 20, 7.68e6, 15, every5)
    assert sorted({o["slot"] for o in occ if o["sfn"] == 0}) == [2, 3, 7, 8] and len(occ) == 16
    w = sched.SiWindow(10, 0, 1, 16, 10, 10)
    assert occasions.in_si_window({"sfn": 465, "slot": 9}, w) and not occasions.in_si_window({"sfn": 466, "slot": 0}, w)
