# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 서민재
"""Summary of latency samples."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

SampleRow = tuple[int, str, str, float]  # t_ns, probe, metric, value


@dataclass(frozen=True, slots=True)
class LatencySummary:
    sent: int
    lost: int
    min_ms: float | None
    avg_ms: float | None
    max_ms: float | None
    jitter_ms: float | None  # mean absolute difference between consecutive replies

    @property
    def loss_percent(self) -> float:
        return 100.0 * self.lost / self.sent if self.sent else 0.0


@dataclass(frozen=True, slots=True)
class MetricSummary:
    count: int
    min: float | None
    avg: float | None
    max: float | None


def summarize_metric(rows: Iterable[SampleRow], probe: str, metric: str) -> MetricSummary:
    values = [v for _, name, m, v in rows if name == probe and m == metric]
    if not values:
        return MetricSummary(0, None, None, None)
    return MetricSummary(len(values), min(values), sum(values) / len(values), max(values))


def summarize_latency(rows: Iterable[SampleRow], probe: str = "ping") -> LatencySummary:
    rtts: list[float] = []
    sent = lost = 0
    for _, name, metric, value in rows:
        if name != probe:
            continue
        if metric == "lost":
            sent += 1
            lost += int(value)
        elif metric == "rtt_ms":
            rtts.append(value)
    if not rtts:
        return LatencySummary(sent, lost, None, None, None, None)
    diffs = [abs(b - a) for a, b in zip(rtts, rtts[1:])]
    jitter = sum(diffs) / len(diffs) if diffs else None
    return LatencySummary(sent, lost, min(rtts), sum(rtts) / len(rtts), max(rtts), jitter)
