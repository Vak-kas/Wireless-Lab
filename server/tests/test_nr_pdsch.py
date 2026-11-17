"""DCI 1_0(SI-RNTI), 시간 자원 표, TBS. 기대값은 MATLAB R2025b 5G Toolbox(nrTBS, nrPDSCHIndices)로 얻었다."""

import pytest
from nrtrail.nr import pdsch

# (PRB 수, 심볼 수, PRB당 DM-RS RE, Q_m, R x 1024) -> nrTBS
MATLAB_TBS = [((12, 12, 36, 2, 120), 304), ((12, 12, 36, 2, 193), 504), ((24, 12, 36, 2, 193), 984), ((12, 12, 36, 2, 679), 1736),
              ((6, 12, 36, 2, 120), 144), ((24, 10, 24, 2, 379), 1736), ((12, 7, 12, 2, 308), 528), ((48, 12, 36, 2, 679), 6912),
              ((96, 12, 36, 2, 679), 13832), ((3, 4, 12, 2, 120), 24)]

# (dmrs-TypeA-Position, S, L) -> 12*L - NREPerPRB (매핑 A, 추가 위치 pos2, 데이터 없는 CDM 그룹 2개)
MATLAB_DMRS = [((2, 2, 12), 36), ((2, 2, 10), 36), ((2, 2, 9), 36), ((2, 2, 7), 24), ((2, 2, 5), 12), ((3, 3, 11), 36),
               ((3, 3, 9), 36), ((3, 3, 4), 12), ((2, 1, 13), 36), ((2, 1, 6), 12), ((2, 2, 4), 12)]


@pytest.mark.parametrize("args,expected", MATLAB_TBS)
def test_tbs_matches_matlab(args, expected):
    assert pdsch.tbs(*args).tbs == expected


@pytest.mark.parametrize("args,expected", MATLAB_DMRS)
def test_dmrs_re_count_matches_matlab(args, expected):
    assert pdsch.dmrs_re_per_prb_type_a(*args) == expected


def test_tdra_default_a():
    t2, t3 = pdsch.tdra_default_a(2), pdsch.tdra_default_a(3)
    assert [(r.s, r.length) for r in t2[:7]] == [(2, 12), (2, 10), (2, 9), (2, 7), (2, 5), (9, 4), (4, 4)]
    assert [(r.s, r.length) for r in t3[:7]] == [(3, 11), (3, 9), (3, 8), (3, 6), (3, 4), (10, 4), (6, 4)]
    assert [(r.s, r.length) for r in t2[7:]] == [(5, 7), (5, 2), (9, 2), (12, 2), (1, 13), (1, 6), (2, 4), (4, 7), (8, 4)]
    assert all(r.s + r.length <= 14 for r in t2 + t3) and len(t2) == 16


def test_dci_1_0_si_layout_and_roundtrip():
    # TS 38.212 7.3.1.2.1: 주파수 할당 ceil(log2(N(N+1)/2)), 시간 4, VRB-PRB 1, MCS 5, RV 2, SI 지시자 1, 예약 15
    assert pdsch.dci_riv_bits(24) == 9 and pdsch.dci_riv_bits(48) == 11 and pdsch.dci_riv_bits(96) == 13
    bits = pdsch.dci_1_0_si_build(24, riv=264, tdra=0, vrb_to_prb=0, mcs=2, rv=0, si_indicator=1)
    assert len(bits) == 37
    d = pdsch.dci_1_0_si_parse(bits, 24)
    assert (d.riv, d.tdra, d.mcs, d.rv, d.si_indicator, d.reserved, d.n_bits) == (264, 0, 2, 0, 1, 0, 37)
    assert d.fields[0] == ("frequency domain resource assignment", "1-9", 264)
    with pytest.raises(ValueError):
        pdsch.dci_1_0_si_parse(bits + "0", 24)
