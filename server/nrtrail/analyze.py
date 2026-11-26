"""저장해 둔 I/Q 파일을 열어 뜯어보는 것(신호 분석). 장비는 쓰지 않는다. numpy 만 쓴다.

하는 일 (화면의 "신호 분석"이 이 순서로 부른다)
    1. open_file   파일을 처음부터 끝까지 한 번 훑어 시간에 따른 세기(envelope)를 만들고, 켜졌다 꺼지는 구간(버스트)을 찾고,
                   파일 전체의 스펙트로그램을 성기게 그린다.
    2. detail      고른 시간 구간을 자세히 본다: 스펙트로그램, 스펙트럼, 시간 파형, 순간 주파수, 성상도, 잰 값들.
                   offset_hz 와 bandwidth_hz 를 주면 그 주파수의 신호만 골라내고(가운데로 옮긴 뒤 저역 통과) 본다.
    3. demodulate  고른 신호를 0·1 로 푼다(켜고 끄는 신호와 주파수를 바꾸는 신호). 패킷마다 비트와 HEX 를 내놓는다.
    4. cut         고른 구간만 새 SigMF 파일로 잘라 낸다.

큰 파일
    몇 GB 짜리도 메모리에 다 올리지 않는다. 훑기는 조각(CHUNK_SAMPLES)씩 읽어 블록마다 최대·평균 세기만 남기고,
    자세히 보기는 필요한 구간만 읽는다(구간이 MAX_DETAIL_SAMPLES 보다 길면 띄엄띄엄 읽고 coarse 로 알린다).
    훑은 결과는 (경로, 고친 시각, 크기)로 기억해 두어 같은 파일을 다시 열면 바로 나온다.

어디까지 하는가 (2026-11-26 사용자 결정으로 비트까지)
    저장한 파일의 신호를 0·1 과 HEX 로 보여 주는 데까지 한다. 그 비트가 무슨 뜻인지(어떤 명령·주소·암호인지)는 해석하지 않는다.
    변조 방식은 모양으로 **추정**한다(켜고 끄는 방식인지, 주파수를 바꾸는 방식인지). 틀릴 수 있어 화면에서 바꿀 수 있다.
    푼 비트를 다시 내보내는 것(재전송)은 이 도구가 하지 않는다(남의 기기인 척하는 송신은 CLAUDE.md 의 금지 항목이다).

단위: 시간은 초, 주파수는 Hz, 세기는 dBFS(장비가 표현할 수 있는 최대 크기를 0 dB 로 본 값. 절대 전력이 아니다).
파일의 주파수 축은 "녹화한 가운데 주파수에서 얼마나 떨어졌는가"(offset)로 다룬다. 0 이 가운데다.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from . import sigmf
from .paths import sessions_dir

CHUNK_SAMPLES = 1 << 22            # 훑을 때 한 번에 읽는 복소 샘플 수
MAX_BLOCKS = 200_000               # 시간에 따른 세기를 이만큼의 블록으로 남긴다(파일이 길면 블록이 길어진다)
BLOCK_S = 1e-3                     # 블록 하나의 기본 길이(1 ms). 이보다 짧은 신호도 블록의 최대값에 잡힌다
ENVELOPE_POINTS = 1200             # 화면에 보내는 세기 줄의 점 수
OVERVIEW_COLS = 360                # 전체 스펙트로그램의 시간 칸 수
DETAIL_COLS = 400                  # 자세히 보기 스펙트로그램의 시간 칸 수
FFT_BINS = 1024
ROWS = 256                         # 스펙트로그램의 주파수 칸 수(FFT_BINS 를 줄여 보낸다)
TRACE_POINTS = 800                 # 시간 파형·순간 주파수의 점 수
MAX_DETAIL_SAMPLES = 16_000_000    # 자세히 보기에서 통째로 읽는 한도(29 MS/s 로 0.55초). 넘으면 띄엄띄엄 읽는다
CONSTELLATION_POINTS = 1500
OCCUPIED_DROP_DB = 15.0            # 차지한 폭: 가장 센 값에서 이만큼 안에 드는 주파수의 범위
BURST_RISE_DB = 10.0               # 바닥보다 이만큼 세면 켜진 것으로 본다
BURST_GAP_S = 5e-3                 # 이보다 짧게 꺼진 틈은 한 버스트로 잇는다
MAX_BURSTS = 300
RAW_TYPES = {".cfile": "cf32_le", ".cf32": "cf32_le", ".iq": "cf32_le", ".cs16": "ci16_le", ".sc16": "ci16_le"}

run = subprocess.run               # 테스트가 가짜로 바꾼다(파일 고르는 창을 띄우지 않게)
_scans: dict[tuple[str, float, int, float], dict[str, Any]] = {}


class AnalyzeError(ValueError):
    pass


# ── 파일 열기 ──────────────────────────────────────────────────────────────────

def source(path: str, sample_rate_hz: float | None = None, center_hz: float | None = None) -> sigmf.Capture:
    """분석할 파일. SigMF(.sigmf-meta 또는 .sigmf-data)는 설명 파일에서 값을 읽고,
    날것 파일(.cfile, .cs16 …)은 설명이 없으므로 샘플 속도를 받아야 한다."""
    p = Path(path.strip()).expanduser()
    if p.name.endswith(".sigmf-data"):
        p = p.with_name(p.name[: -len(".sigmf-data")] + ".sigmf-meta")
    if p.name.endswith(".sigmf-meta"):
        try:
            return sigmf.read_meta(p)
        except sigmf.SigmfError as e:
            raise AnalyzeError(str(e)) from e
    datatype = RAW_TYPES.get(p.suffix.lower())
    if datatype is None:
        raise AnalyzeError("열 수 있는 것은 SigMF(.sigmf-meta / .sigmf-data)와 날것 I/Q(.cfile, .cf32, .iq, .cs16, .sc16)입니다.")
    if not p.is_file():
        raise AnalyzeError(f"파일이 없습니다: {p}")
    if not sample_rate_hz or sample_rate_hz <= 0:
        raise AnalyzeError("이 형식에는 설명이 들어 있지 않습니다. 샘플 속도를 적어 주세요.")
    return sigmf.Capture(meta_path=p, data_path=p, datatype=datatype, sample_rate_hz=float(sample_rate_hz), center_freq_hz=float(center_hz or 0.0),
                         num_samples=p.stat().st_size // sigmf.DTYPES[datatype][1], source="file", testbed=False, extra={})


def describe(cap: sigmf.Capture) -> dict[str, Any]:
    return {"path": str(cap.meta_path), "name": cap.data_path.name, "datatype": cap.datatype, "sample_rate_hz": cap.sample_rate_hz,
            "center_hz": cap.center_freq_hz, "samples": cap.num_samples, "seconds": round(cap.duration_s, 6), "bytes": cap.data_path.stat().st_size}


def folder() -> Path:
    """녹화가 저장되는 폴더(사용자가 고른 곳). saved 모듈이 없는 설치에서는 sessions/saved."""
    try:
        from . import saved
        return saved.folder()
    except ImportError:
        return sessions_dir() / "saved"


def recent(limit: int = 30) -> list[dict[str, Any]]:
    """저장 폴더에 있는 녹화들(새것부터)."""
    out = []
    metas = sorted(folder().glob("*.sigmf-meta"), key=lambda p: p.stat().st_mtime, reverse=True) if folder().is_dir() else []
    for meta in metas[:limit]:
        try:
            cap = sigmf.read_meta(meta)
        except sigmf.SigmfError:
            continue
        out.append(describe(cap) | {"modified": meta.stat().st_mtime})
    return out


def choose_file() -> str | None:
    """운영체제의 파일 고르는 창. 고르면 그 경로, 취소하면 None."""
    if sys.platform != "darwin":
        raise AnalyzeError("이 운영체제에서는 파일 고르는 창을 띄울 수 없습니다. 경로를 직접 적어 주세요.")
    try:
        done = run(["osascript", "-e", "activate", "-e", 'POSIX path of (choose file with prompt "분석할 I/Q 파일 (.sigmf-meta, .sigmf-data, .cfile, .cs16)")'],
                   capture_output=True, text=True, timeout=600)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise AnalyzeError("파일 고르는 창을 띄우지 못했습니다. 경로를 직접 적어 주세요.") from e
    picked = (done.stdout or "").strip()
    return picked if done.returncode == 0 and picked else None


# ── 숫자 도구 ──────────────────────────────────────────────────────────────────

def db(power: np.ndarray | float) -> Any:
    """세기(진폭의 제곱)를 dB 로. 0 은 아주 작은 값으로 막는다."""
    return 10.0 * np.log10(np.maximum(power, 1e-12))


def pool_max(x: np.ndarray, points: int) -> np.ndarray:
    """x 를 points 개로 줄인다(구간마다 최대값). 줄일 것이 없으면 그대로."""
    if len(x) <= points:
        return x
    edges = np.linspace(0, len(x), points + 1).astype(int)
    return np.maximum.reduceat(x, edges[:-1])


def pool_mean(x: np.ndarray, points: int) -> np.ndarray:
    if len(x) <= points:
        return x
    edges = np.linspace(0, len(x), points + 1).astype(int)
    return np.add.reduceat(x, edges[:-1]) / np.maximum(np.diff(edges), 1)


def spectra(frames: np.ndarray) -> np.ndarray:
    """프레임들(줄마다 nfft 샘플)의 세기 스펙트럼(dB). 주파수는 낮은 쪽 → 높은 쪽으로 정렬한다(가운데가 0)."""
    nfft = frames.shape[1]
    win = np.hanning(nfft).astype(np.float32)
    spec = np.fft.fftshift(np.fft.fft(frames * win, axis=1), axes=1)
    return db((np.abs(spec) ** 2) / (win.sum() ** 2))


def rows_of(spec_db: np.ndarray, rows: int = ROWS) -> np.ndarray:
    """스펙트럼의 주파수 칸을 rows 개로 줄인다(구간마다 최대값: 좁은 신호가 사라지지 않게)."""
    bins = spec_db.shape[1]
    if bins <= rows:
        return spec_db
    return spec_db.reshape(spec_db.shape[0], rows, bins // rows).max(axis=2)


def frames_at(cap: sigmf.Capture, starts: np.ndarray, nfft: int) -> np.ndarray:
    """starts(샘플 번호)마다 nfft 샘플씩 읽은 것. 파일 끝을 넘는 것은 0 으로 채운다."""
    out = np.zeros((len(starts), nfft), dtype=np.complex64)
    for k, s in enumerate(starts):
        got = cap.read(int(s), nfft)
        out[k, : len(got)] = got
    return out


# ── 1. 파일 전체 훑기 ──────────────────────────────────────────────────────────

def scan(cap: sigmf.Capture) -> dict[str, Any]:
    """파일을 처음부터 끝까지 읽어 블록마다 최대·평균 세기를 남긴다. 결과는 기억해 둔다."""
    stat = cap.data_path.stat()
    key = (str(cap.data_path), stat.st_mtime, stat.st_size, cap.sample_rate_hz)
    if key in _scans:
        return _scans[key]
    began = time.monotonic()
    block = max(1, int(round(cap.sample_rate_hz * BLOCK_S)), -(-cap.num_samples // MAX_BLOCKS))
    per_chunk = max(1, CHUNK_SAMPLES // block)
    peak: list[np.ndarray] = []
    mean: list[np.ndarray] = []
    done = 0
    while done < cap.num_samples:
        iq = cap.read(done, per_chunk * block)
        if len(iq) == 0:
            break
        whole = (len(iq) // block) * block
        power = (iq.real ** 2 + iq.imag ** 2)
        if whole:
            grid = power[:whole].reshape(-1, block)
            peak.append(grid.max(axis=1))
            mean.append(grid.mean(axis=1))
        if whole < len(iq):                                    # 파일 끝의 자투리
            peak.append(np.array([power[whole:].max()]))
            mean.append(np.array([power[whole:].mean()]))
        done += len(iq)
    out = {"block_s": block / cap.sample_rate_hz, "peak": np.concatenate(peak) if peak else np.zeros(0),
           "mean": np.concatenate(mean) if mean else np.zeros(0), "took_s": round(time.monotonic() - began, 2)}
    if len(_scans) >= 4:
        _scans.pop(next(iter(_scans)))
    _scans[key] = out
    return out


def bursts(scanned: dict[str, Any]) -> tuple[list[dict[str, float]], float]:
    """켜졌다 꺼지는 구간들과 바닥(dBFS). 블록의 최대 세기가 바닥보다 BURST_RISE_DB 넘게 솟은 곳을 잇는다.

    바닥은 "블록 최대값"들의 아래쪽 20% 자리로 잡는다(솟았는지도 최대값으로 보므로 같은 것끼리 견준다).
    파일 내내 켜져 있는 신호는 조용한 때가 없어서 버스트로 잡히지 않는다.
    """
    peak_db = db(scanned["peak"])
    if len(peak_db) == 0:
        return [], 0.0
    floor = float(np.percentile(peak_db, 20))
    on = peak_db > floor + BURST_RISE_DB
    edges = np.diff(np.concatenate([[0], on.astype(np.int8), [0]]))
    begins, ends = np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)
    step = scanned["block_s"]
    merged: list[list[int]] = []
    for b, e in zip(begins, ends, strict=True):
        if merged and (b - merged[-1][1]) * step <= BURST_GAP_S:
            merged[-1][1] = int(e)
        else:
            merged.append([int(b), int(e)])
    found = [{"start_s": round(b * step, 6), "seconds": round((e - b) * step, 6), "peak_db": round(float(peak_db[b:e].max()), 1),
              "above_floor_db": round(float(peak_db[b:e].max()) - floor, 1)} for b, e in merged]
    return found[:MAX_BURSTS], floor


def open_file(cap: sigmf.Capture) -> dict[str, Any]:
    """파일 정보, 시간에 따른 세기, 버스트 목록, 전체 스펙트로그램."""
    if cap.num_samples < 64:
        raise AnalyzeError("파일이 너무 짧습니다.")
    scanned = scan(cap)
    found, floor = bursts(scanned)
    nfft = FFT_BINS if cap.num_samples >= FFT_BINS * 4 else 64
    cols = min(OVERVIEW_COLS, max(1, cap.num_samples // nfft))
    starts = np.linspace(0, cap.num_samples - nfft, cols).astype(np.int64)
    grid = rows_of(spectra(frames_at(cap, starts, nfft)))
    return {"file": describe(cap), "scan_s": scanned["took_s"], "block_s": scanned["block_s"], "floor_db": round(floor, 1),
            "envelope": {"peak_db": np.round(db(pool_max(scanned["peak"], ENVELOPE_POINTS)), 1).tolist(),
                         "mean_db": np.round(db(pool_mean(scanned["mean"], ENVELOPE_POINTS)), 1).tolist()},
            "bursts": found, "bursts_total": len(found),
            # 줄 하나가 시간 한 칸(열), 그 안의 값이 주파수 낮은 쪽 → 높은 쪽
            "spectrogram": {"cols": int(grid.shape[0]), "rows": int(grid.shape[1]), "db": np.round(grid, 1).tolist(),
                            "sparse": bool(cols * nfft < cap.num_samples)}}


# ── 2. 구간 자세히 보기 ────────────────────────────────────────────────────────

def lowpass(iq: np.ndarray, rate_hz: float, bandwidth_hz: float) -> tuple[np.ndarray, float]:
    """가운데(0 Hz) 둘레 bandwidth_hz 만 남기고, 그만큼 샘플을 솎아낸다. (솎은 신호, 새 샘플 속도)

    창을 씌운 sinc 필터(129 탭)다. 통과 폭의 가장자리는 완만하게 줄어든다(급하게 자르지 않는다).
    """
    cutoff = min(0.5, max(bandwidth_hz / rate_hz / 2.0, 1e-4))          # 샘플 속도에 대한 비율(한쪽)
    taps = 129
    n = np.arange(taps) - (taps - 1) / 2
    kernel = (2 * cutoff * np.sinc(2 * cutoff * n) * np.hamming(taps)).astype(np.float32)
    kernel /= kernel.sum()
    out = np.convolve(iq, kernel, mode="same")
    step = max(1, int(0.4 / cutoff))                                    # 솎은 뒤에도 통과 폭의 2.5배쯤은 남긴다
    return out[::step].astype(np.complex64), rate_hz / step


def runs(mask: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """참인 구간들의 (시작 번호, 길이)."""
    edges = np.diff(np.concatenate([[0], mask.astype(np.int8), [0]]))
    begins, ends = np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)
    return begins, ends - begins


def guess_modulation(iq: np.ndarray, rate_hz: float) -> dict[str, Any]:
    """모양으로 본 변조 방식(추정). 풀지는 않는다.

    켜진 구간만 놓고 본다(가장 센 값의 30% 넘는 곳).
      ook  켜고 끄는 방식: 켜진 구간이 여러 번 끊어져 나온다(켜짐과 꺼짐이 번갈아 온다)
      fsk  주파수를 바꾸는 방식: 켜진 동안 크기는 고른데 순간 주파수가 두 값 사이를 오간다
      psk  크기가 고르고 주파수도 한 값이다: 위상을 바꾸는 방식이거나, 아무것도 싣지 않은 반송파다
    함께 재는 것: 가장 짧은 켜짐 길이(심볼 하나의 길이에 가깝다)와 거기서 본 심볼 속도.
    """
    mag = np.abs(iq)
    top = float(mag.max()) if len(mag) else 0.0
    if top <= 0 or len(iq) < 64:
        return {"kind": "unknown"}
    on = mag > 0.3 * top
    # 신호가 처음 켜진 때부터 마지막으로 꺼진 때까지만 본다: 구간 앞뒤의 조용한 여유를 "꺼짐"으로 세지 않게
    where = np.flatnonzero(on)
    if len(where) < 32:
        return {"kind": "unknown"}
    iq, mag, on = iq[where[0]: where[-1] + 1], mag[where[0]: where[-1] + 1], on[where[0]: where[-1] + 1]
    begins, lengths = runs(on)
    lengths = lengths[lengths >= 3]                                      # 한두 샘플짜리는 잡음이다
    out: dict[str, Any] = {"kind": "unknown", "on_ratio": round(float(on.mean()), 3), "pulses": int(len(lengths))}
    if len(lengths):
        shortest = float(np.percentile(lengths, 10)) / rate_hz
        out["shortest_on_s"] = round(shortest, 7)
        out["symbol_rate_hz"] = round(1.0 / shortest, 1) if shortest > 0 else None
    inside = iq[on]
    if len(inside) < 32:
        return out
    step = inside[1:] * np.conj(inside[:-1])
    freq = np.angle(step) * rate_hz / (2 * np.pi)
    lo, hi = np.percentile(freq, [2, 98])
    out["freq_spread_hz"] = round(float(hi - lo), 1)
    ripple = float(np.std(np.abs(inside)) / max(np.mean(np.abs(inside)), 1e-9))
    # 주파수를 바꾸는 신호는 순간 주파수가 두 값에 몰리고 그 사이는 빈다. 값들의 범위(아래 2% ~ 위 2%)를 놓고
    # 가운데 40% 구간에 든 것이 적고(10% 미만) 양쪽에 고르게(각 20% 넘게) 있으면 두 값을 오가는 것으로 본다.
    # 한 주파수에 잡음이 얹힌 것은 가운데에 가장 많이 몰린다.
    middle_lo, middle_hi = lo + 0.3 * (hi - lo), lo + 0.7 * (hi - lo)
    low, high = freq[freq < middle_lo], freq[freq > middle_hi]
    in_middle = 1.0 - (len(low) + len(high)) / max(len(freq), 1)
    two_tones = in_middle < 0.10 and min(len(low), len(high)) > 0.2 * len(freq)
    # 주파수를 바꾸는지를 먼저 본다(그런 신호는 내내 켜져 있다). 그다음에 켜고 끄는지
    if ripple < 0.35 and two_tones and out["on_ratio"] > 0.9:
        tone_lo, tone_hi = float(np.median(low)), float(np.median(high))
        out["kind"] = "fsk"
        out["deviation_hz"] = round((tone_hi - tone_lo) / 2, 1)
        out["tones_hz"] = [round(tone_lo, 1), round(tone_hi, 1)]
        # 심볼 길이: 순간 주파수가 두 값의 한가운데를 넘나드는 사이의 가장 짧은 길이
        high = freq > (tone_lo + tone_hi) / 2
        _, a = runs(high)
        _, c = runs(~high)
        both = np.concatenate([a, c])
        both = both[both >= 3]
        if len(both):
            shortest = float(np.percentile(both, 10)) / rate_hz
            out["shortest_on_s"] = round(shortest, 7)
            out["symbol_rate_hz"] = round(1.0 / shortest, 1)
    elif len(lengths) >= 4 and 0.05 < out["on_ratio"] < 0.9 and np.percentile(lengths, 10) >= 8:
        out["kind"] = "ook"              # 켜진 토막이 여럿이고 토막마다 8샘플은 넘는다(잡음의 뾰족한 것들은 두세 샘플이다)
    elif ripple < 0.35 and len(lengths) <= 2 and (hi - lo) < 0.05 * rate_hz:
        out["kind"] = "psk"              # 크기도 주파수도 고르다(주파수가 넓게 흩어져 있으면 잡음이 섞인 것이라 말하지 않는다)
    return out


def detail(cap: sigmf.Capture, start_s: float, seconds: float, offset_hz: float = 0.0, bandwidth_hz: float = 0.0) -> dict[str, Any]:
    """구간 하나를 자세히. offset_hz·bandwidth_hz 를 주면 그 주파수의 신호만 골라 시간 파형·순간 주파수·성상도를 그린다
    (스펙트로그램과 스펙트럼은 언제나 받은 폭 전체를 보여 준다: 고른 자리가 어디인지 보이게)."""
    rate = cap.sample_rate_hz
    first = int(np.clip(round(start_s * rate), 0, max(cap.num_samples - 1, 0)))
    count = int(np.clip(round(seconds * rate), 64, cap.num_samples - first)) if cap.num_samples - first >= 64 else 0
    if count <= 0:
        raise AnalyzeError("구간이 파일 밖입니다.")
    if abs(offset_hz) > rate / 2:
        raise AnalyzeError(f"고를 수 있는 주파수는 가운데에서 ±{rate / 2e6:g} MHz 안입니다.")
    coarse = count > MAX_DETAIL_SAMPLES

    # 스펙트로그램·스펙트럼: 구간에 고르게 놓은 프레임들. 구간이 짧으면 FFT 를 줄여 시간 칸을 늘린다
    nfft = FFT_BINS
    while nfft > 64 and count < nfft * 16:
        nfft //= 2
    cols = min(DETAIL_COLS, max(1, count // max(nfft // 4, 1)))
    starts = first + np.linspace(0, max(count - nfft, 0), cols).astype(np.int64)
    spec = spectra(frames_at(cap, starts, nfft))
    grid = rows_of(spec)
    mean_line = db(np.mean(10 ** (spec / 10), axis=0))
    max_line = spec.max(axis=0)
    freqs = (np.arange(nfft) - nfft / 2) * rate / nfft

    # 차지한 폭: 가장 센 값에서 OCCUPIED_DROP_DB 안에 드는 주파수들의 범위(바닥보다 6 dB 는 솟아 있어야 한다).
    # 가운데는 세기로 가중한 평균. 센 신호는 옆으로 넓게 번져 보이므로 더 낮은 기준을 쓰면 폭이 부풀려진다
    floor_line = float(np.percentile(max_line, 25))
    lifted = max_line > max(floor_line + 6.0, float(max_line.max()) - OCCUPIED_DROP_DB)
    if lifted.any():
        idx = np.flatnonzero(lifted)
        weight = 10 ** (max_line[idx] / 10)
        occupied = {"center_offset_hz": round(float(np.sum(freqs[idx] * weight) / weight.sum()), 1),
                    "lo_hz": round(float(freqs[idx[0]]), 1), "hi_hz": round(float(freqs[idx[-1]] + rate / nfft), 1)}
        occupied["bandwidth_hz"] = round(occupied["hi_hz"] - occupied["lo_hz"], 1)
    else:
        occupied = None

    out: dict[str, Any] = {
        "start_s": round(first / rate, 7), "seconds": round(count / rate, 7), "samples": count, "coarse": coarse,
        "offset_hz": offset_hz, "bandwidth_hz": bandwidth_hz, "fft": nfft, "bin_hz": round(rate / nfft, 2),
        "spectrogram": {"cols": int(grid.shape[0]), "rows": int(grid.shape[1]), "db": np.round(grid, 1).tolist()},
        "spectrum": {"mean_db": np.round(mean_line, 1).tolist(), "max_db": np.round(max_line, 1).tolist(),
                     "lo_hz": float(freqs[0]), "hi_hz": float(freqs[-1] + rate / nfft)},
        "occupied": occupied,
    }

    if coarse:
        # 너무 길다: 통째로 읽지 않고 훑은 결과(블록마다의 최대·평균)로 세기만 보여 준다. 더 좁히면 나머지가 나온다
        scanned = scan(cap)
        b0, b1 = int(first / rate / scanned["block_s"]), int(np.ceil((first + count) / rate / scanned["block_s"]))
        out["wave"] = {"max": np.round(np.sqrt(pool_max(scanned["peak"][b0:b1], TRACE_POINTS)), 5).tolist(), "rate_hz": rate}
        out["power_db"] = round(float(db(scanned["mean"][b0:b1].mean())), 1)
        out["peak_db"] = round(float(db(scanned["peak"][b0:b1].max())), 1)
        return out

    iq = cap.read(first, count)
    out["power_db"] = round(float(db(np.mean(np.abs(iq) ** 2))), 1)
    out["peak_db"] = round(float(db(np.max(np.abs(iq) ** 2))), 1)
    picked, picked_rate = iq, rate
    if offset_hz:
        picked = picked * np.exp(-2j * np.pi * offset_hz / rate * np.arange(len(picked))).astype(np.complex64)
    if bandwidth_hz and bandwidth_hz < rate * 0.95:
        picked, picked_rate = lowpass(picked, rate, bandwidth_hz)
    mag = np.abs(picked)
    edges = np.linspace(0, len(picked), min(TRACE_POINTS, len(picked)) + 1).astype(int)[:-1]
    out["wave"] = {"max": np.round(np.maximum.reduceat(mag, edges), 5).tolist(), "min": np.round(np.minimum.reduceat(mag, edges), 5).tolist(),
                   "i": np.round(picked.real[edges], 5).tolist(), "q": np.round(picked.imag[edges], 5).tolist(), "rate_hz": picked_rate}

    # 순간 주파수: 이웃한 두 샘플 사이에 위상이 얼마나 돌았는가. 신호가 꺼진 곳(가장 센 값의 20% 아래)은 뜻이 없어 비운다
    if len(picked) > 2:
        turn = np.angle(picked[1:] * np.conj(picked[:-1])) * picked_rate / (2 * np.pi)
        loud = mag[1:] > 0.2 * mag.max() if mag.max() > 0 else np.zeros(len(turn), dtype=bool)
        e2 = np.linspace(0, len(turn), min(TRACE_POINTS, len(turn)) + 1).astype(int)
        freq_line: list[float | None] = []
        for a, b in zip(e2[:-1], e2[1:], strict=True):
            seg, ok = turn[a:max(b, a + 1)], loud[a:max(b, a + 1)]
            freq_line.append(round(float(np.median(seg[ok])), 1) if ok.any() else None)
        out["inst_freq_hz"] = freq_line

    # 성상도: 켜진 곳의 점들을 고르게 뽑아 크기를 1 둘레로 맞춘다. 주파수가 어긋나 있으면 원으로 번진다(그것도 정보다)
    strong = picked[mag > 0.3 * mag.max()] if mag.max() > 0 else picked[:0]
    if len(strong) > 8:
        take = strong[:: max(1, len(strong) // CONSTELLATION_POINTS)][:CONSTELLATION_POINTS]
        scale = float(np.sqrt(np.mean(np.abs(take) ** 2))) or 1.0
        out["constellation"] = {"i": np.round(take.real / scale, 3).tolist(), "q": np.round(take.imag / scale, 3).tolist()}
    # 변조 추정은 신호를 골랐을 때만 한다: 받은 폭 전체에는 잡음과 다른 신호가 섞여 있어 모양이 뭉개진다
    out["modulation"] = guess_modulation(picked, picked_rate) if bandwidth_hz and bandwidth_hz < rate * 0.95 else {"kind": "unpicked"}
    return out


# ── 3. 비트로 풀기 ─────────────────────────────────────────────────────────────

MAX_PACKETS = 60
MAX_BITS = 4096                    # 패킷 하나에서 내놓는 비트 수의 한도


def pick(cap: sigmf.Capture, start_s: float, seconds: float, offset_hz: float, bandwidth_hz: float) -> tuple[np.ndarray, float, int]:
    """구간에서 고른 주파수의 신호만 남긴 것: (신호, 그 샘플 속도, 구간의 첫 샘플 번호). detail 과 같은 길을 쓴다."""
    rate = cap.sample_rate_hz
    first = int(np.clip(round(start_s * rate), 0, max(cap.num_samples - 1, 0)))
    count = int(np.clip(round(seconds * rate), 0, cap.num_samples - first))
    if count < 64:
        raise AnalyzeError("구간이 너무 짧거나 파일 밖입니다.")
    if count > MAX_DETAIL_SAMPLES:
        raise AnalyzeError(f"구간이 너무 깁니다({count / rate:.2f}초). {MAX_DETAIL_SAMPLES / rate:.2f}초 안으로 좁혀 주세요.")
    if not bandwidth_hz or bandwidth_hz >= rate * 0.95:
        raise AnalyzeError("먼저 풀 신호를 고르세요(스펙트럼에서 누르거나 '이 신호 고르기').")
    iq = cap.read(first, count)
    if offset_hz:
        iq = iq * np.exp(-2j * np.pi * offset_hz / rate * np.arange(len(iq))).astype(np.complex64)
    out, out_rate = lowpass(iq, rate, bandwidth_hz)
    return out, out_rate, first


def to_hex(bits: str) -> str:
    """비트 문자열을 16진수로. 4의 배수가 아니면 뒤를 0 으로 채운다(앞에서부터 읽은 그대로 보이게)."""
    padded = bits + "0" * (-len(bits) % 4)
    return "".join(f"{int(padded[k:k + 4], 2):X}" for k in range(0, len(padded), 4))


def manchester(bits: str) -> str | None:
    """맨체스터 부호(비트 하나를 "01" 이나 "10" 두 칸으로 보내는 방식)면 풀어 준다. 아니면 None.

    두 칸씩 끊는 자리를 0 과 1 에서 다 해 보고, "00"·"11" 이 하나도 없는 쪽을 쓴다. "10" 을 1, "01" 을 0 으로 읽는다
    (반대 약속도 있다: 그 경우 결과의 0 과 1 이 뒤바뀐 것이다).
    """
    for shift in (0, 1):
        pairs = [bits[k:k + 2] for k in range(shift, len(bits) - 1, 2)]
        if len(pairs) >= 8 and all(pair in ("01", "10") for pair in pairs):
            return "".join("1" if pair == "10" else "0" for pair in pairs)
    return None


def slice_bits(level: np.ndarray, symbol: float) -> str:
    """0/1 로 가른 파형(level, 샘플마다 참·거짓)을 심볼 길이(symbol, 샘플 수)로 끊어 비트로.

    같은 값이 이어진 토막마다 "심볼 몇 개 길이인가"를 반올림해 그만큼 적는다. 박자를 따로 맞추지 않아도
    토막의 경계가 박자 노릇을 한다(같은 값이 아주 길게 이어지면 한두 개 틀릴 수 있다).
    """
    edges = np.flatnonzero(np.diff(level.astype(np.int8))) + 1
    bounds = np.concatenate([[0], edges, [len(level)]])
    out: list[str] = []
    for a, b in zip(bounds[:-1], bounds[1:], strict=True):
        n = int(round((b - a) / symbol))
        if n >= 1:
            out.append(("1" if level[a] else "0") * min(n, MAX_BITS))
    return "".join(out)[:MAX_BITS]


def symbol_length(level: np.ndarray) -> float | None:
    """심볼 하나의 길이(샘플 수). 가장 짧은 토막들(아래 10%)을 한 심볼로 보고, 그 배수에 가까운 토막들로 다듬는다."""
    edges = np.flatnonzero(np.diff(level.astype(np.int8))) + 1
    lengths = np.diff(edges)                                             # 처음과 끝 토막은 잘렸을 수 있어 뺀다
    lengths = lengths[lengths >= 3]
    if len(lengths) < 4:
        return None
    unit = float(np.percentile(lengths, 10))
    multiples = np.maximum(np.rint(lengths / unit), 1)
    keep = multiples <= 4                                                # 아주 긴 토막(쉬는 구간)은 다듬는 데 쓰지 않는다
    return float(np.median(lengths[keep] / multiples[keep])) if keep.any() else unit


def demodulate(cap: sigmf.Capture, start_s: float, seconds: float, offset_hz: float, bandwidth_hz: float,
               kind: str = "auto", symbol_s: float | None = None) -> dict[str, Any]:
    """고른 신호를 비트로. kind 는 "ook"(켜고 끄기), "fsk"(주파수 바꾸기), "auto"(모양으로 추정한 것).

    하는 순서
      1. 신호가 켜진 곳들을 찾아 패킷으로 나눈다(꺼진 틈이 길면 다른 패킷이다).
      2. 패킷마다 샘플을 0/1 로 가른다. ook: 크기가 문턱보다 큰가. fsk: 순간 주파수가 두 값의 가운데보다 높은가.
      3. 심볼 길이를 잰다(symbol_s 를 주면 그 값을 쓴다).
      4. 같은 값이 이어진 토막을 심볼 길이로 나눠 비트를 적는다. 맨체스터 부호로 보이면 그것도 풀어 함께 준다.
    """
    picked, rate, first = pick(cap, start_s, seconds, offset_hz, bandwidth_hz)
    guessed = guess_modulation(picked, rate)
    use = guessed["kind"] if kind == "auto" else kind
    if use not in ("ook", "fsk"):
        raise AnalyzeError("이 신호의 변조 방식을 알아보지 못했습니다. '켜고 끄기'나 '주파수 바꾸기'를 직접 골라 보세요."
                           if kind == "auto" else f"모르는 방식입니다: {kind}")
    mag = np.abs(picked)
    top = float(mag.max())
    if top <= 0:
        raise AnalyzeError("이 구간에는 신호가 없습니다.")
    # 순간 주파수가 한 샘플마다 흔들리는 것을 누그러뜨린다(다섯 샘플 평균)
    smooth = np.ones(5, dtype=np.float32) / 5

    if use == "fsk":
        on = mag > 0.3 * top
        turn = np.angle(picked[1:] * np.conj(picked[:-1])) * rate / (2 * np.pi)
        turn = np.convolve(np.concatenate([[turn[0]], turn]), smooth, mode="same")
        inside = turn[on]
        lo, hi = np.percentile(inside, [10, 90])
        level = turn > (lo + hi) / 2
        gap = int(rate * 2e-3)                                           # 2 ms 넘게 꺼지면 다른 패킷
    else:
        on = mag > 0.15 * top                                            # 켜고 끄는 신호는 꺼진 동안도 패킷 안이다: 문턱을 낮춰 패킷의 범위를 잡는다
        level = np.convolve(mag, smooth, mode="same") > 0.5 * float(np.percentile(mag[mag > 0.3 * top], 50))
        gap = 0                                                          # 아래에서 심볼 길이를 잰 뒤 정한다

    unit = symbol_s * rate if symbol_s else symbol_length(level[np.flatnonzero(on)[0]: np.flatnonzero(on)[-1] + 1] if on.any() else level)
    if not unit or unit < 2:
        raise AnalyzeError("심볼 길이를 재지 못했습니다(켜짐과 꺼짐이 너무 적습니다). 구간을 넓히거나 심볼 속도를 직접 적어 보세요.")
    if use == "ook":
        gap = int(unit * 12)                                             # 심볼 12개 넘게 꺼져 있으면 다른 패킷

    begins, lengths = runs(on)
    spans: list[list[int]] = []
    for b, n in zip(begins, lengths, strict=True):
        if spans and b - spans[-1][1] <= gap:
            spans[-1][1] = int(b + n)
        else:
            spans.append([int(b), int(b + n)])
    packets = []
    for a, b in spans:
        if b - a < unit * 4:
            continue                                                     # 심볼 네 개도 안 되는 것은 잡음이다
        bits = slice_bits(level[a:b], unit)
        if use == "ook":
            bits = bits.strip("0") or bits                               # 패킷 앞뒤의 꺼짐은 내용이 아니다
        if len(bits) < 4:
            continue
        item: dict[str, Any] = {"start_s": round((first + a * cap.sample_rate_hz / rate) / cap.sample_rate_hz, 6),
                                "seconds": round((b - a) / rate, 6), "bits": bits, "hex": to_hex(bits)}
        plain = manchester(bits)
        if plain:
            item["manchester"] = {"bits": plain, "hex": to_hex(plain)}
        packets.append(item)
    same: dict[str, int] = {}
    for item in packets:
        same[item["bits"]] = same.get(item["bits"], 0) + 1
    for item in packets:
        item["repeats"] = same[item["bits"]]
    return {"kind": use, "guessed": guessed["kind"], "symbol_s": round(unit / rate, 8), "symbol_rate_hz": round(rate / unit, 1),
            "packets": packets[:MAX_PACKETS], "packets_total": len(packets)}


# ── 4. 구간 잘라 내기 ──────────────────────────────────────────────────────────

def cut(cap: sigmf.Capture, start_s: float, seconds: float) -> dict[str, Any]:
    """구간만 새 SigMF 파일로 남긴다(원본 옆, 숫자 형식은 그대로). 같은 이름이 있으면 번호를 붙인다."""
    size = sigmf.DTYPES[cap.datatype][1]
    first = int(np.clip(round(start_s * cap.sample_rate_hz), 0, cap.num_samples))
    count = int(np.clip(round(seconds * cap.sample_rate_hz), 0, cap.num_samples - first))
    if count <= 0:
        raise AnalyzeError("구간이 파일 밖입니다.")
    name = cap.data_path.name
    stem = name[: -len(".sigmf-data")] if name.endswith(".sigmf-data") else cap.data_path.stem
    base = f"{stem}-cut-{first / cap.sample_rate_hz:.3f}s"
    meta, n = cap.data_path.with_name(base + ".sigmf-meta"), 1
    while meta.exists() or sigmf.data_path_for(meta).exists():
        n += 1
        meta = cap.data_path.with_name(f"{base}-{n}.sigmf-meta")
    data = sigmf.data_path_for(meta)
    try:
        with cap.data_path.open("rb") as src, data.open("wb") as dst:
            src.seek(first * size)
            left = count * size
            while left > 0:
                piece = src.read(min(left, 1 << 22))
                if not piece:
                    break
                dst.write(piece)
                left -= len(piece)
        sigmf.write_meta(meta, datatype=cap.datatype, sample_rate_hz=cap.sample_rate_hz, center_freq_hz=cap.center_freq_hz, source="file",
                         description=f"{cap.data_path.name} 의 {first / cap.sample_rate_hz:.6f}초부터 {count / cap.sample_rate_hz:.6f}초")
    except OSError as e:
        data.unlink(missing_ok=True)
        raise AnalyzeError(f"잘라 내지 못했습니다: {e.strerror or e}") from e
    return {"meta_path": str(meta), "data_path": str(data), "bytes": os.path.getsize(data), "seconds": round(count / cap.sample_rate_hz, 6)}


# ── 주소 ──────────────────────────────────────────────────────────────────────

class FileBody(BaseModel):
    path: str
    sample_rate_hz: float | None = None      # 날것 파일일 때만
    center_hz: float | None = None


class DetailBody(FileBody):
    start_s: float
    seconds: float
    offset_hz: float = 0.0
    bandwidth_hz: float = 0.0


class DemodBody(DetailBody):
    kind: str = "auto"
    symbol_rate_hz: float | None = None


class CutBody(FileBody):
    start_s: float
    seconds: float


def register(app: FastAPI) -> None:
    """큰 파일은 몇 초 걸리므로 def 로 둔다(FastAPI 가 다른 스레드에서 돌린다)."""

    def cap_of(body: FileBody) -> sigmf.Capture:
        try:
            return source(body.path, body.sample_rate_hz, body.center_hz)
        except AnalyzeError as e:
            raise HTTPException(400, str(e)) from e

    @app.get("/api/analyze/files")
    def analyze_files() -> dict[str, Any]:
        return {"folder": str(folder()), "files": recent(), "can_choose": sys.platform == "darwin"}

    @app.post("/api/analyze/choose")
    def analyze_choose() -> dict[str, Any]:
        try:
            return {"path": choose_file()}
        except AnalyzeError as e:
            raise HTTPException(400, str(e)) from e

    @app.post("/api/analyze/open")
    def analyze_open(body: FileBody) -> dict[str, Any]:
        try:
            return open_file(cap_of(body))
        except AnalyzeError as e:
            raise HTTPException(400, str(e)) from e

    @app.post("/api/analyze/detail")
    def analyze_detail(body: DetailBody) -> dict[str, Any]:
        try:
            return detail(cap_of(body), body.start_s, body.seconds, body.offset_hz, body.bandwidth_hz)
        except AnalyzeError as e:
            raise HTTPException(400, str(e)) from e

    @app.post("/api/analyze/demod")
    def analyze_demod(body: DemodBody) -> dict[str, Any]:
        try:
            return demodulate(cap_of(body), body.start_s, body.seconds, body.offset_hz, body.bandwidth_hz, body.kind,
                              1.0 / body.symbol_rate_hz if body.symbol_rate_hz and body.symbol_rate_hz > 0 else None)
        except AnalyzeError as e:
            raise HTTPException(400, str(e)) from e

    @app.post("/api/analyze/cut")
    def analyze_cut(body: CutBody) -> dict[str, Any]:
        try:
            return cut(cap_of(body), body.start_s, body.seconds)
        except AnalyzeError as e:
            raise HTTPException(400, str(e)) from e
