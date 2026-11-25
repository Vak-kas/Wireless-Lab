"""받은 신호에서 "신호가 시작하는 자리"를 빠르게 찾는다. 풀지는 않는다.

왜 따로 있나: 받은 신호를 처음부터 끝까지 훑는 일은 샘플 수만큼 걸린다(20 MS/s 면 0.5 초에 천만 개).
그 일은 C++ 프로그램(native/sigfind)이 하고, 푸는 쪽(MATLAB)에는 찾은 자리만 넘긴다.
B200mini 로 받은 Wi-Fi 0.5 초 조각에서: 전체를 MATLAB 으로 훑으면 약 3.9 초, 자리를 찾아 넘기면 훑는 데 0.1 초.

- sigfind 가 지어져 있지 않으면 같은 계산을 numpy 로 한다(느리지만 결과는 같다). 그래서 이 모듈은 언제나 답을 준다.
- 여기서는 "놓치지 않기"가 먼저다. 조금 헐겁게 찾고, 틀린 자리는 푸는 쪽이 걸러 낸다.

짓는 법:  cmake -S native/sigfind -B native/sigfind/build && cmake --build native/sigfind/build
"""

from __future__ import annotations

import json
import os
import subprocess

import numpy as np

from . import sigmf
from .paths import ROOT

BINARY = ROOT / "native" / "sigfind" / "build" / ("sigfind.exe" if os.name == "nt" else "sigfind")
LAG = 16                   # L-STF 무늬 하나의 길이(20 MS/s 에서 0.8 us)
WIN = 144                  # 닮은 정도를 재는 구간(무늬 9 번)
RUN = 32                   # 이만큼 잇달아 문턱값을 넘어야 시작으로 본다
BLOCK = 1 << 16
THRESHOLD = 0.2            # 푸는 쪽(0.5)보다 한참 낮게: 헐겁게 찾는다(0.4 에서는 실제 신호의 약한 프레임 하나를 놓쳤다)


def native() -> bool:
    return BINARY.exists()


def wifi_starts(cap: sigmf.Capture, threshold: float = THRESHOLD) -> list[int]:
    """Wi-Fi(OFDM) 프레임의 맨 앞 L-STF 가 시작하는 샘플 번호들(0 부터). 20 MS/s 로 받은 20 MHz 채널이어야 한다."""
    if native():
        try:
            p = subprocess.run([str(BINARY), "wifi-lstf", str(cap.data_path), cap.datatype, f"{threshold:g}"],
                               capture_output=True, text=True, timeout=60)
            out = json.loads(p.stdout or "{}")
            if out.get("ok"):
                return [int(s) for s in out["starts"]]
        except (OSError, ValueError, subprocess.TimeoutExpired):
            pass                        # 프로그램이 말을 안 들으면 아래의 numpy 계산으로 간다
    return wifi_starts_numpy(np.asarray(cap.read(0, cap.num_samples)), threshold)


def wifi_starts_numpy(iq: np.ndarray, threshold: float = THRESHOLD) -> list[int]:
    """sigfind 의 wifi-lstf 와 같은 계산(설명은 native/sigfind/sigfind.cpp 맨 위).

        C(n) = Σ_{k<WIN} r[n+k]·conj(r[n+k+LAG]),  P(n) = Σ_{k<WIN} |r[n+k+LAG]|²,  M(n) = |C(n)|² / P(n)²
    """
    x = np.asarray(iq, dtype=np.complex64).copy()
    if len(x) < WIN + LAG + RUN:
        return []
    for a in range(0, len(x), BLOCK):                    # 구간마다 평균(DC)을 뺀다
        x[a:a + BLOCK] -= x[a:a + BLOCK].mean()
    prod = np.concatenate([[0], np.cumsum((x[:-LAG] * np.conj(x[LAG:])).astype(np.complex128))])
    power = np.concatenate([[0], np.cumsum(np.abs(x[LAG:]).astype(np.float64) ** 2)])
    c = prod[WIN:] - prod[:-WIN]
    p = power[WIN:] - power[:-WIN]
    over = (p > 1e-9) & (np.abs(c) ** 2 > threshold * p * p)
    # 잇달아 넘은 구간의 길이가 RUN 이상인 것의 첫 자리
    edges = np.diff(np.concatenate([[0], over.astype(np.int8), [0]]))
    begins, ends = np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)
    return [int(b) for b, e in zip(begins, ends, strict=True) if e - b >= RUN]
