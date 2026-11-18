"""Bluetooth LE 광고 수신: 만든 패킷을 다시 풀어 넣은 값이 나오는지, 무엇을 풀지 않는지."""
import numpy as np
import pytest
from nrtrail import ble, devices, sigmf


def adv(address: str, name: str = "", company: int | None = None, kind: int = 0, random: bool = True) -> bytes:
    data = b""
    if name:
        n = name.encode()
        data += bytes([len(n) + 1, 0x09]) + n
    if company is not None:
        data += bytes([5, 0xFF]) + company.to_bytes(2, "little") + b"\x01\x02"
    payload = bytes(reversed(bytes.fromhex(address.replace(":", "")))) + data
    return bytes([kind | (0x40 if random else 0), len(payload)]) + payload


def air(pdus: list[bytes], channel: int, noise: float = 0.02, cfo_hz: float = 0.0, gap: int = 3000) -> np.ndarray:
    rng = np.random.default_rng(3)
    parts = [np.zeros(gap, dtype=np.complex64)]
    for p in pdus:
        parts += [ble.modulate(p, channel), np.zeros(gap, dtype=np.complex64)]
    x = np.concatenate(parts)
    x = x * np.exp(2j * np.pi * cfo_hz * np.arange(len(x)) / ble.RATE_HZ)
    return (x + noise * (rng.standard_normal(len(x)) + 1j * rng.standard_normal(len(x)))).astype(np.complex64)


def test_whitening_undoes_itself_and_depends_on_the_channel():
    data = bytes(range(40))
    assert ble.whiten(ble.whiten(data, 37), 37) == data
    assert ble.whiten(data, 37) != ble.whiten(data, 38) != data


def test_a_packet_made_here_is_found_and_read_back():
    x = air([adv("C0:11:22:33:44:55", name="nrtrail-tag", company=0x004C), adv("00:1A:7D:DA:71:13", kind=2, random=False)], 37)
    res = ble.find_packets(x, 37)
    assert res["crc_failed"] == 0 and len(res["packets"]) == 2
    a, b = res["packets"]
    assert a["pdu_type"] == "ADV_IND" and a["address"] == "C0:11:22:33:44:55" and a["address_type"] == "random"
    assert a["name"] == "nrtrail-tag" and a["company_id"] == 0x004C and a["company"] == "Apple"
    assert b["pdu_type"] == "ADV_NONCONN_IND" and b["address_type"] == "public" and "name" not in b
    assert abs(a["power_db"] - (-6.0)) < 0.5                                   # 크기 0.5 → −6 dB


def test_survives_frequency_offset_and_noise_and_rejects_the_wrong_channel():
    pdu = adv("C0:11:22:33:44:55", name="x")
    for cfo in (-60e3, 60e3):
        res = ble.find_packets(air([pdu] * 3, 38, noise=0.05, cfo_hz=cfo), 38)
        assert len(res["packets"]) == 3 and abs(res["packets"][0]["cfo_hz"] - cfo) < 30e3   # 어긋남 추정은 거칠다(프리앰블 8비트뿐)
    wrong = ble.find_packets(air([pdu], 38), 39)                                # 다른 채널의 화이트닝으로 풀면 CRC 가 안 맞는다
    assert wrong["packets"] == [] and wrong["crc_failed"] == 1
    rng = np.random.default_rng(0)
    noise = (rng.standard_normal(400_000) + 1j * rng.standard_normal(400_000)).astype(np.complex64) * 0.1
    assert ble.find_packets(noise, 37) == {"packets": [], "crc_failed": 0}


def test_packets_aimed_at_one_device_are_counted_but_not_read():
    connect = bytes([5 | 0x40, 34]) + bytes(34)                                 # CONNECT_IND: 연결을 따라갈 값이 들어 있는 종류
    scan_req = bytes([3, 12]) + bytes(12)
    res = ble.find_packets(air([connect, scan_req, adv("C0:11:22:33:44:55", name="tag")], 37), 37)
    assert [p["pdu_type"] for p in res["packets"]] == ["CONNECT_IND", "SCAN_REQ", "ADV_IND"]
    assert "address" not in res["packets"][0] and not res["packets"][0]["broadcast"]
    summary = ble.summarize(res["packets"], 37)
    assert summary["directed"] == {"CONNECT_IND": 1, "SCAN_REQ": 1}
    assert [d["address"] for d in summary["devices"]] == ["C0:11:22:33:44:55"]


def test_devices_are_grouped_by_address():
    pkts = ble.find_packets(air([adv("AA:AA:AA:AA:AA:AA", name="a"), adv("AA:AA:AA:AA:AA:AA", company=0x0075, kind=4),
                                 adv("BB:BB:BB:BB:BB:BB")], 39), 39)["packets"]
    devs = ble.summarize(pkts, 39)["devices"]
    a = next(d for d in devs if d["address"].startswith("AA"))
    assert a["count"] == 2 and a["name"] == "a" and a["company"] == "Samsung" and a["pdu_types"] == ["ADV_IND", "SCAN_RSP"] and a["channel"] == 39
    assert len(devs) == 2


def test_scan_tunes_the_advertising_channel_and_refuses_what_it_cannot_do(tmp_path, monkeypatch):
    monkeypatch.setattr(ble, "sessions_dir", lambda: tmp_path)
    monkeypatch.setattr(devices, "find_device", lambda _id: {"driver": "uhd", "freq_min_hz": 70e6, "freq_max_hz": 6e9, "max_sample_rate_hz": 56e6})
    asked = []

    def fake_capture(_dev, req, out_meta):
        asked.append((req.center_freq_hz, req.sample_rate_hz, req.duration_s, req.gain_db))
        sigmf.write_capture(out_meta, air([adv("C0:11:22:33:44:55", name="tag")], 38), sample_rate_hz=ble.RATE_HZ, center_freq_hz=req.center_freq_hz, source="device")
        return sigmf.read_meta(out_meta)

    monkeypatch.setattr(devices, "capture", fake_capture)
    out = ble.scan("usrp:B200:1", 38, gain_db=40)
    assert asked == [(2426e6, 4e6, ble.DWELL_S, 40)]
    assert out["packets"] == 1 and out["devices"][0]["name"] == "tag" and out["crc_failed"] == 0 and not out["clipped"]
    with pytest.raises(ble.BleError, match="37, 38, 39"):
        ble.scan("usrp:B200:1", 5)
    with pytest.raises(ble.BleError, match="시간"):
        ble.scan("usrp:B200:1", 37, seconds=10)
    monkeypatch.setattr(devices, "find_device", lambda _id: {"driver": "simulated"})
    with pytest.raises(ble.BleError, match="모의 장비"):
        ble.scan("simulated:x", 37)


def test_this_module_never_transmits():
    import re
    from pathlib import Path
    code = Path(ble.__file__).read_text(encoding="utf-8")
    assert not re.search(r"SOAPY_SDR_TX|writeStream|SDRuTransmitter|tx\.start|nrtrail\.tx", code)
