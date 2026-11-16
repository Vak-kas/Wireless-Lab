# Wireless Lab

Local software for measuring wireless link quality and running controlled,
repeatable measurement experiments. It runs on your own machine; there is no
cloud service.

**Status: early development.** Latency and loss measurement works from the
command line; everything else is still planned.

## Usage

```bash
uv sync --no-editable
uv run --no-editable wls devices
uv run --no-editable wls ping 1.1.1.1 --duration 10
uv run --no-editable wls verify runs/<file>.sqlite
uv run --no-editable wls export runs/<file>.sqlite --format csv -o out.csv
```

`wls ping` runs until `--duration` elapses or you press Ctrl+C, prints each
reply, and saves the run to `runs/`. A run that ended normally is sealed with
a hash; `wls verify` tells whether a file is complete and unmodified.

No administrator rights are needed. Measurement uses the system `ping`
command and works on macOS, Windows and Linux.

## Planned scope of this repository

- Experiment controller: explicit start, stop and recovery of measurement runs
- Wi-Fi link information (SSID, BSSID, channel, RSSI) where the OS allows it
- Latency, packet loss, jitter and throughput measurement
- Recording of results with export to CSV and JSON
- A simulated device provider for development and testing without hardware

Features that depend on the operating system, adapter or driver report whether
they are supported and why not.

## Development

```bash
uv sync
uv run pytest
```

`--no-editable` in the usage commands avoids a macOS problem: in synced
folders (for example Desktop with iCloud) files inside `.venv` can be marked
hidden, and Python 3.13 then ignores the path file an editable install relies
on. Tests are not affected because they import from `src/` directly.

## License

GPL-3.0-or-later. See [LICENSE](LICENSE).

Copyright (C) 2026 서민재
