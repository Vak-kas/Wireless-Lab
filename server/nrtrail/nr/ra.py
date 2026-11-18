"""랜덤 액세스 관측(SPEC 11절)용 계산: RA-RNTI, RAR(Msg2) 풀이, TA → 거리, Msg4의 경쟁 해소.

테스트베드 전용이다. 입력이 synthetic 이거나 testbed로 표시된 file일 때만 쓴다(runner.check_allowed).
근거
- RA-RNTI = 1 + s_id + 14*t_id + 14*80*f_id + 14*80*8*ul_carrier_id — TS 38.321 5.1.3
- MAC RAR(7바이트): R(1) | TA 명령(12) | UL 그랜트(27) | TC-RNTI(16) — TS 38.321 6.2.3
- RAR 부헤더: E|T|R|R|BI(4) 또는 E|T|RAPID(6) — TS 38.321 6.1.5
- UL 그랜트 27비트의 필드 — TS 38.213 표 8.2-1
- N_TA = T_A * 16 * 64 / 2^mu — TS 38.213 4.2
- DCI 1_0 (RA-RNTI): 주파수 할당 | 시간 4 | VRB-PRB 1 | MCS 5 | TB scaling 2 | 예약 16 — TS 38.212 7.3.1.2.1
- 경쟁 해소 MAC CE: LCID 62, UE 경쟁 해소 식별자 48비트 — TS 38.321 6.1.3.3, 표 6.2.1-1
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .ntn import TC, C

# TS 38.213 표 8.2-1: RAR UL 그랜트의 필드와 비트 수 (MSB부터)
UL_GRANT_FIELDS = [("frequency hopping flag", 1), ("PUSCH frequency resource allocation", 14), ("PUSCH time resource allocation", 4),
                   ("MCS", 4), ("TPC command for PUSCH", 3), ("CSI request", 1)]
LCID_CCCH = 0
LCID_CONTENTION_RESOLUTION = 62
LCID_PADDING = 63
TB_SCALING = [1.0, 0.5, 0.25]   # TS 38.214 표 5.1.3.2-2


def ra_rnti(s_id: int, t_id: int, f_id: int, ul_carrier_id: int = 0) -> int:
    if not (0 <= s_id < 14 and 0 <= t_id < 80 and 0 <= f_id < 8 and ul_carrier_id in (0, 1)):
        raise ValueError("s_id 0~13, t_id 0~79, f_id 0~7, ul_carrier_id 0~1")
    return 1 + s_id + 14 * t_id + 14 * 80 * f_id + 14 * 80 * 8 * ul_carrier_id


def prach_slot_index(subframe: int, prach_scs_khz: int, slots_per_subframe: int | None) -> int:
    """PRACH 기회가 든 슬롯의 프레임 내 번호(t_id). 30 kHz이고 서브프레임당 PRACH 슬롯이 1개면 둘째 슬롯을 쓴다 (TS 38.211 5.3.2)."""
    if prach_scs_khz == 15 or slots_per_subframe is None:
        return subframe * (prach_scs_khz // 15)
    return subframe * 2 + (1 if slots_per_subframe == 1 else 0)


@dataclass(frozen=True)
class Rar:
    rapid: int
    ta_command: int
    ul_grant: int
    tc_rnti: int
    grant_fields: dict[str, int]


@dataclass(frozen=True)
class RarPdu:
    backoff_indicator: int | None
    rars: list[Rar]


def _grant_fields(grant: int) -> dict[str, int]:
    out, shift = {}, 27
    for name, n in UL_GRANT_FIELDS:
        shift -= n
        out[name] = (grant >> shift) & ((1 << n) - 1)
    return out


def build_rar_pdu(rapid: int, ta_command: int, ul_grant: int, tc_rnti: int, backoff: int | None = None) -> bytes:
    """합성 파형에 실을 RAR MAC PDU (시험용 정답 만들기)."""
    if not (0 <= rapid < 64 and 0 <= ta_command < 4096 and 0 <= ul_grant < 2 ** 27 and 0 <= tc_rnti < 65536):
        raise ValueError("RAR 필드 값이 범위를 벗어났습니다")
    out = bytearray()
    if backoff is not None:
        out.append(0x80 | (backoff & 0xF))           # E=1, T=0, R, R, BI
    out.append(0x40 | rapid)                         # E=0, T=1, RAPID
    body = (ta_command << 43) | (ul_grant << 16) | tc_rnti   # R(1)=0 | TA(12) | grant(27) | TC-RNTI(16) = 56비트
    out += body.to_bytes(7, "big")
    return bytes(out)


def parse_rar_pdu(data: bytes) -> RarPdu:
    """RAR MAC PDU를 푼다. 끝의 채움(0)은 무시한다."""
    i, backoff, rars = 0, None, []
    while i < len(data):
        sub = data[i]
        ext, is_rapid = bool(sub & 0x80), bool(sub & 0x40)
        i += 1
        if is_rapid:
            if i + 7 > len(data):
                raise ValueError("RAR 본문이 잘렸습니다")
            body = int.from_bytes(data[i:i + 7], "big")
            i += 7
            grant = (body >> 16) & (2 ** 27 - 1)
            rars.append(Rar(sub & 0x3F, (body >> 43) & 0xFFF, grant, body & 0xFFFF, _grant_fields(grant)))
        else:
            backoff = sub & 0x0F
        if not ext:
            break
    if not rars and backoff is None:
        raise ValueError("RAR이 없습니다")
    return RarPdu(backoff, rars)


def n_ta_from_command(ta_command: int, scs_khz: int) -> float:
    """RAR의 TA 명령 T_A(0~3846) -> N_TA (Tc 단위). N_TA = T_A * 16 * 64 / 2^mu. TS 38.213 4.2."""
    mu = {15: 0, 30: 1, 60: 2, 120: 3}[scs_khz]
    return ta_command * 16 * 64 / 2 ** mu


def distance_from_n_ta(n_ta: float) -> float:
    """왕복 지연 N_TA*Tc 에 해당하는 편도 거리(m). 지상망에서는 기지국까지의 거리, NTN에서는 사전 보정 뒤 남은 몫이다."""
    return C * n_ta * TC / 2


def dci_1_0_ra_parse(bits: str, n_rb: int) -> dict[str, Any]:
    """RA-RNTI로 가려진 DCI 1_0. 길이는 SI-RNTI 형식과 같다.

    ra-ResponseWindow가 10 ms보다 길면 예약 16비트의 앞 2비트가 'LSBs of SFN'이 된다(여기서는 예약으로 묶어 둔다)."""
    from .pdsch import dci_riv_bits

    layout = [("frequency domain resource assignment", dci_riv_bits(n_rb)), ("time domain resource assignment", 4), ("VRB-to-PRB mapping", 1),
              ("modulation and coding scheme", 5), ("TB scaling", 2), ("reserved", 16)]
    if len(bits) != sum(n for _, n in layout):
        raise ValueError("DCI 1_0 (RA-RNTI) 길이가 맞지 않습니다")
    out, pos = {}, 0
    for name, n in layout:
        out[name] = int(bits[pos:pos + n], 2)
        pos += n
    return out


def dci_1_0_ra_build(n_rb: int, riv: int, tdra: int, mcs: int, tb_scaling: int = 0) -> str:
    from .pdsch import dci_riv_bits

    return format(riv, f"0{dci_riv_bits(n_rb)}b") + format(tdra, "04b") + "0" + format(mcs, "05b") + format(tb_scaling, "02b") + "0" * 16


def build_msg4_pdu(contention_id: bytes, ccch_sdu: bytes = b"") -> bytes:
    """Msg4 MAC PDU: 경쟁 해소 식별자 CE(+ DL-CCCH SDU) + 채움 부헤더. 시험용 정답 만들기. 부헤더는 R|F|LCID(+L 8비트)."""
    if len(contention_id) != 6:
        raise ValueError("경쟁 해소 식별자는 48비트(6바이트)입니다")
    out = bytes([LCID_CONTENTION_RESOLUTION]) + contention_id   # 고정 길이 CE: 부헤더 1바이트
    if ccch_sdu:
        if len(ccch_sdu) > 255:
            raise ValueError("CCCH SDU가 너무 깁니다")
        out += bytes([LCID_CCCH, len(ccch_sdu)]) + ccch_sdu
    return out + bytes([LCID_PADDING])   # 뒤는 전송 블록 크기까지 채움


def parse_msg4_pdu(data: bytes) -> dict[str, Any]:
    """DL-SCH MAC PDU에서 경쟁 해소 식별자와 CCCH SDU를 꺼낸다. TS 38.321 6.1.2."""
    i = 0
    contention_id: str | None = None
    ccch_sdu: str | None = None
    other: list[int] = []
    while i < len(data) and any(data[i:]):   # 남은 바이트가 전부 0이면 채움으로 본다
        head = data[i]
        f, lcid = bool(head & 0x40), head & 0x3F
        i += 1
        if lcid == LCID_PADDING:
            break
        if lcid == LCID_CONTENTION_RESOLUTION:
            contention_id = data[i:i + 6].hex()
            i += 6
            continue
        if i >= len(data):
            break
        length = int.from_bytes(data[i:i + 2], "big") if f else data[i]
        i += 2 if f else 1
        if lcid == LCID_CCCH and length:
            ccch_sdu = data[i:i + length].hex()
        elif lcid != LCID_CCCH:
            other.append(lcid)
        i += length
    return {"contention_id": contention_id, "ccch_sdu": ccch_sdu, "other_lcids": other}


# TC-RNTI(또는 C-RNTI)로 가려진 DCI 1_0의 필드. TS 38.212 7.3.1.2.1. 길이는 SI-RNTI·RA-RNTI 형식과 같다.
def _tc_layout(n_rb: int) -> list[tuple[str, int]]:
    from .pdsch import dci_riv_bits

    return [("identifier for DCI formats", 1), ("frequency domain resource assignment", dci_riv_bits(n_rb)),
            ("time domain resource assignment", 4), ("VRB-to-PRB mapping", 1), ("modulation and coding scheme", 5),
            ("new data indicator", 1), ("redundancy version", 2), ("HARQ process number", 4), ("downlink assignment index", 2),
            ("TPC command for scheduled PUCCH", 2), ("PUCCH resource indicator", 3), ("PDSCH-to-HARQ_feedback timing indicator", 3)]


def dci_1_0_tc_build(n_rb: int, riv: int, tdra: int, mcs: int, rv: int = 0) -> str:
    values = {"identifier for DCI formats": 1, "frequency domain resource assignment": riv, "time domain resource assignment": tdra,
              "modulation and coding scheme": mcs, "redundancy version": rv}
    return "".join(format(values.get(name, 0), f"0{n}b") for name, n in _tc_layout(n_rb))


def dci_1_0_tc_parse(bits: str, n_rb: int) -> dict[str, int]:
    layout = _tc_layout(n_rb)
    if len(bits) != sum(n for _, n in layout):
        raise ValueError("DCI 1_0 (TC-RNTI) 길이가 맞지 않습니다")
    out, pos = {}, 0
    for name, n in layout:
        out[name] = int(bits[pos:pos + n], 2)
        pos += n
    return out
