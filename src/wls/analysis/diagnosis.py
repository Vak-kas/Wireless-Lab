# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 서민재
"""Where is the problem: Wi-Fi, the local network, or beyond the router?

The verdict compares latency to the router with latency to an internet
address, together with Wi-Fi signal. The thresholds are rules of thumb for a
home or office connection, not a standard, and the verdict describes only the
measured period.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from enum import Enum

from wls.analysis.summary import (
    LatencySummary,
    MetricSummary,
    SampleRow,
    summarize_latency,
    summarize_metric,
)

# Rules of thumb.
WEAK_RSSI_DBM = -70.0
FAIR_RSSI_DBM = -60.0
LOW_SNR_DB = 20.0
MAX_LOSS_PERCENT = 2.0
LOCAL_MAX_AVG_MS = 20.0
LOCAL_MAX_JITTER_MS = 30.0  # routers answer ping with low priority, so their delay varies
INTERNET_MAX_AVG_MS = 100.0
INTERNET_MAX_JITTER_MS = 30.0


class Verdict(Enum):
    OK = "ok"
    WIFI_NOT_CONNECTED = "wifi_not_connected"
    NO_CONNECTIVITY = "no_connectivity"
    LOCAL_PROBLEM = "local_problem"  # between this computer and the router
    INTERNET_PROBLEM = "internet_problem"  # beyond the router
    INCONCLUSIVE = "inconclusive"


@dataclass(frozen=True, slots=True)
class Diagnosis:
    verdict: Verdict
    headline: str
    details: tuple[str, ...] = field(default=())
    wifi_suspect: bool = False  # weak, noisy or dropping Wi-Fi was observed


def _problems(s: LatencySummary, max_avg: float, max_jitter: float) -> list[str]:
    found = []
    if s.loss_percent > MAX_LOSS_PERCENT:
        found.append(f"{s.loss_percent:.0f}% of packets lost")
    if s.avg_ms is not None and s.avg_ms > max_avg:
        found.append(f"average delay {s.avg_ms:.0f} ms")
    if s.jitter_ms is not None and s.jitter_ms > max_jitter:
        found.append(f"delay varies by {s.jitter_ms:.0f} ms")
    return found


def _wifi_notes(
    connected: MetricSummary | None, rssi: MetricSummary | None, snr: MetricSummary | None
) -> tuple[list[str], bool]:
    """Notes about Wi-Fi and whether the signal is a likely cause of trouble."""
    notes: list[str] = []
    suspect = False
    if connected is None or not connected.count:
        return notes, suspect
    if connected.avg is not None and 0 < connected.avg < 1:
        notes.append(f"Wi-Fi was connected only {100 * connected.avg:.0f}% of the time")
        suspect = True
    if rssi is not None and rssi.avg is not None:
        if rssi.avg < WEAK_RSSI_DBM:
            notes.append(f"Wi-Fi signal is weak ({rssi.avg:.0f} dBm)")
            suspect = True
        elif rssi.avg < FAIR_RSSI_DBM:
            notes.append(f"Wi-Fi signal is fair ({rssi.avg:.0f} dBm)")
        else:
            notes.append(f"Wi-Fi signal is strong ({rssi.avg:.0f} dBm)")
    if snr is not None and snr.avg is not None and snr.avg < LOW_SNR_DB:
        notes.append(f"Wi-Fi is noisy (signal only {snr.avg:.0f} dB above noise)")
        suspect = True
    return notes, suspect


def diagnose(
    internet: LatencySummary,
    gateway: LatencySummary | None = None,
    wifi_connected: MetricSummary | None = None,
    wifi_rssi: MetricSummary | None = None,
    wifi_snr: MetricSummary | None = None,
) -> Diagnosis:
    result = _diagnose(internet, gateway, wifi_connected, wifi_rssi, wifi_snr)
    _, suspect = _wifi_notes(wifi_connected, wifi_rssi, wifi_snr)
    return replace(result, wifi_suspect=suspect)


def _diagnose(
    internet: LatencySummary,
    gateway: LatencySummary | None = None,
    wifi_connected: MetricSummary | None = None,
    wifi_rssi: MetricSummary | None = None,
    wifi_snr: MetricSummary | None = None,
) -> Diagnosis:
    wifi_notes, wifi_suspect = _wifi_notes(wifi_connected, wifi_rssi, wifi_snr)
    wifi_measured = wifi_connected is not None and wifi_connected.count > 0
    wifi_down = wifi_measured and wifi_connected.avg == 0

    internet_dead = internet.sent > 0 and internet.lost == internet.sent
    gateway_measured = gateway is not None and gateway.sent > 0
    gateway_dead = gateway_measured and gateway.lost == gateway.sent

    if internet.sent == 0:
        return Diagnosis(Verdict.INCONCLUSIVE, "Nothing was measured.", tuple(wifi_notes))

    if internet_dead and (gateway_dead or not gateway_measured):
        if wifi_down:
            return Diagnosis(Verdict.WIFI_NOT_CONNECTED, "Wi-Fi is not connected to any network.")
        headline = (
            "No connection: neither the router nor the internet answered."
            if gateway_measured
            else "No connection: the internet address did not answer."
        )
        return Diagnosis(Verdict.NO_CONNECTIVITY, headline, tuple(wifi_notes))

    internet_issues = _problems(internet, INTERNET_MAX_AVG_MS, INTERNET_MAX_JITTER_MS)

    if not gateway_measured or gateway_dead:
        # Cannot separate local from remote (many routers ignore ping).
        why = (
            "The router does not answer ping, so the local part cannot be measured separately."
            if gateway_dead
            else "The router address is unknown, so the local part was not measured separately."
        )
        if not internet_issues:
            return Diagnosis(Verdict.OK, "No problem found.", (*wifi_notes, why))
        if wifi_suspect:
            return Diagnosis(
                Verdict.LOCAL_PROBLEM,
                "The connection is poor, and Wi-Fi is a likely cause.",
                (*(f"Internet: {i}" for i in internet_issues), *wifi_notes, why),
            )
        return Diagnosis(
            Verdict.INCONCLUSIVE,
            "The connection is poor, but the cause could not be located.",
            (*(f"Internet: {i}" for i in internet_issues), *wifi_notes, why),
        )

    local_issues = _problems(gateway, LOCAL_MAX_AVG_MS, LOCAL_MAX_JITTER_MS)

    if local_issues:
        headline = "The problem is between this computer and your router"
        headline += ": Wi-Fi is a likely cause." if wifi_suspect else "."
        return Diagnosis(
            Verdict.LOCAL_PROBLEM,
            headline,
            (*(f"To the router: {i}" for i in local_issues), *wifi_notes),
        )
    if internet_issues:
        return Diagnosis(
            Verdict.INTERNET_PROBLEM,
            "Your local network is fine. The problem is beyond your router "
            "(internet provider or the tested address).",
            (*(f"Internet: {i}" for i in internet_issues), *wifi_notes),
        )
    return Diagnosis(Verdict.OK, "No problem found.", tuple(wifi_notes))


def diagnose_samples(rows: Sequence[SampleRow]) -> Diagnosis:
    """Diagnose a recorded ``diagnose`` run (probes: internet, router, wifi)."""
    router = summarize_latency(rows, "router")
    return diagnose(
        summarize_latency(rows, "internet"),
        router if router.sent else None,
        summarize_metric(rows, "wifi", "associated"),
        summarize_metric(rows, "wifi", "rssi_dbm"),
        summarize_metric(rows, "wifi", "snr_db"),
    )
