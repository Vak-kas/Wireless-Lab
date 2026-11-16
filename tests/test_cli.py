# SPDX-License-Identifier: GPL-3.0-or-later
import csv
import io
import json
import shutil
import sqlite3

import pytest

from wls.analysis.summary import summarize_latency
from wls.cli import main
from wls.core.export import export_csv, export_json
from wls.core.interfaces import Event, Sample
from wls.core.storage import SqliteRecorder, verify_run

needs_ping = pytest.mark.skipif(shutil.which("ping") is None, reason="no system ping")


@pytest.fixture
def run_file(tmp_path):
    path = tmp_path / "run.sqlite"
    recorder = SqliteRecorder(path)
    recorder.event(Event(1_000, "state", {"state": "measuring"}))
    for i, rtt in enumerate([10.0, 14.0, None, 12.0]):
        values = {"lost": 1.0} if rtt is None else {"rtt_ms": rtt, "lost": 0.0}
        recorder.sample(Sample("ping", 2_000 + i, values))
    recorder.close()
    return path


# --- summary ----------------------------------------------------------------------


def test_latency_summary():
    rows = [
        (1, "ping", "rtt_ms", 10.0), (1, "ping", "lost", 0.0),
        (2, "ping", "rtt_ms", 14.0), (2, "ping", "lost", 0.0),
        (3, "ping", "lost", 1.0),
        (4, "ping", "rtt_ms", 12.0), (4, "ping", "lost", 0.0),
        (5, "other", "rtt_ms", 999.0),
    ]  # fmt: skip
    s = summarize_latency(rows)
    assert (s.sent, s.lost, s.loss_percent) == (4, 1, 25.0)
    assert (s.min_ms, s.avg_ms, s.max_ms) == (10.0, 12.0, 14.0)
    assert s.jitter_ms == 3.0  # (|14-10| + |12-14|) / 2


def test_summary_of_a_run_with_no_replies():
    s = summarize_latency([(1, "ping", "lost", 1.0), (2, "ping", "lost", 1.0)])
    assert (s.sent, s.lost, s.loss_percent, s.avg_ms, s.jitter_ms) == (2, 2, 100.0, None, None)


def test_summary_of_an_empty_run():
    s = summarize_latency([])
    assert (s.sent, s.loss_percent, s.avg_ms) == (0, 0.0, None)


# --- export ------------------------------------------------------------------------


def test_csv_export_has_one_line_per_value_with_wall_time(run_file):
    out = io.StringIO()
    assert export_csv(run_file, out) == 7
    rows = list(csv.DictReader(io.StringIO(out.getvalue())))
    assert len(rows) == 7
    assert rows[0]["probe"] == "ping" and rows[0]["metric"] == "rtt_ms"
    assert float(rows[0]["value"]) == 10.0
    assert rows[0]["time_utc"].endswith("+00:00")
    assert [r["time_utc"] for r in rows] == sorted(r["time_utc"] for r in rows)


def test_json_export_contains_everything_and_the_seal_status(run_file):
    out = io.StringIO()
    export_json(run_file, out)
    document = json.loads(out.getvalue())
    assert document["sealed"] is True and document["intact"] is True
    assert document["events"][0]["kind"] == "state"
    assert len(document["samples"]) == 7


# --- command line --------------------------------------------------------------------


def test_devices_lists_this_computer(capsys):
    assert main(["devices"]) == 0
    out = capsys.readouterr().out
    assert "host: This computer" in out
    assert "net_probe" in out


def test_verify_reports_ok_modified_and_missing(run_file, capsys, tmp_path):
    assert main(["verify", str(run_file)]) == 0
    assert capsys.readouterr().out.startswith("OK")

    db = sqlite3.connect(run_file)
    with db:
        db.execute("UPDATE sample SET value = 1.0 WHERE metric = 'rtt_ms'")
    db.close()
    assert main(["verify", str(run_file)]) == 1
    assert capsys.readouterr().out.startswith("MODIFIED")

    assert main(["verify", str(tmp_path / "nope.sqlite")]) == 2


def test_verify_reports_a_run_that_was_never_closed(tmp_path, capsys):
    path = tmp_path / "crashed.sqlite"
    SqliteRecorder(path).event(Event(1, "state", {"state": "measuring"}))
    assert main(["verify", str(path)]) == 1
    assert capsys.readouterr().out.startswith("NOT SEALED")


def test_export_to_file_and_to_standard_output(run_file, tmp_path, capsys):
    target = tmp_path / "out.csv"
    assert main(["export", str(run_file), "-o", str(target)]) == 0
    assert target.read_text(encoding="utf-8").startswith("time_utc,t_ns,probe,metric,value\n")

    assert main(["export", str(run_file), "--format", "json"]) == 0
    assert json.loads(capsys.readouterr().out)["intact"] is True


def test_ping_refuses_a_host_that_looks_like_an_option(tmp_path, capsys):
    assert main(["ping", "--out", str(tmp_path), "--", "-f"]) == 2
    assert "invalid host" in capsys.readouterr().err
    assert not list(tmp_path.iterdir())


@needs_ping
def test_ping_measures_saves_and_summarizes(tmp_path, capsys):
    code = main(
        ["ping", "127.0.0.1", "--duration", "0.4", "--interval", "0.1", "--out", str(tmp_path)]
    )
    out = capsys.readouterr().out
    assert code == 0, out
    assert "measuring 127.0.0.1" in out
    assert "lost 0 (0.0%)" in out
    assert "rtt min/avg/max" in out

    (run,) = tmp_path.glob("*-ping.sqlite")
    check = verify_run(run)
    assert check.sealed and check.intact and check.sample_count >= 2


@needs_ping
def test_ping_to_an_unreachable_address_reports_loss_but_completes(tmp_path, capsys):
    # 192.0.2.0/24 is reserved for documentation and never answers.
    code = main(
        ["ping", "192.0.2.1", "--duration", "0.5", "--interval", "0.1", "--timeout", "0.2",
         "--quiet", "--out", str(tmp_path)]
    )  # fmt: skip
    out = capsys.readouterr().out
    assert code == 0, out
    assert "(100.0%)" in out
    assert "rtt min/avg/max" not in out
