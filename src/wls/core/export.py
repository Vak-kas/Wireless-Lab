# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 서민재
"""Export a recorded run to CSV (samples) or JSON (everything)."""

from __future__ import annotations

import csv
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import TextIO

from wls.core.storage import read_meta, read_run, verify_run


def _wall_clock(meta: dict[str, str]):
    """Convert a monotonic timestamp of this run to UTC wall time."""
    start = datetime.fromisoformat(meta["started_wall_utc"])
    start_ns = int(meta["started_mono_ns"])

    def convert(t_ns: int) -> str:
        return (start + timedelta(microseconds=(t_ns - start_ns) / 1000)).isoformat()

    return convert


def export_csv(run: str | Path, out: TextIO) -> int:
    """Write one line per sample value. Returns the number of lines."""
    wall = _wall_clock(read_meta(run))
    _, samples = read_run(run)
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(["time_utc", "t_ns", "probe", "metric", "value"])
    for t_ns, probe, metric, value in samples:
        writer.writerow([wall(t_ns), t_ns, probe, metric, value])
    return len(samples)


def export_json(run: str | Path, out: TextIO) -> None:
    meta = read_meta(run)
    wall = _wall_clock(meta)
    check = verify_run(run)
    events, samples = read_run(run)
    document = {
        "meta": meta,
        "sealed": check.sealed,
        "intact": check.intact,
        "events": [
            {"time_utc": wall(e.t_ns), "t_ns": e.t_ns, "kind": e.kind, "data": e.data}
            for e in events
        ],
        "samples": [
            {"time_utc": wall(t), "t_ns": t, "probe": p, "metric": m, "value": v}
            for t, p, m, v in samples
        ],
    }
    json.dump(document, out, ensure_ascii=False, indent=2)
    out.write("\n")
