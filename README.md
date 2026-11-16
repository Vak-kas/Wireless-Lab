# Wireless Lab

Local software for measuring wireless link quality and running controlled,
repeatable measurement experiments. It runs on your own machine; there is no
cloud service.

**Status: early development.** Latency and loss measurement works from the
command line; everything else is still planned.

## Usage

Install once (Python 3.12 or newer, pip 25.1 or newer):

```bash
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -e . --group dev
```

Then:

```bash
wls devices
wls diagnose
wls ping 1.1.1.1 --duration 10
wls wifi --duration 10
wls speed
wls web                          # then open http://127.0.0.1:8765
wls verify runs/<file>.sqlite
wls export runs/<file>.sqlite --format csv -o out.csv
```

The quickest way to check a connection:

```bash
wls diagnose
```

`wls diagnose` measures the router, an internet address and the Wi-Fi signal
together for 10 seconds and says where the problem is: Wi-Fi, the local
network, or beyond the router. Its thresholds are rules of thumb and the
result describes only the measured period.

`wls web` is the easy way in. The first screen shows your Wi-Fi signal right
now in plain words, the Wi-Fi networks around you, and one button that checks
the connection and says where a problem is. Other measurements, charts and
past results are one click away. The page is in Korean or English, following
the browser language. It
listens on this computer only, has no login, and refuses requests coming from
other web pages.

`wls ping` runs until `--duration` elapses or you press Ctrl+C, prints each
reply, and saves the run to `runs/`. A run that ended normally is sealed with
a hash; `wls verify` tells whether a file is complete and unmodified.

No administrator rights are needed. `wls ping` uses the system `ping` command
and works on macOS, Windows and Linux.

`wls wifi` records signal strength, noise, channel and link rate of the
current Wi-Fi connection. It is implemented for macOS so far.

### Connection log and live lists

While `wls web` is running it watches the Wi-Fi connection and records when
the computer moves to another access point of the same network (a roam),
loses the connection, reconnects, or switches networks. The log is shown in
the Wi-Fi section and kept in `runs/wifi-events.jsonl`. A recorded roam means
the access point changed between two observations a second or more apart; it
does not show which 802.11 procedure was used or how long it took.

The lists of nearby Wi-Fi networks and Bluetooth devices keep updating while
their section is open; a checkbox turns that off.

Each device in the Bluetooth list has a *Track* button that records one
device's signal strength over time as a normal run, with a live chart, until
you stop it. It only listens to what the device broadcasts; it never connects.

### Bluetooth

The Bluetooth section of `wls web` lists Bluetooth Low Energy devices around
you with their signal strength, the name and maker where a device broadcasts
them, and whether it accepts connections. Nothing is connected to. It is
implemented for macOS so far and uses the helper app described below; macOS
asks for Bluetooth permission the first time.

### Network names on macOS

macOS gives Wi-Fi network names (SSID) and BSSIDs only to an application that
you allowed to use Location Services. Run this once:

```bash
wls macos-setup
```

It builds a small helper app from the Swift source in this repository (needs
the Xcode command line tools), installs it under
`~/Library/Application Support/WirelessLab/`, and macOS asks whether to allow
it. The helper only prints Wi-Fi information for Wireless Lab; it does not
read, store or send your location. Without it everything else still works,
and nearby networks are listed without their names. The helper is signed for
your own computer only; rebuilding it makes macOS ask again.

`wls speed` measures download and upload throughput against an HTTP server
(`--down-url`, `--up-url`; the default is Cloudflare's public speed test
endpoint). It transfers real data for the whole duration. Upload figures from
short runs are rough.

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
pytest
```

[uv](https://docs.astral.sh/uv/) works too and uses the committed lock file:
`uv sync --no-editable`, then `uv run --no-editable wls ...` and
`uv run pytest`. `--no-editable` avoids a macOS problem seen with uv's `.venv`
in synced folders (for example Desktop with iCloud): files inside it can be
marked hidden, and Python 3.13 then ignores the path file an editable install
relies on.

## License

GPL-3.0-or-later. See [LICENSE](LICENSE).

Copyright (C) 2026 서민재
