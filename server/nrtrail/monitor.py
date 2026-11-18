"""채널 모니터: 고른 채널을 계속 훑으며 세기 변화를 지켜본다. **수신 전용**이다.

한 바퀴 잴 때마다(`sweep`) 아래를 한다.
- 표시값 = 최근 SMOOTH 바퀴의 중앙값. 주변 트래픽으로 한두 바퀴 튀는 것을 걸러 낸다(그래서 변화가 몇 초 늦게 보인다).
- 자동 기준값: 기준값이 없는 채널은 SETTLE_S 초를 기다린 뒤, 최근 바퀴들이 STABLE_DB 폭 안에 들면 그때의 표시값을 기준으로 저장한다.
  계속 흔들리면 TIMEOUT_S 초에 그대로 저장하고 그 채널을 "흔들리는 중에 저장"으로 표시한다. 채널마다 따로 판단한다.
- 증가량 = 표시값 − 기준값. RISE_DB 이상 오르면 "올랐음"으로 표시한다.
측정과 판단 방식은 사용자의 MATLAB 도구(SSOM_USRP_DEBUG 의 PowerMonitorApp)를 옮긴 것이다. 실제 장비로는 검증하지 못했다.
"""

from __future__ import annotations

import statistics
import time
import uuid
from collections import deque
from collections.abc import Callable
from typing import Any

from . import survey

SMOOTH = 5
SETTLE_S = 8.0
STABLE_DB = 2.0
TIMEOUT_S = 15.0
RISE_DB = 6.0          # 이만큼 오르면 "올랐음". 사용자의 도구에는 없던 표시로, 내가 정한 값이다
STATS = ("mean_dbfs", "median_dbfs")
MAX_MONITORS = 4

Sweep = Callable[..., dict[str, Any]]


class Monitor:
    def __init__(self, device: str, plan: str, channels: list[str] | None = None, *, gain_db: float | None = None,
                 center_hz: float | None = None, span_hz: float | None = None, step_hz: float | None = None, auto: bool = True,
                 stat: str = "median_dbfs", clock: Callable[[], float] = time.monotonic, sweep: Sweep = survey.run):
        if stat not in STATS:
            raise survey.SurveyError("모르는 값 종류입니다.")
        self.id = uuid.uuid4().hex[:10]
        self.device, self.plan, self.channels, self.gain_db = device, plan, channels, gain_db
        self.custom = {"center_hz": center_hz, "span_hz": span_hz, "step_hz": step_hz}
        self.auto, self.stat = auto, stat
        self._clock, self._sweep = clock, sweep
        self.recent: dict[str, deque[dict[str, float]]] = {}
        self.baseline: dict[str, dict[str, float]] = {}
        self.forced: set[str] = set()
        self.baseline_note = ""            # "", "manual", "auto"
        self.settle_start: dict[str, float] = {}
        self.sweeps = 0
        self.sweep_s: float | None = None
        self.last: list[dict[str, Any]] = []

    # ---- 한 바퀴
    def sweep(self) -> dict[str, Any]:
        started = self._clock()
        out = self._sweep(self.device, self.plan, gain_db=self.gain_db, only=self.channels, **self.custom)
        self.update(out["channels"], self._clock())
        self.sweep_s = round(self._clock() - started, 3)
        return self.state()

    def update(self, rows: list[dict[str, Any]], now: float) -> None:
        self.last = rows
        self.sweeps += 1
        for r in rows:
            if not r.get("measured"):
                continue
            self.recent.setdefault(r["name"], deque(maxlen=SMOOTH)).append({s: float(r[s]) for s in STATS})
            self.settle_start.setdefault(r["name"], now)
        self._auto_baseline(now)

    def level(self, name: str) -> dict[str, float] | None:
        hist = self.recent.get(name)
        return {s: round(statistics.median(h[s] for h in hist), 2) for s in STATS} if hist else None

    def _auto_baseline(self, now: float) -> None:
        if not self.auto:
            return
        for name, hist in self.recent.items():
            if name in self.baseline:
                continue
            waited = now - self.settle_start[name]
            values = [h[self.stat] for h in hist]
            shaky = max(values) - min(values) > STABLE_DB
            if len(hist) == SMOOTH and waited >= SETTLE_S and (not shaky or waited >= TIMEOUT_S):
                level = self.level(name)
                assert level is not None
                self.baseline[name] = level
                self.baseline_note = "auto"
                if shaky:
                    self.forced.add(name)

    # ---- 기준값
    def save_baseline(self) -> None:
        self.baseline = {name: lv for name in self.recent if (lv := self.level(name)) is not None}
        self.forced.clear()
        self.baseline_note = "manual" if self.baseline else ""

    def clear_baseline(self, now: float | None = None) -> None:
        self.baseline.clear()
        self.forced.clear()
        self.baseline_note = ""
        t = self._clock() if now is None else now
        self.settle_start = {name: t for name in self.recent}   # 자동이 켜져 있으면 가라앉은 뒤 다시 잡는다

    def configure(self, *, auto: bool | None = None, stat: str | None = None) -> None:
        if auto is not None:
            self.auto = auto
        if stat is not None:
            if stat not in STATS:
                raise survey.SurveyError("모르는 값 종류입니다.")
            self.stat = stat

    # ---- 화면에 줄 모양
    def state(self) -> dict[str, Any]:
        now = self._clock()
        rows = []
        for r in self.last:
            name = r["name"]
            row: dict[str, Any] = {"name": name, "center_hz": r["center_hz"], "width_hz": r["width_hz"], "measured": bool(r.get("measured"))}
            level, base = self.level(name), self.baseline.get(name)
            if level and row["measured"]:
                row |= level | {"peak_dbfs": r.get("peak_dbfs"), "clipped": bool(r.get("clipped")), "samples": len(self.recent[name])}
                if base:
                    rise = round(level[self.stat] - base[self.stat], 2)
                    row |= {"baseline_dbfs": base[self.stat], "rise_db": rise, "raised": rise >= RISE_DB, "forced": name in self.forced}
                elif self.auto:
                    row["settle_s"] = round(max(0.0, SETTLE_S - (now - self.settle_start[name])), 1)
            rows.append(row)
        return {"id": self.id, "device": self.device, "plan": self.plan, "unit": "dBFS", "stat": self.stat, "auto": self.auto,
                "sweeps": self.sweeps, "sweep_s": self.sweep_s, "channels": rows, "baseline_note": self.baseline_note,
                "has_baseline": bool(self.baseline), "forced": sorted(self.forced), "smooth": SMOOTH, "rise_threshold_db": RISE_DB,
                "raised": [r["name"] for r in rows if r.get("raised")]}


class Registry:
    """서버가 들고 있는 모니터들. 창을 닫지 않고 설정으로 돌아가면 화면이 지운다. 오래된 것은 밀려난다."""

    def __init__(self) -> None:
        self._items: dict[str, Monitor] = {}

    def add(self, m: Monitor) -> Monitor:
        while len(self._items) >= MAX_MONITORS:
            self._items.pop(next(iter(self._items)))
        self._items[m.id] = m
        return m

    def get(self, mid: str) -> Monitor:
        try:
            return self._items[mid]
        except KeyError:
            raise survey.SurveyError("모니터를 찾을 수 없습니다. 다시 시작하세요.") from None

    def remove(self, mid: str) -> None:
        self._items.pop(mid, None)
