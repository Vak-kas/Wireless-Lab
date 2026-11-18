# nrtrail — a local tool for watching and following radio signals with an SDR

[한국어](README.md) · **English**

nrtrail receives signals from an SDR device (or a saved file) with a few clicks in a web page, and shows
what happened with pictures and formulas. It runs only between your browser and a server on your own
computer (`127.0.0.1`).

- **Follow a 5G NR base station** (NTN included): scan → SSB → MIB → SIB1 → SIB19, in order. Every value on screen can be expanded into "raw value → formula → result → clause of the standard".
- **Look at the spectrum**: pick a center frequency and width to see the spectrum, and keep watching per-channel power on Wi-Fi 2.4 / 5 / 6 GHz.
- **Bluetooth**: receive and decode BLE advertisements (broadcasts meant for anyone to receive).
- **Nearby**: even without an SDR, see the channels and strength of nearby networks and the advertisements of nearby devices with the computer's own Wi-Fi and Bluetooth (no connection is made).
- **Practice mode**: replays saved results, so you can go through the whole flow without any device.

This public edition (Basic) is **receive-only**.

The user interface is in Korean by default; an English translation is included.

## Basic and Pro

| | Basic (this repository, free) | Pro (private) |
|---|---|---|
| Web UI, local server, practice mode | ✓ | ✓ |
| Broadcast information decoding (MIB, SIB1, SIB19), satellite (NTN) calculations, tracking, report | ✓ | ✓ |
| Channel power monitor, spectrum, BLE advertisement reception | ✓ | ✓ |
| Look around with the computer's own Wi-Fi and Bluetooth (built-in or external adapters) | ✓ | ✓ |
| 5G NR signal-processing engine for real signals (based on MATLAB 5G Toolbox) | — | ✓ |
| Automatic USRP registration and reception (MATLAB) | — | ✓ |
| Wi-Fi beacon and preamble decoding (nearby APs, bandwidth) | — | ✓ |
| Experimental transmit (a responsibility confirmation is required every time), receive-while-sending check | — | ✓ |
| OAI NTN simulator testbed | — | ✓ |

Pro is an overlay on top of this repository and requires MATLAB with the relevant toolboxes.

**Pro inquiries**: [smjgallery.kr](https://smjgallery.kr) · <mjseo@smjgallery.kr>

## What is in this repository

- `web/` the UI (React + TypeScript + Vite)
- `server/` the local server (FastAPI): sessions, jobs, device layer, ASN.1 decoding, standard tables, satellite calculations, channel monitor, BLE receiver
- `pipeline/` stage definitions and texts, and the saved results that practice mode replays
- `tools/` environment check, launcher, full verification

To use a real device with Basic you need to install SoapySDR and a device module yourself (practice mode works without them).

## Running

```
python3.12 -m venv venv
venv/bin/pip install -e '.[dev]'
cd web && npm install && npm run build && cd ..
venv/bin/python tools/doctor.py          # environment check
venv/bin/python tools/dev.py --built     # http://127.0.0.1:8765
```

To use it like an application, double-click the file below. If there is no virtual environment yet, it creates one on first run and installs the Python packages it needs (`tools/bootstrap.py`; building the UI requires Node.js). It starts the server and opens a window; closing the window shuts everything down.

| OS | Launcher |
|---|---|
| macOS | `nrtrail.app` or `nrtrail.command` (a terminal window opens with it; the first run may ask for folder access) |
| Windows | `nrtrail.bat` |
| Linux | `./nrtrail.sh` |

On Windows use `venv\Scripts\python` instead. Full verification: `venv/bin/python tools/verify.py`.

## What it does not do

- This public edition contains no transmit (TX) code. It never calls the transmit path of any SDR API. (The "Transmit" tile in the UI is enabled only when Pro is present.)
- No edition contains jamming, spoofing, or fake base station features.
- The server listens on `127.0.0.1` only.
- From live device input it processes broadcast information only (a base station's SSB, MIB and SIB; Wi-Fi beacons and frame preambles; BLE advertisements). It does not decode what individual devices exchange with each other.

## Platforms

Developed and tested on macOS. Windows and Linux support is in progress.

## License

Apache License 2.0 — see [LICENSE](LICENSE). The Pro overlay is not covered by this license.
External programs used alongside it (MATLAB, UHD, and others) are under their own licenses and are not included in this repository.
