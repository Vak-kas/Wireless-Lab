"""동기 래스터(GSCN), NR-ARFCN, 셀 번호.

근거: TS 38.104 5.4.3.1(동기 래스터), 5.4.2.1(NR-ARFCN), TS 38.211 7.4.2.1(PCI).
주의: TS 38.104 원문은 specs/에 없어 대조하지 못했다(PROGRESS.md "원문 미대조" 목록). 공식은 널리 알려진 형태 그대로다.
"""

from __future__ import annotations

from dataclasses import dataclass

KHZ = 1_000
MHZ = 1_000_000


@dataclass(frozen=True)
class Gscn:
    gscn: int
    ss_ref_hz: int
    n: int
    m: int | None  # 3 GHz 미만에서만 쓰는 M (1, 3, 5)


def gscn_to_freq(gscn: int) -> Gscn:
    """GSCN -> SS_REF. TS 38.104 표 5.4.3.1-1."""
    if 2 <= gscn <= 7498:
        # 0-3000 MHz: SS_REF = N*1200 kHz + M*50 kHz, GSCN = 3N + (M-3)/2, M in {1,3,5}
        n = (gscn + 1) // 3
        m = 2 * (gscn - 3 * n) + 3
        return Gscn(gscn, n * 1200 * KHZ + m * 50 * KHZ, n, m)
    if 7499 <= gscn <= 22255:
        # 3000-24250 MHz: SS_REF = 3000 MHz + N*1.44 MHz, GSCN = 7499 + N
        n = gscn - 7499
        return Gscn(gscn, 3000 * MHZ + n * 1440 * KHZ, n, None)
    if 22256 <= gscn <= 26639:
        # 24250-100000 MHz: SS_REF = 24250.08 MHz + N*17.28 MHz, GSCN = 22256 + N
        n = gscn - 22256
        return Gscn(gscn, 24_250_080 * KHZ + n * 17_280 * KHZ, n, None)
    raise ValueError(f"GSCN 범위 밖: {gscn}")


def gscn_range(lo_hz: float, hi_hz: float) -> list[Gscn]:
    """SS_REF가 [lo, hi] 안에 드는 GSCN 전부."""
    out: list[Gscn] = []
    if lo_hz < 3000 * MHZ:
        n0 = max(1, int(lo_hz // (1200 * KHZ)) - 1)
        n1 = min(2499, int(min(hi_hz, 3000 * MHZ) // (1200 * KHZ)) + 1)
        for n in range(n0, n1 + 1):
            for m in (1, 3, 5):
                f = n * 1200 * KHZ + m * 50 * KHZ
                if lo_hz <= f <= hi_hz and f < 3000 * MHZ:
                    out.append(Gscn(3 * n + (m - 3) // 2, f, n, m))
    if hi_hz >= 3000 * MHZ and lo_hz < 24_250 * MHZ:
        n0 = max(0, -int(-(lo_hz - 3000 * MHZ) // (1440 * KHZ)))
        n1 = min(14756, int((hi_hz - 3000 * MHZ) // (1440 * KHZ)))
        out += [Gscn(7499 + n, 3000 * MHZ + n * 1440 * KHZ, n, None) for n in range(n0, n1 + 1)]
    return sorted(out, key=lambda g: g.gscn)


def arfcn_to_freq(n_ref: int) -> int:
    """NR-ARFCN -> F_REF (Hz). F_REF = F_REF-Offs + dF_Global*(N_REF - N_REF-Offs). TS 38.104 표 5.4.2.1-1."""
    if 0 <= n_ref < 600_000:
        return 5 * KHZ * n_ref
    if 600_000 <= n_ref < 2_016_667:
        return 3000 * MHZ + 15 * KHZ * (n_ref - 600_000)
    if 2_016_667 <= n_ref <= 3_279_165:
        return 24_250_080 * KHZ + 60 * KHZ * (n_ref - 2_016_667)
    raise ValueError(f"NR-ARFCN 범위 밖: {n_ref}")


def arfcn_params(n_ref: int) -> tuple[int, int, int]:
    """(dF_Global Hz, F_REF-Offs Hz, N_REF-Offs)"""
    if n_ref < 600_000:
        return 5 * KHZ, 0, 0
    if n_ref < 2_016_667:
        return 15 * KHZ, 3000 * MHZ, 600_000
    return 60 * KHZ, 24_250_080 * KHZ, 2_016_667


def pci(nid1: int, nid2: int) -> int:
    """N_ID^cell = 3*N_ID^(1) + N_ID^(2). TS 38.211 7.4.2.1."""
    if not (0 <= nid1 <= 335 and 0 <= nid2 <= 2):
        raise ValueError("N_ID1은 0~335, N_ID2는 0~2")
    return 3 * nid1 + nid2


SSB_BW_SC = 240  # SS/PBCH 블록은 부반송파 240개. TS 38.211 7.4.3.1


def ssb_bandwidth_hz(scs_khz: int) -> int:
    return SSB_BW_SC * scs_khz * KHZ
