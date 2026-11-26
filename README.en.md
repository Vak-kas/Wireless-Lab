# Wireless Lab (nrtrail) — a local tool to watch, follow and experiment with radio signals

[한국어](README.md) · **English**

Wireless Lab handles signals from SDR devices, the computer's own Wi-Fi and Bluetooth, and saved files with a few clicks
in a web page, and shows what happened with pictures and formulas. It runs only between your browser and a server on
your own computer (`127.0.0.1`).

The goal is one place for cellular (5G NR), Wi-Fi and Bluetooth. When it starts you pick the devices to use and press **Receive** or **Transmit**. With several devices each gets its own tab, and an overview shows every device's results side by side.

The user interface is in Korean by default; an English translation is included.

## What it does

- **Follow a 5G NR base station** (NTN included): scan → SSB → MIB → SIB1 → SIB19, in order. Every value on screen can be expanded into "raw value → formula → result → clause of the standard".
- **Receive**: pick a band and channels, or type a center frequency and bandwidth, to look at that band. Frequencies you look at often can be saved.
- **Signal analysis**: opens a recorded I/Q file (SigMF, .cfile, .cs16) and takes it apart. It scans the whole file for on-off signals (bursts) and draws the spectrogram, spectrum, waveform, instantaneous frequency and constellation of any span. Pick one signal to measure its centre frequency, occupied width and (guessed) modulation and decode it to bits. It can decode every burst and compare them: whether the signal matches (carrier, deviation, symbol rate) and whether the data matches (aligned bits, fixed and changing fields) are shown separately. No device needed.
- **Live view** (Pro): receives without gaps until you stop and draws the spectrum and spectrogram 20 times a second. It names the signals it sees from their width and band (a guess) and marks separately the ones that were actually decoded. A record button saves the I/Q to a file (SigMF) while receiving.
- **Compare channel levels**: steps through Wi-Fi 2.4 / 5 / 6 GHz and Bluetooth channels and compares their power.
- **Wi-Fi**: Pro also decodes nearby APs, frame types and bandwidth.
- **Bluetooth**: receive and decode BLE advertisements (broadcasts meant for anyone to receive).
- **Nearby**: even without an SDR, see the channels and strength of nearby networks and the advertisements of nearby devices with the computer's own Wi-Fi and Bluetooth (no connection is made).
- **Experimental transmit** (Pro): send a test tone, standard test signals or your own waveform, and receive while sending to check that it really went out. Several devices can be started at the same instant.
- **Several devices together**: set each device up separately — for example send on one while receiving on another — and start or stop them all at once.
- **Practice mode**: replays saved results, so you can go through the whole flow without any device.

This public edition (Basic) is **receive-only**.

## Devices

| Kind | Examples | What you can do |
|---|---|---|
| Plug-in device (SDR) | USRP B, N and X series and E320 (Pro, registered automatically when plugged in), SoapySDR devices | Follow a base station, receive, live view (Pro), channel level comparison, Bluetooth reception, transmit (Pro) |
| The computer's Wi-Fi adapter (built-in or external) | Laptop Wi-Fi, USB Wi-Fi adapter | Channel, width and strength of nearby networks |
| The computer's Bluetooth adapter (built-in or external) | Built-in Bluetooth, USB dongle | Advertisements of nearby devices (name, maker, strength) |
| No device | — | Practice mode, opening saved files |

## Basic and Pro

| | Basic (this repository, free) | Pro (private) |
|---|---|---|
| Web UI, local server, practice mode | ✓ | ✓ |
| Broadcast information decoding (MIB, SIB1, SIB19), satellite (NTN) calculations, tracking, report | ✓ | ✓ |
| Receive screen (pick band and channels, look once), channel level comparison, BLE advertisement reception | ✓ | ✓ |
| Workbench: a tab per device, overview, start and stop all | ✓ | ✓ |
| Look around with the computer's own Wi-Fi and Bluetooth (built-in or external adapters) | ✓ | ✓ |
| 5G NR signal-processing engine for real signals (based on MATLAB 5G Toolbox) | — | ✓ |
| Automatic USRP registration and reception (a C++ helper talks to UHD directly; a MATLAB path also exists) | recognised only | ✓ |
| Live view: gapless receive, 20 redraws a second, signal naming, recording | — | ✓ |
| Wi-Fi beacon and preamble decoding (nearby APs, bandwidth) | — | ✓ |
| Experimental transmit (a responsibility confirmation is required every time) | — | ✓ |
| Receive-while-sending check (one or two USRPs) | — | ✓ |
| Start several transmitters at the same instant | — | ✓ |
| A slot for your own signal generators (`plugins/tx/`) | — | ✓ |
| OAI NTN simulator testbed | — | ✓ |

Pro is an overlay on top of this repository. Decoding signals needs MATLAB with the relevant toolboxes; gapless USRP receive and transmit needs UHD (the USRP driver).

**Pro inquiries**: [smjgallery.kr](https://smjgallery.kr) · <mjseo@smjgallery.kr>

## What is in this repository

- `web/` the UI (React + TypeScript + Vite)
- `server/` the local server (FastAPI): sessions, jobs, device layer, ASN.1 decoding, standard tables, satellite calculations, channel level comparison, BLE receiver, signal-kind guessing
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
| macOS | `Wireless Lab.app` (opens just the window) or `nrtrail.command` (a terminal window opens with it; the first run may ask for folder access) |
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
