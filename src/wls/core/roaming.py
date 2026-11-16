# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 서민재
"""Turn a stream of Wi-Fi link observations into connection events.

A roam is a change of BSSID while the network name stays the same. Seeing the
BSSID change shows that the device moved to another access point; it does not
show which 802.11 procedure was used or how long the hand-over took (the
observations are seconds apart).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class LinkObservation:
    t: float  # seconds since the epoch
    connected: bool
    ssid: str | None = None
    bssid: str | None = None
    channel: int | None = None
    rssi_dbm: float | None = None


@dataclass(frozen=True, slots=True)
class LinkEvent:
    t: float
    kind: str  # "connected", "disconnected", "roamed", "network_changed"
    ssid: str | None = None
    bssid: str | None = None  # the access point after the event
    channel: int | None = None
    rssi_dbm: float | None = None
    from_ssid: str | None = None
    from_bssid: str | None = None
    from_channel: int | None = None
    from_rssi_dbm: float | None = None


class LinkTracker:
    """Feed observations in time order; get the events they imply."""

    def __init__(self, disconnect_after: int = 2) -> None:
        # A single "not connected" reading can be a glitch; wait for this many in a row.
        self._disconnect_after = disconnect_after
        self._last: LinkObservation | None = None  # last connected observation
        self._connected: bool | None = None  # None until the first observation
        self._misses = 0

    def observe(self, obs: LinkObservation) -> list[LinkEvent]:
        if self._connected is None:  # the starting point is not an event
            self._connected = obs.connected
            self._last = obs if obs.connected else None
            return []

        if not obs.connected:
            if not self._connected:
                return []
            self._misses += 1
            if self._misses < self._disconnect_after:
                return []
            self._connected = False
            last, self._last = self._last, None
            return [
                LinkEvent(
                    obs.t, "disconnected",
                    from_ssid=last.ssid if last else None,
                    from_bssid=last.bssid if last else None,
                    from_channel=last.channel if last else None,
                    from_rssi_dbm=last.rssi_dbm if last else None,
                )
            ]  # fmt: skip

        self._misses = 0
        last = self._last
        if not self._connected or last is None:
            self._connected, self._last = True, obs
            return [LinkEvent(obs.t, "connected", obs.ssid, obs.bssid, obs.channel, obs.rssi_dbm)]

        # Keep what is known when the OS did not give the identity this time.
        current = LinkObservation(
            obs.t, True, obs.ssid or last.ssid, obs.bssid or last.bssid, obs.channel, obs.rssi_dbm
        )
        self._last = current
        if obs.bssid is None or last.bssid is None or obs.bssid == last.bssid:
            return []
        same_network = obs.ssid is None or last.ssid is None or obs.ssid == last.ssid
        return [
            LinkEvent(
                obs.t,
                "roamed" if same_network else "network_changed",
                current.ssid, current.bssid, current.channel, current.rssi_dbm,
                last.ssid, last.bssid, last.channel, last.rssi_dbm,
            )
        ]  # fmt: skip
