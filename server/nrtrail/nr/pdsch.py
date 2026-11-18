"""SI-RNTI로 스케줄된 PDSCH(SIB1, SI 메시지)의 DCI 1_0 풀이, 시간 자원 표, MCS, 전송 블록 크기.

근거와 대조 상태 (TS 38.214, 38.212 원문은 specs/에 없다)
- DCI 1_0 (SI-RNTI) 필드 배치: TS 38.212 7.3.1.2.1 (test_nr_pdsch.py 참고)
- 기본 시간 자원 표 A: TS 38.214 표 5.1.2.1.1-2. MATLAB 5G Toolbox에 들어 있는 같은 표
  (wirelessWaveformGenerator.nr5G_SSB_SIB1_Dialog)의 시작·길이와 16행 모두 일치함을 확인
- MCS 표 1: TS 38.214 표 5.1.3.1-1
- TBS: TS 38.214 5.1.3.2. MATLAB nrTBS 결과와 교차 확인(test_nr_pdsch.py의 기대값)
"""

from __future__ import annotations

from dataclasses import dataclass
from math import ceil, floor, log2
from typing import Any

SI_RNTI = 0xFFFF


@dataclass(frozen=True)
class Tdra:
    row: int           # 표의 행 번호(1부터). DCI 필드 값 m에 대해 row = m + 1
    mapping_type: str  # "A" | "B"
    k0: int
    s: int
    length: int


def tdra_default_a(dmrs_typea_pos: int) -> list[Tdra]:
    """기본 PDSCH 시간 자원 표 A(정상 CP). TS 38.214 표 5.1.2.1.1-2."""
    d = dmrs_typea_pos
    rows = [("A", d, 14 - d), ("A", d, 12 - d), ("A", d, 11 - d), ("A", d, 9 - d), ("A", d, 7 - d),
            ("B", d + 7, 4), ("B", 2 * d, 4), ("B", 5, 7), ("B", 5, 2), ("B", 9, 2), ("B", 12, 2),
            ("A", 1, 13), ("A", 1, 6), ("A", 2, 4), ("B", 4, 7), ("B", 8, 4)]
    return [Tdra(i + 1, t, 0, s, length) for i, (t, s, length) in enumerate(rows)]


# MCS 표 1 (64QAM까지). (Q_m, R x 1024). TS 38.214 표 5.1.3.1-1. SI-RNTI는 Q_m <= 2 (번호 0~9)만 쓴다.
MCS_TABLE_1: list[tuple[int, int]] = [
    (2, 120), (2, 157), (2, 193), (2, 251), (2, 308), (2, 379), (2, 449), (2, 526), (2, 602), (2, 679),
    (4, 340), (4, 378), (4, 434), (4, 490), (4, 553), (4, 616), (4, 658),
    (6, 438), (6, 466), (6, 517), (6, 567), (6, 616), (6, 666), (6, 719), (6, 772), (6, 822), (6, 873), (6, 910), (6, 948),
]

# TS 38.214 표 5.1.3.2-1 (N_info <= 3824 일 때의 TBS)
TBS_TABLE = [
    24, 32, 40, 48, 56, 64, 72, 80, 88, 96, 104, 112, 120, 128, 136, 144, 152, 160, 168, 176, 184, 192, 208, 224, 240, 256,
    272, 288, 304, 320, 336, 352, 368, 384, 408, 432, 456, 480, 504, 528, 552, 576, 608, 640, 672, 704, 736, 768, 808, 848,
    888, 928, 984, 1032, 1064, 1128, 1160, 1192, 1224, 1256, 1288, 1320, 1352, 1416, 1480, 1544, 1608, 1672, 1736, 1800,
    1864, 1928, 2024, 2088, 2152, 2216, 2280, 2408, 2472, 2536, 2600, 2664, 2728, 2792, 2856, 2976, 3104, 3240, 3368, 3496,
    3624, 3752, 3824,
]


@dataclass(frozen=True)
class Tbs:
    n_re_prime: int   # PRB 하나의 데이터 RE 수 N'_RE
    n_re: int         # 전체 N_RE
    n_info: float
    n_info_prime: int
    tbs: int
    steps: list[str]


def tbs(n_prb: int, n_symbols: int, n_dmrs_per_prb: int, qm: int, rate_x1024: int, layers: int = 1, overhead: int = 0,
        scaling: float = 1.0) -> Tbs:
    """전송 블록 크기. TS 38.214 5.1.3.2.

    n_dmrs_per_prb: 할당 구간에서 PRB 하나에 든 DM-RS RE 수(데이터 없는 CDM 그룹의 몫 포함).
    """
    r = rate_x1024 / 1024
    n_re_prime = 12 * n_symbols - n_dmrs_per_prb - overhead
    n_re = min(156, n_re_prime) * n_prb
    n_info = scaling * n_re * r * qm * layers  # scaling: RA-RNTI/P-RNTI의 TB scaling (TS 38.214 표 5.1.3.2-2), 그 외 1
    steps = [f"N'_RE = 12 × {n_symbols} − {n_dmrs_per_prb} − {overhead} = {n_re_prime}",
             f"N_RE = min(156, {n_re_prime}) × {n_prb} = {n_re}",
             f"N_info = {n_re} × {rate_x1024}/1024 × {qm} × {layers} = {n_info:.6g}"]
    if n_info <= 3824:
        n = max(3, floor(log2(n_info)) - 6)
        nip = max(24, (2 ** n) * floor(n_info / 2 ** n))
        value = next(t for t in TBS_TABLE if t >= nip)
        steps += [f"n = max(3, ⌊log2({n_info:.6g})⌋ − 6) = {n}", f"N'_info = max(24, 2^{n} × ⌊N_info / 2^{n}⌋) = {nip}",
                  f"TBS = smallest table value ≥ {nip} = {value}"]
    else:
        n = floor(log2(n_info - 24)) - 5
        nip = max(3840, (2 ** n) * round((n_info - 24) / 2 ** n))
        if r <= 0.25:
            c = ceil((nip + 24) / 3816)
            value = 8 * c * ceil((nip + 24) / (8 * c)) - 24
        elif nip > 8424:
            c = ceil((nip + 24) / 8424)
            value = 8 * c * ceil((nip + 24) / (8 * c)) - 24
        else:
            value = 8 * ceil((nip + 24) / 8) - 24
        steps += [f"n = ⌊log2({n_info:.6g} − 24)⌋ − 5 = {n}", f"N'_info = max(3840, 2^{n} × round((N_info − 24) / 2^{n})) = {nip}",
                  f"TBS = {value}"]
    return Tbs(n_re_prime, n_re, n_info, int(nip), int(value), steps)


@dataclass(frozen=True)
class Dci10Si:
    """SI-RNTI로 CRC가 가려진 DCI 형식 1_0. TS 38.212 7.3.1.2.1."""

    riv: int
    tdra: int
    vrb_to_prb: int
    mcs: int
    rv: int
    si_indicator: int   # 0 = SIB1, 1 = SI 메시지
    reserved: int
    n_bits: int
    fields: list[tuple[str, str, int]]  # (필드 이름, 비트 위치 "a-b" 1부터, 값)


def dci_riv_bits(n_rb: int) -> int:
    """주파수 자원 할당 필드의 비트 수 ceil(log2(N(N+1)/2)), N = CORESET0의 RB 수."""
    return ceil(log2(n_rb * (n_rb + 1) / 2))


def dci_1_0_si_layout(n_rb_coreset0: int) -> list[tuple[str, int]]:
    return [("frequency domain resource assignment", dci_riv_bits(n_rb_coreset0)), ("time domain resource assignment", 4),
            ("VRB-to-PRB mapping", 1), ("modulation and coding scheme", 5), ("redundancy version", 2),
            ("system information indicator", 1), ("reserved", 15)]


def dci_1_0_si_parse(bits: str, n_rb_coreset0: int) -> Dci10Si:
    """bits: '0'/'1' 문자열(MSB 먼저)."""
    layout = dci_1_0_si_layout(n_rb_coreset0)
    total = sum(n for _, n in layout)
    if len(bits) != total:
        raise ValueError(f"DCI 1_0 (SI-RNTI) 길이는 {total}비트여야 하는데 {len(bits)}비트입니다")
    pos, vals, fields = 0, [], []
    for name, n in layout:
        v = int(bits[pos:pos + n], 2)
        vals.append(v)
        fields.append((name, f"{pos + 1}-{pos + n}" if n > 1 else f"{pos + 1}", v))
        pos += n
    riv, tdra, vrb, mcs, rv, si, reserved = vals
    return Dci10Si(riv, tdra, vrb, mcs, rv, si, reserved, total, fields)


def dci_1_0_si_build(n_rb_coreset0: int, riv: int, tdra: int, vrb_to_prb: int, mcs: int, rv: int, si_indicator: int) -> str:
    out = ""
    for (_, n), v in zip(dci_1_0_si_layout(n_rb_coreset0), (riv, tdra, vrb_to_prb, mcs, rv, si_indicator, 0), strict=True):
        if not 0 <= v < 2 ** n:
            raise ValueError("DCI 필드 값이 범위를 벗어났습니다")
        out += format(v, f"0{n}b")
    return out


def dmrs_re_per_prb_type_a(dmrs_typea_pos: int, s: int, length: int) -> int:
    """SI-RNTI PDSCH(매핑 A, DM-RS 설정 1형, 단일 심볼, dmrs-AdditionalPosition pos2, 데이터 없는 CDM 그룹 2개)의
    PRB당 DM-RS RE 수. DM-RS 심볼 위치는 TS 38.211 표 7.4.1.1.2-3의 pos2 열(MATLAB 결과와 교차 확인)."""
    ld = s + length  # 매핑 A에서는 슬롯 시작부터 PDSCH 마지막 심볼까지
    n_sym = 1 if ld <= 7 else 2 if ld <= 9 else 3
    return 12 * n_sym


# 합성 파형과 예시 데이터에 쓰는 기본 선택
DEFAULT_MCS = 2      # QPSK, R = 193/1024. 낮은 SNR에서도 풀리도록 낮게 잡는다
DEFAULT_TDRA = 0     # 기본 표 A의 1행: 슬롯 전체(S = dmrs-TypeA-Position)
DEFAULT_AL = 8


def allocate(payload_hex: str, n_rb: int, dmrs_pos: int, si_indicator: int) -> dict[str, Any]:
    """페이로드가 들어가는 가장 좁은 RB 할당을 고르고 DCI 1_0과 채움(TBS 길이)까지 만든다. 합성기 cfg와 예시 raw가 같이 쓴다."""
    from .sched import riv_encode

    row = tdra_default_a(dmrs_pos)[DEFAULT_TDRA]
    n_dmrs = dmrs_re_per_prb_type_a(dmrs_pos, row.s, row.length)
    qm, rate = MCS_TABLE_1[DEFAULT_MCS]
    bits = len(payload_hex) * 4
    for length in range(1, n_rb + 1):
        t = tbs(length, row.length, n_dmrs, qm, rate)
        if t.tbs >= bits:
            break
    else:
        raise ValueError(f"payload of {bits} bits does not fit in CORESET0 ({n_rb} RB)")
    riv = riv_encode(0, length, n_rb)
    return {
        "tb_hex": payload_hex + "00" * ((t.tbs - bits) // 8), "payload_bytes": bits // 8, "tbs": t.tbs, "al": DEFAULT_AL,
        "dci": {"bits": dci_1_0_si_build(n_rb, riv, DEFAULT_TDRA, 0, DEFAULT_MCS, 0, si_indicator),
                "riv": riv, "tdra": DEFAULT_TDRA, "vrb_to_prb": 0, "mcs": DEFAULT_MCS, "rv": 0, "si_indicator": si_indicator},
        "rb_start": 0, "rb_len": length, "sym_start": row.s, "sym_len": row.length, "mapping_type": row.mapping_type,
        "qm": qm, "rate_x1024": rate, "n_dmrs_per_prb": n_dmrs,
    }
