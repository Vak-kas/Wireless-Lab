"""저장한 I/Q 파일을 뜯어보는 것(analyze). 만든 신호로 본다: 켜고 끄는 신호(OOK) 버스트와 주파수를 바꾸는 신호(FSK)."""
from types import SimpleNamespace

import numpy as np
import pytest
from nrtrail import analyze, sigmf

RATE = 2e6


def write(folder, iq, datatype="ci16_le", name="rec"):
    meta = folder / f"{name}.sigmf-meta"
    flat = iq.astype(np.complex64).view(np.float32)
    (np.rint(flat * 32768).astype("<i2") if datatype == "ci16_le" else flat.astype("<f4")).tofile(sigmf.data_path_for(meta))
    sigmf.write_meta(meta, datatype=datatype, sample_rate_hz=RATE, center_freq_hz=433.92e6, source="device")
    return meta


def ook(bits, offset_hz, symbol_s=200e-6, level=0.3):
    """bits 대로 켜고 끄는 신호. 가운데에서 offset_hz 떨어진 주파수."""
    per = int(RATE * symbol_s)
    gate = np.repeat(np.asarray(bits, dtype=np.float32), per)
    return level * gate * np.exp(2j * np.pi * offset_hz / RATE * np.arange(len(gate)))


def fsk(bits, offset_hz, deviation_hz=40e3, symbol_s=200e-6, level=0.3):
    per = int(RATE * symbol_s)
    freq = offset_hz + deviation_hz * (2 * np.repeat(np.asarray(bits, dtype=np.float32), per) - 1)
    return level * np.exp(2j * np.pi * np.cumsum(freq) / RATE)


@pytest.fixture
def recording(tmp_path):
    rng = np.random.default_rng(3)
    n = int(RATE * 0.5)
    iq = (rng.normal(0, 1e-3, n) + 1j * rng.normal(0, 1e-3, n)).astype(np.complex64)
    bits = rng.integers(0, 2, 60).tolist()
    key = ook([1, 0, 1, 0, 1, 0, 1, 0] + bits, 200e3)              # 0.1 초에: 켜고 끄는 신호, +200 kHz
    iq[int(0.1 * RATE): int(0.1 * RATE) + len(key)] += key
    tone = fsk(bits, -300e3)                                        # 0.3 초에: 주파수를 바꾸는 신호, -300 kHz
    iq[int(0.3 * RATE): int(0.3 * RATE) + len(tone)] += tone
    return analyze.source(str(write(tmp_path, iq))), len(key) / RATE, len(tone) / RATE


def test_open_scans_the_whole_file_and_finds_the_bursts(recording):
    cap, key_s, tone_s = recording
    out = analyze.open_file(cap)
    assert out["file"]["samples"] == int(RATE * 0.5) and out["file"]["center_hz"] == 433.92e6
    assert len(out["envelope"]["peak_db"]) <= analyze.ENVELOPE_POINTS and out["spectrogram"]["rows"] == analyze.ROWS
    found = out["bursts"]
    assert len(found) == 2                                         # 켜고 끄는 신호의 짧은 꺼짐들은 한 버스트로 이어진다
    assert abs(found[0]["start_s"] - 0.1) < 2e-3 and abs(found[0]["seconds"] - key_s) < 4e-3
    assert abs(found[1]["start_s"] - 0.3) < 2e-3 and abs(found[1]["seconds"] - tone_s) < 4e-3
    assert found[0]["above_floor_db"] > 30
    assert analyze.open_file(cap)["scan_s"] == out["scan_s"]       # 같은 파일은 다시 훑지 않는다


def test_detail_measures_where_the_signal_sits_and_guesses_how_it_is_keyed(recording):
    cap, key_s, tone_s = recording
    whole = analyze.detail(cap, 0.1, key_s)
    assert abs(whole["occupied"]["center_offset_hz"] - 200e3) < 15e3          # 가운데에서 +200 kHz
    picked = analyze.detail(cap, 0.1, key_s, offset_hz=200e3, bandwidth_hz=60e3)
    assert picked["modulation"]["kind"] == "ook"
    assert abs(picked["modulation"]["shortest_on_s"] - 200e-6) < 60e-6        # 심볼 하나 200 us
    assert len(picked["wave"]["max"]) <= analyze.TRACE_POINTS and picked["wave"]["rate_hz"] < RATE
    assert len(picked["constellation"]["i"]) > 100

    # 구간을 앞뒤로 넉넉히 잡아도(조용한 여유가 붙어도) 같은 답이 나온다
    assert analyze.detail(cap, 0.295, tone_s + 0.01, offset_hz=-300e3, bandwidth_hz=200e3)["modulation"]["kind"] == "fsk"
    assert analyze.detail(cap, 0.095, key_s + 0.01, offset_hz=200e3, bandwidth_hz=60e3)["modulation"]["kind"] == "ook"
    tone = analyze.detail(cap, 0.3, tone_s, offset_hz=-300e3, bandwidth_hz=200e3)
    assert tone["modulation"]["kind"] == "fsk" and abs(tone["modulation"]["deviation_hz"] - 40e3) < 12e3
    seen = [f for f in tone["inst_freq_hz"] if f is not None]
    assert min(seen) < -25e3 and max(seen) > 25e3                             # 순간 주파수가 두 값 사이를 오간다

    quiet = analyze.detail(cap, 0.45, 0.02)
    assert quiet["power_db"] < -50 and quiet["modulation"]["kind"] == "unpicked"  # 신호를 고르지 않았으면 추정하지 않는다
    assert analyze.detail(cap, 0.45, 0.02, offset_hz=0, bandwidth_hz=100e3)["modulation"]["kind"] == "unknown"  # 잡음뿐인 곳은 모른다고 한다
    assert whole["modulation"]["kind"] == "unpicked"


def test_demodulate_turns_the_picked_signal_into_bits(tmp_path):
    rng = np.random.default_rng(5)
    bits = [1, 0, 1, 0, 1, 0, 1, 0, 1, 1, 0, 0, 1, 0, 1, 1, 0, 1, 0, 0, 1, 1, 1, 0, 1, 0, 0, 0, 1, 1, 0, 1]
    want = "".join(map(str, bits))
    n = int(RATE * 0.4)
    iq = (rng.normal(0, 1e-3, n) + 1j * rng.normal(0, 1e-3, n)).astype(np.complex64)
    key = ook(bits, 200e3)
    for at in (0.05, 0.10):                                             # 같은 패킷을 두 번 보낸다(리모컨처럼)
        iq[int(at * RATE): int(at * RATE) + len(key)] += key
    tone = fsk(bits, -300e3)
    iq[int(0.3 * RATE): int(0.3 * RATE) + len(tone)] += tone
    cap = analyze.source(str(write(tmp_path, iq)))

    keyed = analyze.demodulate(cap, 0.04, 0.09, offset_hz=200e3, bandwidth_hz=60e3)
    assert keyed["kind"] == "ook" and abs(keyed["symbol_s"] - 200e-6) < 15e-6
    assert [p["bits"] for p in keyed["packets"]] == [want.rstrip("0"), want.rstrip("0")]   # 끝의 꺼짐은 내용에서 뺀다
    assert keyed["packets"][0]["repeats"] == 2 and abs(keyed["packets"][1]["start_s"] - 0.10) < 1e-3
    assert keyed["packets"][0]["hex"] == analyze.to_hex(want.rstrip("0"))

    shifted = analyze.demodulate(cap, 0.295, len(tone) / RATE + 0.01, offset_hz=-300e3, bandwidth_hz=200e3)
    assert shifted["kind"] == "fsk" and len(shifted["packets"]) == 1
    assert want in shifted["packets"][0]["bits"]                          # 앞뒤 가장자리에 한두 비트가 더 붙을 수 있다
    forced = analyze.demodulate(cap, 0.295, len(tone) / RATE + 0.01, offset_hz=-300e3, bandwidth_hz=200e3, kind="fsk", symbol_s=200e-6)
    assert want in forced["packets"][0]["bits"]

    with pytest.raises(analyze.AnalyzeError):
        analyze.demodulate(cap, 0.04, 0.09, offset_hz=0, bandwidth_hz=0)     # 신호를 고르지 않았다
    with pytest.raises(analyze.AnalyzeError):
        analyze.demodulate(cap, 0.2, 0.02, offset_hz=0, bandwidth_hz=100e3)  # 잡음뿐인 곳: 방식을 알 수 없다


def test_manchester_is_recognised_and_hex_pads_the_tail():
    assert analyze.manchester("1001" * 4 + "0110" * 2) == "10" * 4 + "01" * 2
    assert analyze.manchester("0" + "1001" * 6) == "10" * 6             # 두 칸씩 끊는 자리가 한 칸 밀려 있어도 찾는다
    assert analyze.manchester("1110" * 6) is None                        # 어느 자리에서 끊어도 "11" 이 나온다: 맨체스터가 아니다
    assert analyze.to_hex("10101") == "A8" and analyze.to_hex("11110000") == "F0"


def test_long_windows_are_read_sparsely_and_say_so(recording, monkeypatch):
    cap, *_ = recording
    monkeypatch.setattr(analyze, "MAX_DETAIL_SAMPLES", 100_000)
    out = analyze.detail(cap, 0.0, 0.5)
    assert out["coarse"] and "constellation" not in out and len(out["wave"]["max"]) > 100
    assert out["spectrogram"]["cols"] == analyze.DETAIL_COLS


def test_cut_writes_only_the_window_and_never_overwrites(recording):
    cap, key_s, _ = recording
    made = analyze.cut(cap, 0.1, key_s)
    piece = sigmf.read_meta(made["meta_path"])
    assert piece.num_samples == round(key_s * RATE) and piece.sample_rate_hz == RATE and piece.center_freq_hz == 433.92e6
    assert np.allclose(piece.read(0, 50), cap.read(int(0.1 * RATE), 50))
    assert analyze.cut(cap, 0.1, key_s)["meta_path"] != made["meta_path"]


def test_raw_files_need_a_sample_rate_and_other_files_are_refused(tmp_path, monkeypatch):
    raw = tmp_path / "x.cfile"
    np.zeros(2000, dtype="<f4").tofile(raw)
    with pytest.raises(analyze.AnalyzeError):
        analyze.source(str(raw))                                    # 설명이 없는 형식: 샘플 속도를 받아야 한다
    cap = analyze.source(str(raw), sample_rate_hz=1e6, center_hz=100e6)
    assert cap.num_samples == 1000 and cap.datatype == "cf32_le"
    for bad in (tmp_path / "notes.txt", tmp_path / "gone.sigmf-meta"):
        with pytest.raises(analyze.AnalyzeError):
            analyze.source(str(bad))
    monkeypatch.setattr(analyze.sys, "platform", "darwin")
    monkeypatch.setattr(analyze, "run", lambda cmd, **_: SimpleNamespace(returncode=0, stdout=f"{raw}\n"))
    assert analyze.choose_file() == str(raw)
    monkeypatch.setattr(analyze, "run", lambda cmd, **_: SimpleNamespace(returncode=1, stdout=""))
    assert analyze.choose_file() is None                            # 취소


def test_recent_lists_recordings_in_the_save_folder_newest_first(tmp_path, monkeypatch):
    monkeypatch.setattr(analyze, "folder", lambda: tmp_path)
    write(tmp_path, np.zeros(1000), name="a")
    assert [f["name"] for f in analyze.recent()] == ["a.sigmf-data"]
