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

    assert shifted["fit"] > 0.9 and keyed["fit"] > 0.9                   # 토막들이 심볼 길이의 배수에 잘 맞는다
    # 폭을 넓게 골라 잡음이 많이 섞여도(값이 바뀌는 순간마다 잡티가 생긴다) 심볼 길이를 잡티에 맞추지 않는다
    wide = analyze.demodulate(cap, 0.295, len(tone) / RATE + 0.01, offset_hz=-300e3, bandwidth_hz=900e3, kind="fsk")
    assert abs(wide["symbol_s"] - 200e-6) < 25e-6 and want in wide["packets"][0]["bits"]

    with pytest.raises(analyze.AnalyzeError):
        analyze.demodulate(cap, 0.04, 0.09, offset_hz=0, bandwidth_hz=0)     # 신호를 고르지 않았다
    with pytest.raises(analyze.AnalyzeError):
        analyze.demodulate(cap, 0.2, 0.02, offset_hz=0, bandwidth_hz=100e3)  # 잡음뿐인 곳: 방식을 알 수 없다


def test_glitches_do_not_set_the_symbol_length():
    level = np.repeat(np.array([1, 0, 1, 0, 1, 1, 0, 0, 1, 0, 1, 0, 1, 0], dtype=bool), 100)
    for at in (100, 300, 500, 900, 1100):                              # 값이 바뀌는 순간마다 세 샘플짜리 잡티
        level[at + 4: at + 7] = ~level[at + 4: at + 7]
    unit = analyze.symbol_length(level)
    assert 90 < unit < 110
    clean = analyze.tidy(level, unit * 0.35)
    assert analyze.slice_bits(clean, analyze.symbol_length(clean)) == "10101100101010"
    assert analyze.beat_fit(clean, 100) > 0.95 and analyze.beat_fit(clean, 37) < 0.6


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


def test_columns_tell_fixed_fields_from_changing_ones_and_spot_a_counter():
    rows = ["1100" + format(n, "08b") + "1111" + r for n, r in zip((5, 6, 7), ("0110100", "1010011", "0001110"), strict=True)]
    out = analyze.columns(rows)
    assert out["length"] == 23 and out["mask"].startswith("====") and out["groups"] == [[0], [1], [2]]
    kinds = [(f["start"], f["length"], f["kind"]) for f in out["fields"]]
    assert kinds[0] == (0, 10, "same") and out["fields"][0]["bits"] == "1100000001"   # 머리 4자리 + 세는 값의 안 바뀌는 윗자리
    counter = next(f for f in out["fields"] if f["kind"] == "varies")
    assert counter["distinct"] == 3 and counter.get("step") == 1          # 누를 때마다 1 씩 늘어난다
    assert out["distance"][0][0] == 0 and out["distance"][0][1] == out["distance"][1][0] > 0
    assert analyze.columns(["1010", "1010"])["groups"] == [[0, 1]]         # 내용이 같은 줄은 한 묶음


def test_preamble_end_and_manchester_with_violations():
    assert analyze.preamble_end("0" + "10" * 12 + "0110") == (0, 25)        # 번갈아 나오기가 깨지는 자리부터가 내용
    assert analyze.preamble_end("110011") == (0, 0)
    out = analyze.manchester_from("1001" * 3 + "11" + "0110")
    assert out["bits"] == "101010?01" and out["errors"] == 1 and out["broken_at"] == [6]
    assert analyze.repeat_period(("1011001110001011" * 3 + "0") * 3) == 49


def test_compare_decodes_every_burst_and_separates_signal_from_data(tmp_path):
    rng = np.random.default_rng(9)
    n = int(RATE * 0.6)
    iq = (rng.normal(0, 1e-3, n) + 1j * rng.normal(0, 1e-3, n)).astype(np.complex64)
    ident = [1, 1, 0, 0, 1, 0, 1, 1, 0, 0, 1, 0]
    for k, at in enumerate((0.05, 0.25, 0.45)):                          # 세 번 누른 것: 고정된 번호 + 누를 때마다 느는 값 + 끝 표시
        counter = [int(c) for c in format(9 + k, "06b")]
        bits = [1, 0] * 20 + [1, 1] + ident + counter + [1, 1, 1, 0, 0, 0, 1, 1]
        tone = fsk(bits, -300e3 + 400 * k)                                # 누를 때마다 반송파가 400 Hz 씩 밀린다(신호의 차이)
        iq[int(at * RATE): int(at * RATE) + len(tone)] += tone
    cap = analyze.source(str(write(tmp_path, iq)))
    out = analyze.compare(cap, offset_hz=-300e3, bandwidth_hz=200e3)
    assert out["kind"] == "fsk" and out["decoded"] == [0, 1, 2]
    # 신호: 편이와 심볼 속도는 셋이 같고, 반송파는 조금씩 다르다
    assert abs(out["signal"]["deviation_hz"]["mean"] - 40e3) < 3e3 and abs(out["signal"]["symbol_rate_hz"]["mean"] - 5000) < 60
    carriers = [b["carrier_offset_hz"] for b in out["bursts"]]
    assert all(abs(c + 300e3) < 1.5e3 for c in carriers) and carriers[2] - carriers[0] > 500
    # 데이터: 앞머리 뒤를 0 번으로 맞추면 번호는 고정, 세는 값은 바뀐다
    assert all(b["preamble"]["length"] >= 38 for b in out["bursts"])
    sym = out["symbols"]
    assert sym["groups"] == [[0], [1], [2]] and sym["same"] > sym["varies"] > 0
    assert any(f["kind"] == "same" and "".join(map(str, ident)) in f["bits"] for f in sym["fields"])
    assert any(f["kind"] == "varies" and f.get("step") == 1 for f in sym["fields"])
    # 겹쳐 보기: 버스트마다 같은 길이의 줄
    lines = out["traces"]["lines"]
    assert len(lines) == 3 and len({len(line) for line in lines}) == 1


def test_compare_needs_bursts(tmp_path):
    cap = analyze.source(str(write(tmp_path, np.zeros(200_000) + 1e-4)))
    with pytest.raises(analyze.AnalyzeError):
        analyze.compare(cap)


def test_frames_are_split_at_markers_and_aligned_one_by_one():
    """앞 프레임의 길이가 줄마다 달라도, 표시 뒤의 프레임은 그 시작에 맞춰 견준다(밀려서 "다르다"고 나오지 않는다)."""
    mark = "111110000001"
    tail = "0101" * 3 + "1001011010011001"
    rows = ["1001" * 5 + mark + tail, "1001" * 6 + mark + tail, "0110" * 4 + mark + tail]     # 앞 프레임 길이 20, 24, 16
    assert analyze.marker_spans(rows[0]) == [(19, 31)]              # 표시 바로 앞의 같은 심볼 하나는 표시에 붙어 잡힌다
    whole = analyze.columns(rows)
    frames = analyze.frames_of(rows)
    assert whole["varies"] > 10                                                          # 통째로 맞추면 뒤가 밀려 다르게 나온다
    assert [f["lengths"] for f in frames] == [[19, 23, 16], [29, 29, 29]]
    assert frames[1]["symbols"]["varies"] == 0 and frames[1]["symbols"]["groups"] == [[0, 1, 2]]   # 표시 뒤는 셋이 같다
    assert frames[1]["marker_before"] == ["11111000000", "111111000000"] and frames[1]["manchester"]["varies"] == 0
    assert frames[0]["symbols"]["varies"] > 0
    assert analyze.frames_of(["1001" * 6, "0110" * 6]) is None                            # 표시가 없으면 나누지 않는다
    # 한 번 누를 때 같은 패킷을 두 번 보내는 기기: 프레임의 끝부분이 서로 같다
    body = tail + "0110" * 6
    twice = analyze.frames_of(["1001" * 2 + body + mark + body + mark, "0110" * 2 + body + mark + body + mark])
    again = analyze.repeats_within(twice)
    assert again["same"] == 2 and again["of"] == 2 and again["frames"] == 2 and again["length"] >= 16
    assert analyze.repeats_within(frames) is None                                       # 견줄 만큼 길지 않으면 말하지 않는다
