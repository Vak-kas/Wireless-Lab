# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 서민재
"""Command line interface. A thin client of the controller.

    wls devices
    wls ping HOST [--duration S] [--interval S] [--out DIR]
    wls wifi [--iface NAME] [--duration S] [--interval S] [--out DIR]
    wls diagnose [--target HOST] [--duration S] [--out DIR]
    wls speed [--seconds S] [--down-url URL] [--up-url URL] [--out DIR]
    wls web [--port N] [--runs DIR]
    wls macos-setup
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
from wls.analysis.diagnosis import diagnose_samples
from wls.analysis.summary import SampleRow, summarize_latency, summarize_metric
from wls.core.devices import DeviceManager
from wls.core.export import export_csv, export_json
from wls.core.interfaces import Event, Sample
from wls.core.state_machine import State
from wls.core.storage import SqliteRecorder, read_run, verify_run
from wls.measurements import (
    Plan,
    PlanError,
    plan_diagnose,
    plan_ping,
    plan_speed,
    plan_wifi,
    providers,
    run_plan,
)
from wls.probes.speed import DEFAULT_DOWN_URL, DEFAULT_UP_URL

EXIT_OK, EXIT_FAILED, EXIT_USAGE = 0, 1, 2

Show = Callable[[Sample], str]


class _LiveRecorder:
    """Stores to disk and prints each sample as it arrives."""

    def __init__(self, store: SqliteRecorder, show: Show | None) -> None:
        self._store = store
        self._show = show

    def sample(self, sample: Sample) -> None:
        self._store.sample(sample)
        if self._show is not None:
            print("  " + self._show(sample), flush=True)

    def event(self, event: Event) -> None:
        self._store.event(event)


def _on_interrupt(loop: asyncio.AbstractEventLoop, stop: asyncio.Event) -> None:
    try:
        loop.add_signal_handler(signal.SIGINT, stop.set)
    except NotImplementedError:  # Windows
        signal.signal(signal.SIGINT, lambda *_: loop.call_soon_threadsafe(stop.set))


async def _measure(
    args: argparse.Namespace, plan: Plan, show: Show
) -> tuple[State, list[SampleRow], Path]:
    """Run a plan until the duration ends, Ctrl+C, or a failure. Saves the run."""
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = Path(args.out) / f"{stamp}-{plan.kind}.sqlite"
    store = SqliteRecorder(path)
    recorder = _LiveRecorder(store, None if args.quiet else show)
    stop = asyncio.Event()
    _on_interrupt(asyncio.get_running_loop(), stop)
    for note in plan.notes:
        print(f"note: {note}")
    print(f"measuring {plan.title} (Ctrl+C to stop)", flush=True)
    try:
        state = await run_plan(
            plan, recorder, duration=getattr(args, "duration", None), stop=stop
        )
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


def _plan_error(exc: PlanError) -> int:
    print(f"error: {exc}", file=sys.stderr)
    usage = "invalid host" in str(exc) or "not an http" in str(exc)
    return EXIT_USAGE if usage else EXIT_FAILED


def _finish(state: State, path: Path) -> int:
    print(f"saved {path}")
    return EXIT_OK if state is State.COMPLETED else EXIT_FAILED


# --- commands ---------------------------------------------------------------------


async def _devices() -> int:
    manager = DeviceManager(providers())
    for device in await manager.refresh():
        print(f"{device.id}: {device.name}")
        for capability, support in device.capabilities.items():
            status = "yes" if support.supported else f"no ({support.reason})"
            print(f"  {capability.value:<18} {status}")
    for provider, error in manager.provider_errors.items():
        print(f"warning: provider {provider} failed: {error}", file=sys.stderr)
    return EXIT_OK


def _show_ping(sample: Sample) -> str:
    rtt = sample.values.get("rtt_ms")
    return "lost" if rtt is None else f"{rtt:8.2f} ms"


async def _ping(args: argparse.Namespace) -> int:
    try:
        plan = plan_ping(args.host, args.interval, args.timeout)
    except PlanError as exc:
        return _plan_error(exc)
    state, samples, path = await _measure(args, plan, _show_ping)

    s = summarize_latency(samples)
    print(f"sent {s.sent}, lost {s.lost} ({s.loss_percent:.1f}%)")
    if s.avg_ms is not None:
        jitter = "n/a" if s.jitter_ms is None else f"{s.jitter_ms:.2f}"
        print(
            f"rtt min/avg/max {s.min_ms:.2f}/{s.avg_ms:.2f}/{s.max_ms:.2f} ms, "
            f"jitter {jitter} ms"
        )
    return _finish(state, path)


def _show_wifi(sample: Sample) -> str:
    return format_wifi(sample.values)


def format_wifi(values: Mapping[str, float]) -> str:
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


async def _wifi(args: argparse.Namespace) -> int:
    try:
        plan = await plan_wifi(args.iface, args.interval)
    except PlanError as exc:
        return _plan_error(exc)
    state, samples, path = await _measure(args, plan, _show_wifi)

    connected = summarize_metric(samples, "wifi", "associated")
    rssi = summarize_metric(samples, "wifi", "rssi_dbm")
    if connected.count:
        share = 100.0 * (connected.avg or 0.0)
        print(f"samples {connected.count}, connected {share:.0f}% of the time")
    if rssi.count:
        print(f"rssi min/avg/max {rssi.min:.0f}/{rssi.avg:.1f}/{rssi.max:.0f} dBm")
    return _finish(state, path)


def _show_speed(sample: Sample) -> str:
    ((key, value),) = sample.values.items()
    return f"{'download' if key == 'down_mbps' else 'upload':<8} {value:8.1f} Mbps"


def _steady_average(samples: list[SampleRow], metric: str) -> float | None:
    """Average rate, leaving out the first sample (connection setup and ramp-up)."""
    values = [v for _, probe, m, v in samples if probe == "speed" and m == metric]
    if len(values) > 2:
        values = values[1:]
    return sum(values) / len(values) if values else None


async def _speed(args: argparse.Namespace) -> int:
    try:
        plan = plan_speed(args.down_url, args.up_url, args.seconds)
    except PlanError as exc:
        return _plan_error(exc)
    state, samples, path = await _measure(args, plan, _show_speed)

    print()
    for label, metric in (("download", "down_mbps"), ("upload", "up_mbps")):
        average = _steady_average(samples, metric)
        if average is not None:
            print(f"{label:<8} {average:8.1f} Mbps")
    return _finish(state, path)


def _show_diagnose(sample: Sample) -> str:
    text = format_wifi(sample.values) if sample.probe == "wifi" else _show_ping(sample).strip()
    return f"{sample.probe:<9} {text}"


async def _diagnose(args: argparse.Namespace) -> int:
    try:
        plan = await plan_diagnose(args.target, args.interval)
    except PlanError as exc:
        return _plan_error(exc)
    state, samples, path = await _measure(args, plan, _show_diagnose)

    internet = summarize_latency(samples, "internet")
    router = summarize_latency(samples, "router")
    result = diagnose_samples(samples)
    print()
    for label, s in (("router", router), ("internet", internet)):
        if s.sent:
            avg = "no reply" if s.avg_ms is None else f"{s.avg_ms:.1f} ms average"
            print(f"{label:<9} {avg}, {s.loss_percent:.0f}% lost")
    print(f"result: {result.headline}")
    for detail in result.details:
        print(f"  - {detail}")
    return _finish(state, path)


def _web(args: argparse.Namespace) -> int:
    import uvicorn

    from wls.web.app import create_app

    app = create_app(args.runs, providers)
    print(f"Wireless Lab is running at http://127.0.0.1:{args.port}  (Ctrl+C to stop)", flush=True)
    # Bound to this computer only: the UI has no login.
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
    return EXIT_OK


def _macos_setup() -> int:
    if sys.platform != "darwin":
        print("error: this command is for macOS only", file=sys.stderr)
        return EXIT_FAILED
    from wls.providers import macos_helper

    print("macOS shows Wi-Fi network names only to an app allowed to use Location Services.")
    print("Building the helper app if needed; then macOS may ask you to allow it.")
    try:
        status = macos_helper.setup()
    except macos_helper.HelperError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_FAILED
    print(f"helper: {macos_helper.APP}")
    if status == "authorized":
        print("allowed: network names will be shown")
        return EXIT_OK
    print(f"not allowed yet: {macos_helper.STATUS_HELP.get(status, status)}")
    return EXIT_FAILED


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

    diag = sub.add_parser("diagnose", help="find out whether Wi-Fi or the internet is the problem")
    diag.add_argument("--target", default="1.1.1.1", help="internet address to test against")
    _add_run_options(diag)
    diag.set_defaults(duration=10.0)

    speed = sub.add_parser("speed", help="measure download and upload speed")
    speed.add_argument("--seconds", type=_positive, default=5.0, help="seconds per direction")
    speed.add_argument("--down-url", default=DEFAULT_DOWN_URL, help="URL of a large download")
    speed.add_argument("--up-url", default=DEFAULT_UP_URL, help="URL that accepts an upload")
    speed.add_argument("--out", default="runs", help="directory for run files (default: runs)")
    speed.add_argument("--quiet", action="store_true", help="do not print each sample")

    web = sub.add_parser("web", help="show recorded runs in the browser (this computer only)")
    web.add_argument("--port", type=int, default=8765)
    web.add_argument("--runs", default="runs", help="directory with run files (default: runs)")

    sub.add_parser("macos-setup", help="macOS: allow Wi-Fi network names to be shown (one time)")

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
        case "diagnose":
            return asyncio.run(_diagnose(args))
        case "speed":
            return asyncio.run(_speed(args))
        case "web":
            return _web(args)
        case "macos-setup":
            return _macos_setup()
        case "verify":
            return _verify(args)
        case "export":
            return _export(args)
    return EXIT_USAGE
