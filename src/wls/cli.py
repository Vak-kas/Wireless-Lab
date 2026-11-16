# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 서민재
"""Command line interface. A thin client of the controller.

    wls devices
    wls ping HOST [--duration S] [--interval S] [--out DIR]
    wls verify RUN.sqlite
    wls export RUN.sqlite --format csv|json [-o FILE]
"""

from __future__ import annotations

import argparse
import asyncio
import signal
import sys
from datetime import UTC, datetime
from pathlib import Path

from wls import __version__
from wls.analysis.summary import summarize_latency
from wls.core.controller import Controller, ExperimentConfig
from wls.core.devices import DeviceManager
from wls.core.export import export_csv, export_json
from wls.core.interfaces import Event, Sample
from wls.core.state_machine import Command, State
from wls.core.storage import SqliteRecorder, read_run, verify_run
from wls.probes.ping import PingProbe, ping_command
from wls.providers.host import LocalHostProvider

EXIT_OK, EXIT_FAILED, EXIT_USAGE = 0, 1, 2


def _providers():
    return [LocalHostProvider()]


class _LiveRecorder:
    """Stores to disk and prints each ping result as it arrives."""

    def __init__(self, store: SqliteRecorder, quiet: bool) -> None:
        self._store = store
        self._quiet = quiet

    def sample(self, sample: Sample) -> None:
        self._store.sample(sample)
        if not self._quiet:
            rtt = sample.values.get("rtt_ms")
            print("  lost" if rtt is None else f"  {rtt:8.2f} ms", flush=True)

    def event(self, event: Event) -> None:
        self._store.event(event)


def _on_interrupt(loop: asyncio.AbstractEventLoop, stop: asyncio.Event) -> None:
    try:
        loop.add_signal_handler(signal.SIGINT, stop.set)
    except NotImplementedError:  # Windows
        signal.signal(signal.SIGINT, lambda *_: loop.call_soon_threadsafe(stop.set))


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


async def _ping(args: argparse.Namespace) -> int:
    try:
        ping_command(args.host, args.timeout)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = Path(args.out) / f"{stamp}-ping.sqlite"
    store = SqliteRecorder(path)
    controller = Controller(DeviceManager(_providers()), _LiveRecorder(store, args.quiet))
    probe = PingProbe(args.host, interval=args.interval, timeout=args.timeout)
    config = ExperimentConfig((probe,), stall_timeout=args.interval + args.timeout + 5.0)

    stop = asyncio.Event()
    _on_interrupt(asyncio.get_running_loop(), stop)
    terminal = (State.COMPLETED, State.FAILED)
    try:
        controller.submit(Command.PREPARE, config=config)
        state = (await controller.wait_state(State.READY, *terminal, timeout=30)).state
        if state is State.READY:
            print(f"measuring {args.host} (Ctrl+C to stop)", flush=True)
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

    s = summarize_latency(samples)
    print(f"sent {s.sent}, lost {s.lost} ({s.loss_percent:.1f}%)")
    if s.avg_ms is not None:
        jitter = "n/a" if s.jitter_ms is None else f"{s.jitter_ms:.2f}"
        print(
            f"rtt min/avg/max {s.min_ms:.2f}/{s.avg_ms:.2f}/{s.max_ms:.2f} ms, "
            f"jitter {jitter} ms"
        )
    print(f"saved {path}")
    return EXIT_OK if state is State.COMPLETED else EXIT_FAILED


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


def _positive(text: str) -> float:
    value = float(text)
    if value <= 0:
        raise argparse.ArgumentTypeError("must be greater than 0")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="wls", description="Wireless Lab")
    parser.add_argument("--version", action="version", version=f"wls {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("devices", help="list devices and what each can do")

    ping = sub.add_parser("ping", help="measure latency and loss, and save the run")
    ping.add_argument("host")
    ping.add_argument("--duration", type=_positive, help="seconds; default: until Ctrl+C")
    ping.add_argument("--interval", type=_positive, default=1.0, help="seconds between samples")
    ping.add_argument("--timeout", type=_positive, default=1.0, help="seconds to wait for a reply")
    ping.add_argument("--out", default="runs", help="directory for run files (default: runs)")
    ping.add_argument("--quiet", action="store_true", help="do not print each sample")

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
        case "verify":
            return _verify(args)
        case "export":
            return _export(args)
    return EXIT_USAGE
