# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 서민재
"""Wi-Fi interfaces on macOS through CoreWLAN.

Signal, noise, channel and rate are available to any process. macOS returns
the SSID and BSSID only to a signed application that was granted Location
permission, so a command line process gets none; that is reported as an
unsupported capability with the reason, not as an error.
"""

from __future__ import annotations

import CoreWLAN  # available on macOS only; importers must guard this module

from wls.core.devices import SUPPORTED, Capability, Device, DeviceKind, unsupported
from wls.providers import macos_helper
from wls.probes.wifi_link import LinkReading, Reader, ScanEntry, Scanner, WifiBackend

_BAND_GHZ = {1: 2.4, 2: 5.0, 3: 6.0}
_WIDTH_MHZ = {1: 20, 2: 40, 3: 80, 4: 160}
_PHY = {1: "802.11a", 2: "802.11b", 3: "802.11g", 4: "802.11n", 5: "802.11ac", 6: "802.11ax"}

ID_PREFIX = "wifi:"


def to_reading(
    rssi: int, noise: int, tx_rate: float, channel: int | None, band: int | None, width: int | None
) -> LinkReading | None:
    """Convert raw CoreWLAN numbers. RSSI 0 means the interface is not connected."""
    if rssi == 0:
        return None
    return LinkReading(
        rssi_dbm=float(rssi),
        noise_dbm=float(noise) if noise != 0 else None,
        tx_rate_mbps=float(tx_rate) if tx_rate > 0 else None,
        channel=channel,
        band_ghz=_BAND_GHZ.get(band) if band is not None else None,
        width_mhz=_WIDTH_MHZ.get(width) if width is not None else None,
    )


def _interface(name: str):
    interface = CoreWLAN.CWWiFiClient.sharedWiFiClient().interfaceWithName_(name)
    if interface is None:
        raise RuntimeError(f"Wi-Fi interface {name} is no longer present")
    return interface


def link_reader(interface_name: str) -> Reader:
    def read() -> LinkReading | None:
        interface = _interface(interface_name)
        if not interface.powerOn():
            return None
        channel = interface.wlanChannel()
        return to_reading(
            interface.rssiValue(),
            interface.noiseMeasurement(),
            interface.transmitRate(),
            channel.channelNumber() if channel else None,
            channel.channelBand() if channel else None,
            channel.channelWidth() if channel else None,
        )

    return read


# CWSecurity values, strongest meaning first.
_SECURITY = (
    ((12, 10, 9, 8, 7), "enterprise"),
    ((13,), "WPA2/WPA3"),
    ((11,), "WPA3"),
    ((4, 5, 3), "WPA2"),
    ((2,), "WPA"),
    ((1, 6), "WEP"),
    ((0,), "open"),
)


def security_label(supported: set[int]) -> str:
    for codes, label in _SECURITY:
        if supported.intersection(codes):
            return label
    return ""


def entries_from_helper(answer: dict) -> list[ScanEntry]:
    """Convert the helper's scan answer."""
    entries = [
        ScanEntry(
            rssi_dbm=float(n["rssi"]),
            ssid=n.get("ssid"),
            bssid=n.get("bssid"),
            channel=n.get("channel"),
            band_ghz=_BAND_GHZ.get(n.get("band")),
            width_mhz=_WIDTH_MHZ.get(n.get("width")),
            security=security_label(set(n.get("security", []))),
        )
        for n in answer.get("networks", [])
    ]
    return sorted(entries, key=lambda e: e.rssi_dbm, reverse=True)


def identity(interface_name: str, fresh: bool = False) -> tuple[str | None, str | None]:
    """SSID and BSSID of the connected network, when the helper may read them."""
    if not macos_helper.installed():
        return None, None
    try:
        ask = macos_helper.run if fresh else macos_helper.cached
        answer = ask("link", interface_name)
    except macos_helper.HelperError:
        return None, None
    return answer.get("ssid"), answer.get("bssid")


def _identity_support(interface_name: str, connected: bool):
    if not connected:
        return unsupported("not connected to a network")
    if not macos_helper.installed():
        return unsupported(
            "macOS gives network names only to an app allowed to use Location Services; "
            "run 'wls macos-setup' once"
        )
    try:
        answer = macos_helper.cached("link", interface_name)
    except macos_helper.HelperError as exc:
        return unsupported(f"the helper failed: {exc}")
    if answer.get("ssid") is not None:
        return SUPPORTED
    status = str(answer.get("location", "unknown"))
    return unsupported(macos_helper.STATUS_HELP.get(status) or f"location status: {status}")


def scanner(interface_name: str) -> Scanner:
    def scan() -> list[ScanEntry]:
        """Blocks for several seconds; call from a worker thread."""
        if macos_helper.installed():
            try:
                return entries_from_helper(macos_helper.run("scan", interface_name, timeout=30))
            except macos_helper.HelperError:
                pass  # fall back to scanning without names
        networks, error = _interface(interface_name).scanForNetworksWithName_error_(None, None)
        if networks is None:
            raise RuntimeError(f"Wi-Fi scan failed: {error}")
        entries = []
        for network in networks:
            channel = network.wlanChannel()
            supported = {code for code in range(14) if network.supportsSecurity_(code)}
            ssid, bssid = network.ssid(), network.bssid()
            entries.append(
                ScanEntry(
                    rssi_dbm=float(network.rssiValue()),
                    ssid=str(ssid) if ssid is not None else None,
                    bssid=str(bssid) if bssid is not None else None,
                    channel=channel.channelNumber() if channel else None,
                    band_ghz=_BAND_GHZ.get(channel.channelBand()) if channel else None,
                    width_mhz=_WIDTH_MHZ.get(channel.channelWidth()) if channel else None,
                    security=security_label(supported),
                )
            )
        return sorted(entries, key=lambda e: e.rssi_dbm, reverse=True)

    return scan


class MacWifiProvider:
    name = "wifi-macos"

    async def discover(self) -> list[Device]:
        devices = []
        for interface in CoreWLAN.CWWiFiClient.sharedWiFiClient().interfaces() or []:
            name = str(interface.interfaceName())
            connected = bool(interface.powerOn()) and interface.rssiValue() != 0
            if interface.ssid() is not None:
                identity_support = SUPPORTED
            else:
                identity_support = _identity_support(name, connected)
            phy = _PHY.get(interface.activePHYMode(), "")
            details = {"interface": name, "power": "on" if interface.powerOn() else "off"}
            if phy:
                details["phy"] = phy
            devices.append(
                Device(
                    ID_PREFIX + name,
                    DeviceKind.WIFI_NIC,
                    f"Wi-Fi {name}" + (f" ({phy})" if phy else ""),
                    {
                        Capability.WIFI_LINK_INFO: SUPPORTED,
                        Capability.WIFI_IDENTITY: identity_support,
                        Capability.WIFI_SCAN: SUPPORTED,
                        Capability.WIFI_MONITOR: unsupported("not implemented yet"),
                        Capability.WIFI_INJECT: unsupported(
                            "macOS drivers do not allow frame injection"
                        ),
                    },
                    details,
                )
            )
        return devices


def backend() -> WifiBackend:
    return WifiBackend(
        MacWifiProvider(), link_reader, scanner, ID_PREFIX, identity, macos_helper.setup
    )
