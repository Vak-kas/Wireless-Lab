# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 서민재
"""Command line interface. A thin client of the controller.

    wls devices
    wls ping HOST [--duration S] [--interval S] [--out DIR]
    wls wifi [--iface NAME] [--duration S] [--interval S] [--out DIR]
    wls verify RUN.sqlite
    wls export RUN.sqlite --format csv|json [-o FILE]
"""

from __future__ import annotations

import argparse
import asyncio
import signal
import sys
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path

from wls import __version__
from wls.analysis.summary import SampleRow, summarize_latency, summarize_metric
from wls.core.controller import Controller, ExperimentConfig
from wls.core.devices import Capability, Device, DeviceManager, DeviceProvider
from wls.core.export import export_csv, export_json
from wls.core.interfaces import Event, Probe, Sample
from wls.core.state_machine import Command, State
from wls.core.storage import SqliteRecorder, read_run, verify_run
from wls.probes.ping import PingProbe, ping_command
from wls.probes.wifi_link import Reader, WifiLinkProbe
from wls.providers.host import LocalHostProvider

EXIT_OK, EXIT_FAILED, EXIT_USAGE = 0, 1, 2

Show = Callable[[Mapping[str, float]], str]


def _wifi_backend() -> tuple[DeviceProvider, Callable[[str], Reader], str] | None:
    """Wi-Fi provider, reader factory and device id prefix for this OS, if any."""
    if sys.platform == "darwin":
        try:
            from wls.providers import wifi_macos
        except ImportError:
            return None
        return wifi_macos.MacWifiProvider(), wifi_macos.link_reader, wifi_macos.ID_PREFIX
    return None


def _providers() -> list[DeviceProvider]:
    providers: list[DeviceProvider] = [LocalHostProvider()]
    backend = _wifi_backend()
    if backend is not None:
        providers.append(backend[0])
    return providers


class _LiveRecorder:
    """Stores to disk and prints each sample as it arrives."""

    def __init__(self, store: SqliteRecorder, show: Show | None) -> None:
        self._store = store
        self._show = show

    def sample(self, sample: Sample) -> None:
        self._store.sample(sample)
        if self._show is not None:
            print("  " + self._show(sample.values), flush=True)

    def event(self, event: Event) -> None:
        self._store.event(event)


def _on_interrupt(loop: asyncio.AbstractEventLoop, stop: asyncio.Event) -> None:
    try:
        loop.add_signal_handler(signal.SIGINT, stop.set)
    except NotImplementedError:  # Windows
        signal.signal(signal.SIGINT, lambda *_: loop.call_soon_threadsafe(stop.set))


async def _measure(
    args: argparse.Namespace,
    probe: Probe,
    kind: str,
    title: str,
    show: Show,
    stall_timeout: float,
) -> tuple[State, list[SampleRow], Path]:
    """Run one probe until the duration ends, Ctrl+C, or a failure. Saves the run."""
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = Path(args.out) / f"{stamp}-{kind}.sqlite"
    store = SqliteRecorder(path)
    recorder = _LiveRecorder(store, None if args.quiet else show)
    controller = Controller(DeviceManager(_providers()), recorder)
    config = ExperimentConfig((probe,), stall_timeout=stall_timeout)

    stop = asyncio.Event()
    _on_interrupt(asyncio.get_running_loop(), stop)
    terminal = (State.COMPLETED, State.FAILED)
    try:
        controller.submit(Command.PREPARE, config=config)
        state = (await controller.wait_state(State.READY, *terminal, timeout=30)).state
        if state is State.READY:
            print(f"measuring {title} (Ctrl+C to stop)", flush=True)
            controller.submit(Command.START_MEASUREMENT)
            state = (await controller.wait_state(State.MEASURING, *terminal, timeout=30)).state
        if state is State.MEASURING:
            waiters = [
                asyncio.ensure_future(stop.wait()),
                asyncio.ensure_future(controller.wait_state(*terminal, timeout=None)),
            ]
            await asyncio.wait(
                waiters, timeout=args.duration, return_when=asyncio.FIRST_COMPLETED
            )
            for waiter in waiters:
                waiter.cancel()
            controller.submit(Command.STOP)
        state = (await controller.wait_state(*terminal, timeout=60)).state
    finally:
        store.close()

    events, samples = read_run(path)
    if state is State.FAILED:
        for event in events:
            if event.kind in ("probe_error", "probe_stalled", "internal_error", "stop_timeout"):
                print(f"error: {event.kind}: {event.data.get('error', '')}", file=sys.stderr)
            for problem in event.data.get("problems", []):
                print(f"error: {problem}", file=sys.stderr)
    return state, samples, path


def _finish(state: State, path: Path) -> int:
    print(f"saved {path}")
    return EXIT_OK if state is State.COMPLETED else EXIT_FAILED


# --- commands ---------------------------------------------------------------------


async def _devices() -> int:
    manager = DeviceManager(_providers())
    for device in await manager.refresh():
        print(f"{device.id}: {device.name}")
        for capability, support in device.capabilities.items():
            status = "yes" if support.supported else f"no ({support.reason})"
            print(f"  {capability.value:<18} {status}")
    for provider, error in manager.provider_errors.items():
        print(f"warning: provider {provider} failed: {error}", file=sys.stderr)
    return EXIT_OK


def _show_ping(values: Mapping[str, float]) -> str:
    rtt = values.get("rtt_ms")
    return "lost" if rtt is None else f"{rtt:8.2f} ms"


async def _ping(args: argparse.Namespace) -> int:
    try:
        ping_command(args.host, args.timeout)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE
    probe = PingProbe(args.host, interval=args.interval, timeout=args.timeout)
    stall = args.interval + args.timeout + 5.0
    state, samples, path = await _measure(args, probe, "ping", args.host, _show_ping, stall)

    s = summarize_latency(samples)
    print(f"sent {s.sent}, lost {s.lost} ({s.loss_percent:.1f}%)")
    if s.avg_ms is not None:
        jitter = "n/a" if s.jitter_ms is None else f"{s.jitter_ms:.2f}"
        print(
            f"rtt min/avg/max {s.min_ms:.2f}/{s.avg_ms:.2f}/{s.max_ms:.2f} ms, "
            f"jitter {jitter} ms"
        )
    return _finish(state, path)


def _show_wifi(values: Mapping[str, float]) -> str:
    if not values.get("associated"):
        return "not connected"
    parts = [f"rssi {values['rssi_dbm']:4.0f} dBm"]
    if "snr_db" in values:
        parts.append(f"snr {values['snr_db']:3.0f} dB")
    if "channel" in values:
        channel = f"ch {values['channel']:.0f}"
        extra = []
        if "band_ghz" in values:
            extra.append(f"{values['band_ghz']:g} GHz")
        if "width_mhz" in values:
            extra.append(f"{values['width_mhz']:.0f} MHz")
        parts.append(channel + (f" ({', '.join(extra)})" if extra else ""))
    if "tx_rate_mbps" in values:
        parts.append(f"{values['tx_rate_mbps']:.0f} Mbps")
    return "  ".join(parts)


async def _pick_wifi(prefix: str, iface: str | None) -> Device | str:
    """The Wi-Fi device to use, or an error message."""
    manager = DeviceManager(_providers())
    devices = [d for d in await manager.refresh() if d.id.startswith(prefix)]
    if iface is not None:
        devices = [d for d in devices if d.id == prefix + iface]
        if not devices:
            return f"no Wi-Fi interface named {iface}"
    if not devices:
        return "no Wi-Fi interface found"
    return devices[0]


async def _wifi(args: argparse.Namespace) -> int:
    backend = _wifi_backend()
    if backend is None:
        print(f"error: Wi-Fi measurement is not supported on {sys.platform} yet", file=sys.stderr)
        return EXIT_FAILED
    _, make_reader, prefix = backend
    device = await _pick_wifi(prefix, args.iface)
    if isinstance(device, str):
        print(f"error: {device}", file=sys.stderr)
        return EXIT_FAILED
    identity = device.support(Capability.WIFI_IDENTITY)
    if not identity.supported:
        print(f"note: network name is not shown: {identity.reason}")

    interface = device.id.removeprefix(prefix)
    probe = WifiLinkProbe(device.id, make_reader(interface), interval=args.interval)
    state, samples, path = await _measure(
        args, probe, "wifi", device.name, _show_wifi, args.interval + 5.0
    )

    connected = summarize_metric(samples, "wifi", "associated")
    rssi = summarize_metric(samples, "wifi", "rssi_dbm")
    if connected.count:
        share = 100.0 * (connected.avg or 0.0)
        print(f"samples {connected.count}, connected {share:.0f}% of the time")
    if rssi.count:
        print(f"rssi min/avg/max {rssi.min:.0f}/{rssi.avg:.1f}/{rssi.max:.0f} dBm")
    return _finish(state, path)


def _verify(args: argparse.Namespace) -> int:
    check = verify_run(args.run)
    if not check.sealed:
        verdict = "NOT SEALED (the run did not end normally; data may be incomplete)"
    elif check.intact:
        verdict = "OK"
    else:
        verdict = "MODIFIED (content does not match the seal)"
    print(f"{verdict}: {check.event_count} events, {check.sample_count} sample values")
    return EXIT_OK if check.intact else EXIT_FAILED


def _export(args: argparse.Namespace) -> int:
    out = open(args.output, "w", encoding="utf-8", newline="") if args.output else sys.stdout
    try:
        if args.format == "csv":
            export_csv(args.run, out)
        else:
            export_json(args.run, out)
    finally:
        if args.output:
            out.close()
    return EXIT_OK


# --- argument parsing ---------------------------------------------------------------


def _positive(text: str) -> float:
    value = float(text)
    if value <= 0:
        raise argparse.ArgumentTypeError("must be greater than 0")
    return value


def _add_run_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--duration", type=_positive, help="seconds; default: until Ctrl+C")
    parser.add_argument("--interval", type=_positive, default=1.0, help="seconds between samples")
    parser.add_argument("--out", default="runs", help="directory for run files (default: runs)")
    parser.add_argument("--quiet", action="store_true", help="do not print each sample")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="wls", description="Wireless Lab")
    parser.add_argument("--version", action="version", version=f"wls {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("devices", help="list devices and what each can do")

    ping = sub.add_parser("ping", help="measure latency and loss, and save the run")
    ping.add_argument("host")
    ping.add_argument("--timeout", type=_positive, default=1.0, help="seconds to wait for a reply")
    _add_run_options(ping)

    wifi = sub.add_parser("wifi", help="measure Wi-Fi signal of the current connection")
    wifi.add_argument("--iface", help="interface name (default: the first Wi-Fi interface)")
    _add_run_options(wifi)

    verify = sub.add_parser("verify", help="check that a run file is complete and unmodified")
    verify.add_argument("run")

    export = sub.add_parser("export", help="export a run file")
    export.add_argument("run")
    export.add_argument("--format", choices=["csv", "json"], default="csv")
    export.add_argument("-o", "--output", help="file to write (default: standard output)")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command in ("verify", "export") and not Path(args.run).is_file():
        print(f"error: no such run file: {args.run}", file=sys.stderr)
        return EXIT_USAGE
    match args.command:
        case "devices":
            return asyncio.run(_devices())
        case "ping":
            return asyncio.run(_ping(args))
        case "wifi":
            return asyncio.run(_wifi(args))
        case "verify":
            return _verify(args)
        case "export":
            return _export(args)
    return EXIT_USAGE
