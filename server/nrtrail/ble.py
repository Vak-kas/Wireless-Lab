"""Bluetooth LE 광고 수신: 주변 기기가 방송하는 광고 패킷을 받아 주소·이름·제조사를 읽는다. **수신 전용**이다.

무엇을 읽는가
- 광고 채널 3개(37 = 2402 MHz, 38 = 2426 MHz, 39 = 2480 MHz)의 **방송용 광고**만 풀이한다:
  ADV_IND, ADV_NONCONN_IND, ADV_SCAN_IND, SCAN_RSP 의 광고 주소(AdvA)와 광고 데이터(이름, 제조사 번호, 서비스 번호).
- 특정 기기를 향한 패킷(SCAN_REQ, CONNECT_IND, ADV_DIRECT_IND)은 **개수만 세고 내용은 풀지 않는다.**
  CONNECT_IND 에는 그 뒤의 연결을 따라갈 수 있는 값이 들어 있다. 연결(데이터 채널)은 따라가지 않는다
  (방송 정보 외의 개별 단말 통신은 처리하지 않는다).

어떻게 읽는가 (Bluetooth Core 규격 Vol 6 Part B)
- 변조: GFSK 1 Mbit/s, 변조 지수 약 0.5. 비트 1 = 주파수가 위로. 비트는 바이트의 낮은 자리부터 나간다.
- 패킷: 프리앰블 0xAA(8비트) + 접근 주소 0x8E89BED6(32비트) + PDU(머리 2바이트 + 본문) + CRC 24비트.
- 화이트닝: PDU 와 CRC 에 x^7 + x^4 + 1 수열을 XOR. 초기값은 채널 번호로 정한다.
- CRC: 다항식 x^24 + x^10 + x^9 + x^6 + x^4 + x^3 + x + 1, 광고 채널의 초기값 0x555555.
- 복조: 이웃한 샘플의 위상 차이(= 순간 주파수)를 구해 한 비트 길이로 평균하고, 부호로 비트를 정한다.
  프리앰블 + 접근 주소 40비트와 맞는 자리를 찾고(2비트까지 틀려도 됨), 프리앰블 평균으로 주파수 어긋남을 뺀 뒤 다시 자른다.
"""

from __future__ import annotations

import math
import tempfile
from pathlib import Path
from typing import Any

import numpy as np

from . import devices, sigmf
from .paths import sessions_dir

ACCESS_ADDRESS = 0x8E89BED6
ADV_FREQ_HZ = {37: 2402e6, 38: 2426e6, 39: 2480e6}
RATE_HZ = 4e6                 # 심볼(1 Mbit/s)당 4샘플
SPS = 4
DWELL_S = 0.25
SYNC_ERRORS = 2
MAX_PDU = 2 + 255
PDU_TYPES = {0: "ADV_IND", 1: "ADV_DIRECT_IND", 2: "ADV_NONCONN_IND", 3: "SCAN_REQ", 4: "SCAN_RSP", 5: "CONNECT_IND",
             6: "ADV_SCAN_IND", 7: "ADV_EXT_IND"}
BROADCAST = {0, 2, 4, 6}      # 내용을 풀이하는 종류(모두에게 방송하는 광고)
# 제조사 번호(Bluetooth SIG 가 배정한 회사 식별자) 가운데 흔한 것 몇 개. 표에 없으면 번호만 보여 준다.
COMPANIES = {0x004C: "Apple", 0x0006: "Microsoft", 0x0075: "Samsung", 0x00E0: "Google", 0x0157: "Huami", 0x038F: "Xiaomi",
             0x0087: "Garmin", 0x0059: "Nordic Semiconductor", 0x000D: "Texas Instruments", 0x012D: "Sony", 0x00C4: "LG Electronics"}


class BleError(ValueError):
    """사용자에게 그대로 보여줄 문구."""


def _swap(b: int) -> int:
    return int(f"{b:08b}"[::-1], 2)


def whiten(data: bytes, channel: int) -> bytes:
    """화이트닝(걸기와 풀기가 같은 연산)."""
    coeff = _swap(channel) | 2
    out = bytearray(data)
    for i in range(len(out)):
        m = 1
        while m < 0x100:
            if coeff & 0x80:
                coeff ^= 0x11
                out[i] ^= m
            coeff = (coeff << 1) & 0xFF
            m <<= 1
    return bytes(out)


def crc24(data: bytes) -> bytes:
    """광고 채널 CRC. 공중으로 나가는 순서의 3바이트."""
    c = [0x55, 0x55, 0x55]
    for d in data:
        for _ in range(8):
            t = c[0] >> 7
            c[0] = ((c[0] << 1) & 0xFF) | (c[1] >> 7)
            c[1] = ((c[1] << 1) & 0xFF) | (c[2] >> 7)
            c[2] = (c[2] << 1) & 0xFF
            if t != (d & 1):
                c[2] ^= 0x5B
                c[1] ^= 0x06
            d >>= 1
    return bytes(_swap(x) for x in c)


def _bits(data: bytes) -> np.ndarray:
    return np.unpackbits(np.frombuffer(data, dtype=np.uint8), bitorder="little")


SYNC_BITS = _bits(bytes([0xAA]) + ACCESS_ADDRESS.to_bytes(4, "little"))
_SYNC_PM = SYNC_BITS.astype(np.float32) * 2 - 1


def modulate(pdu: bytes, channel: int, sps: int = SPS, amplitude: float = 0.5) -> np.ndarray:
    """광고 패킷 하나를 GFSK 기저대역으로 만든다(테스트용. 실험용 송신 모듈이 시험 광고를 만들 때도 쓴다)."""
    bits = np.concatenate([SYNC_BITS, _bits(whiten(pdu + crc24(pdu), channel))])
    nrz = np.repeat(bits.astype(np.float64) * 2 - 1, sps)
    t = np.arange(-2 * sps, 2 * sps + 1) / sps
    bt = 0.5
    g = np.exp(-2 * (math.pi * bt * t) ** 2 / math.log(2))
    shaped = np.convolve(nrz, g / g.sum(), mode="same")
    phase = np.cumsum(math.pi * 0.5 * shaped / sps)                 # 변조 지수 0.5
    out: np.ndarray = (amplitude * np.exp(1j * phase)).astype(np.complex64)
    return out


def _ad_fields(data: bytes) -> dict[str, Any]:
    """광고 데이터(길이·종류·값의 나열)에서 이름, 제조사, 서비스 번호를 읽는다."""
    out: dict[str, Any] = {}
    i = 0
    while i < len(data):
        n = data[i]
        if n == 0 or i + 1 + n > len(data):
            break
        kind, value = data[i + 1], data[i + 2:i + 1 + n]
        if kind in (0x08, 0x09):
            out["name"] = value.decode("utf-8", errors="replace")
        elif kind == 0xFF and len(value) >= 2:
            company = int.from_bytes(value[:2], "little")
            out["company_id"] = company
            out["company"] = COMPANIES.get(company, "")
        elif kind in (0x02, 0x03):
            out["services"] = [f"0x{int.from_bytes(value[k:k + 2], 'little'):04X}" for k in range(0, len(value) - 1, 2)]
        elif kind == 0x0A and len(value) == 1:
            out["tx_power_dbm"] = int.from_bytes(value, "little", signed=True)
        i += 1 + n
    return out


def parse(pdu: bytes) -> dict[str, Any]:
    """PDU 를 풀이한다. 방송용 광고가 아니면 종류만 돌려준다."""
    kind = pdu[0] & 0x0F
    out: dict[str, Any] = {"pdu_type": PDU_TYPES.get(kind, f"RESERVED_{kind}"), "broadcast": kind in BROADCAST}
    if kind in BROADCAST and len(pdu) >= 8:
        out["address"] = ":".join(f"{b:02X}" for b in reversed(pdu[2:8]))
        out["address_type"] = "random" if pdu[0] & 0x40 else "public"
        out |= _ad_fields(pdu[8:])
    return out


def find_packets(iq: np.ndarray, channel: int, sps: int = SPS) -> dict[str, Any]:
    """IQ 에서 광고 패킷을 찾아 푼다. CRC 가 맞은 것만 packets 에 넣는다."""
    x = np.asarray(iq, dtype=np.complex64)
    if len(x) < sps * 100:
        return {"packets": [], "crc_failed": 0}
    freq = np.angle(x[1:] * np.conj(x[:-1]))
    smooth = np.convolve(freq, np.ones(sps, dtype=np.float32) / sps, mode="same")
    power = np.abs(x) ** 2
    found: list[dict[str, Any]] = []
    failed: list[int] = []
    near = sps * 16                                                           # 이 안의 자리는 같은 패킷이다(여러 위상에서 겹쳐 찾음)
    need = len(SYNC_BITS) - 2 * SYNC_ERRORS
    for phase in range(sps):
        sym = smooth[phase::sps]
        hits = np.nonzero(np.correlate(np.sign(sym).astype(np.float32), _SYNC_PM, mode="valid") >= need)[0]
        for h in hits:
            a = int(h * sps + phase)
            if any(abs(a - f["sample"]) < near for f in found):
                continue
            dc = float(sym[h:h + 8].mean())                                   # 프리앰블(0101…)의 평균 = 주파수 어긋남
            body = sym[h + 40:h + 40 + 8 * (MAX_PDU + 3)] > dc
            if len(body) < 8 * 5:
                continue
            raw = np.packbits(body[: len(body) // 8 * 8], bitorder="little").tobytes()
            total = 2 + whiten(raw[:2], channel)[1] + 3
            plain = whiten(raw[:total], channel) if total <= len(raw) else b""
            if not plain or crc24(plain[:-3]) != plain[-3:]:
                failed.append(a)
                continue
            pdu = plain[:-3]
            b = a + (40 + 8 * total) * sps
            found.append(parse(pdu) | {"sample": a, "length": len(pdu),
                                       "power_db": round(10 * math.log10(float(power[a:b].mean()) + 1e-12), 1),
                                       # rad/샘플 → Hz (샘플레이트 = sps × 1 MHz)
                                       "cfo_hz": round(dc / (2 * math.pi) * 1e6 * sps, -2)})
    # CRC 가 안 맞은 자리 가운데, 맞은 패킷과 겹치지 않는 것만 "깨진 패킷"으로 센다(서로 가까운 것은 하나로)
    broken: list[int] = []
    for a in sorted(failed):
        if not any(abs(a - f["sample"]) < near for f in found) and not (broken and a - broken[-1] < near):
            broken.append(a)
    return {"packets": sorted(found, key=lambda p: p["sample"]), "crc_failed": len(broken)}


def summarize(packets: list[dict[str, Any]], channel: int) -> dict[str, Any]:
    """패킷들을 기기(광고 주소)별로 모은다. 특정 기기를 향한 패킷은 종류별 개수만 센다."""
    devs: dict[str, dict[str, Any]] = {}
    directed: dict[str, int] = {}
    for p in packets:
        if not p.get("broadcast") or "address" not in p:
            directed[p["pdu_type"]] = directed.get(p["pdu_type"], 0) + 1
            continue
        d = devs.setdefault(p["address"], {"address": p["address"], "address_type": p["address_type"], "name": "", "company": "",
                                           "company_id": None, "services": [], "pdu_types": [], "count": 0, "power_db": -200.0,
                                           "channel": channel})
        d["count"] += 1
        d["power_db"] = max(d["power_db"], p["power_db"])
        d["name"] = p.get("name") or d["name"]
        if p.get("company_id") is not None:
            d["company_id"], d["company"] = p["company_id"], p.get("company", "")
        d["services"] = sorted(set(d["services"]) | set(p.get("services", [])))
        if p["pdu_type"] not in d["pdu_types"]:
            d["pdu_types"].append(p["pdu_type"])
    return {"devices": sorted(devs.values(), key=lambda d: -d["power_db"]), "directed": directed}


def scan(dev_id: str, channel: int = 37, gain_db: float | None = None, seconds: float = DWELL_S) -> dict[str, Any]:
    """광고 채널 하나를 seconds 초 받아 주변 기기를 돌려준다."""
    if channel not in ADV_FREQ_HZ:
        raise BleError("광고 채널은 37, 38, 39 입니다.")
    if not 0.05 <= seconds <= 2.0:
        raise BleError("받는 시간은 0.05 ~ 2 초 사이여야 합니다.")
    try:
        dev = devices.find_device(dev_id)
    except devices.DeviceError as e:
        raise BleError("장비를 찾을 수 없습니다.") from e
    if dev["driver"] == "simulated":
        raise BleError("모의 장비로는 블루투스를 받을 수 없습니다(저장 파일에 블루투스 신호가 없습니다).")
    center = ADV_FREQ_HZ[channel]
    if devices.check_request(dev, center, RATE_HZ):
        raise BleError("이 장비로는 받을 수 없는 주파수이거나 샘플레이트(4 MS/s)입니다.")
    work = sessions_dir() / "survey"
    work.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=work) as tmp:
        try:
            cap: sigmf.Capture = devices.capture(dev_id, devices.CaptureRequest(center, RATE_HZ, seconds, gain_db), Path(tmp) / "ble.sigmf-meta")
        except devices.DeviceError as e:
            raise BleError(f"장비에서 받지 못했습니다: {e}") from e
        sps = round(cap.sample_rate_hz / 1e6)
        if abs(cap.sample_rate_hz - sps * 1e6) > 1 or sps < 2:
            raise BleError("샘플레이트가 1 MS/s 의 정수배(2 이상)여야 합니다.")
        iq = np.asarray(cap.read(0, cap.num_samples))
    res = find_packets(iq, channel, sps)
    peak = float(max(np.abs(iq.real).max(), np.abs(iq.imag).max())) if len(iq) else 0.0
    return {"device": dev_id, "channel": channel, "center_hz": center, "seconds": round(len(iq) / cap.sample_rate_hz, 3),
            "packets": len(res["packets"]), "crc_failed": res["crc_failed"], "clipped": peak > 0.89,
            **summarize(res["packets"], channel)}
