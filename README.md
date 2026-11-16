# Wireless Lab

Local software for measuring wireless link quality and running controlled,
repeatable measurement experiments. It runs on your own machine; there is no
cloud service.

**Status: early development. Nothing here is usable yet.**

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

## License

GPL-3.0-or-later. See [LICENSE](LICENSE).

Copyright (C) 2026 서민재
