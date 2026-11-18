"""SS/PBCH 블록의 시간 배치(Case A~C)와 PBCH 페이로드 풀이.

근거: TS 38.213 4.1 (specs/38213-j50, Case A-C의 첫 심볼과 n의 범위, L_max와 DM-RS 비트 수).
근거: TS 38.212 7.1.1 (PBCH 추가 페이로드 비트), TS 38.211 7.4.3.1 (SSB 안의 자원 배치).
"""

from __future__ import annotations

FR1_3GHZ = 3_000_000_000
UNPAIRED_SPLIT = 1_880_000_000


def burst_start_symbols(pattern: str, carrier_hz: float, paired: bool = True) -> list[int]:
    """하프프레임 첫 슬롯의 첫 심볼을 0으로 볼 때, 후보 SSB들의 첫 심볼 번호. TS 38.213 4.1.

    공유 스펙트럼(비면허) 동작은 다루지 않는다.
    """
    if pattern == "A":  # 15 kHz: {2, 8} + 14n
        ns = range(2) if carrier_hz <= FR1_3GHZ else range(4)
        return [s + 14 * n for n in ns for s in (2, 8)]
    if pattern == "B":  # 30 kHz: {4, 8, 16, 20} + 28n
        ns = range(1) if carrier_hz <= FR1_3GHZ else range(2)
        return [s + 28 * n for n in ns for s in (4, 8, 16, 20)]
    if pattern == "C":  # 30 kHz: {2, 8} + 14n
        if paired:
            ns = range(2) if carrier_hz <= FR1_3GHZ else range(4)
        else:
            ns = range(2) if carrier_hz < UNPAIRED_SPLIT else range(4)
        return [s + 14 * n for n in ns for s in (2, 8)]
    raise ValueError(f"지원하지 않는 SSB 배치: Case {pattern}")


def lmax(pattern: str, carrier_hz: float, paired: bool = True) -> int:
    """한 하프프레임의 후보 SSB 수 L_max."""
    return len(burst_start_symbols(pattern, carrier_hz, paired))


def pattern_scs_khz(pattern: str) -> int:
    return {"A": 15, "B": 30, "C": 30}[pattern]


def split_ibar(ibar_ssb: int, l_max: int) -> tuple[int, int | None]:
    """PBCH DM-RS 번호 i_SSB(3비트) -> (SSB 번호 하위 비트, 하프프레임 비트 또는 None).

    L_max=4면 하위 2비트가 SSB 번호이고 셋째 비트가 하프프레임 n_hf (i_SSB = i_SSB' + 4*n_hf, TS 38.211 7.4.1.4.1).
    L_max>4면 3비트 전부가 SSB 번호 하위 3비트다 (TS 38.213 4.1).
    """
    if l_max == 4:
        return ibar_ssb & 0b11, ibar_ssb >> 2
    return ibar_ssb & 0b111, None


def full_sfn(sfn_msb6: int, sfn_lsb4: int) -> int:
    """SFN = 16*MSB6 + LSB4. MIB에 상위 6비트, PBCH 추가 페이로드에 하위 4비트. TS 38.212 7.1.1."""
    return 16 * sfn_msb6 + sfn_lsb4


def k_ssb(msb: int, lsb4: int) -> int:
    """k_SSB = 16*MSB + ssb-SubcarrierOffset (FR1, L_max 4 또는 8). TS 38.212 7.1.1, TS 38.211 7.4.3.1."""
    return 16 * msb + lsb4


def sib1_present_fr1(k: int) -> bool:
    """FR1에서 k_SSB <= 23 이면 이 SSB에 Type0-PDCCH CSS용 CORESET이 있다. TS 38.213 13."""
    return k <= 23


def symbols_per_slot() -> int:
    return 14


def samples_per_symbol(scs_khz: int, sample_rate_hz: float, symbol_in_half_subframe: int) -> float:
    """정상 CP에서 OFDM 심볼 하나의 길이(샘플). 0.5 ms마다 첫 심볼의 CP가 16*kappa*Tc만큼 길다. TS 38.211 5.3.1."""
    mu = {15: 0, 30: 1, 60: 2, 120: 3}[scs_khz]
    n_fft = sample_rate_hz / (scs_khz * 1000)
    cp = 144 * n_fft / 2048
    extra = 16 * n_fft / 2048 * (2 ** mu) if symbol_in_half_subframe == 0 else 0.0
    return n_fft + cp + extra


def symbol_start_in_half_frame(symbol: int, scs_khz: int, sample_rate_hz: float) -> float:
    """하프프레임 시작부터 주어진 심볼 시작까지의 샘플 수."""
    mu = {15: 0, 30: 1, 60: 2, 120: 3}[scs_khz]
    per_half_sf = 7 * (2 ** mu)  # 0.5 ms 안의 심볼 수
    full, rest = divmod(symbol, per_half_sf)
    total = full * sample_rate_hz * 0.0005
    for s in range(rest):
        total += samples_per_symbol(scs_khz, sample_rate_hz, s)
    return total


# SSB 안의 자원 배치. TS 38.211 표 7.4.3.1-1 (부반송파 k, 심볼 l).
def ssb_category(k: int, sym: int, ncellid: int) -> int:
    """SSB 격자 한 칸의 종류: 0=PSS, 1=SSS, 2=PBCH, 3=PBCH DM-RS, -1=비어 있음(0으로 채움)."""
    v = ncellid % 4
    if sym == 0:
        return 0 if 56 <= k <= 182 else -1
    if sym == 2 and 56 <= k <= 182:
        return 1
    if sym == 2 and (48 <= k <= 55 or 183 <= k <= 191):
        return -1
    return 3 if k % 4 == v else 2
