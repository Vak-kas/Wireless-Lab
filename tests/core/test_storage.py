# SPDX-License-Identifier: GPL-3.0-or-later
import shutil
import sqlite3

import pytest

from wls.core.controller import Controller, ExperimentConfig
from wls.core.devices import DeviceManager
from wls.core.interfaces import Event, Sample
from wls.core.state_machine import Command, State
from wls.core.storage import SqliteRecorder, read_run, verify_run
from wls.probes.ping import PingProbe
from wls.providers.host import LocalHostProvider


def fill(recorder: SqliteRecorder) -> None:
    recorder.event(Event(1, "state", {"state": "measuring"}))
    recorder.sample(Sample("ping", 2, {"rtt_ms": 11.5, "lost": 0.0}))
    recorder.sample(Sample("ping", 3, {"lost": 1.0}))
    recorder.event(Event(4, "mark", {"label": "문 열림"}))


def test_everything_written_can_be_read_back_in_order(tmp_path):
    path = tmp_path / "run.sqlite"
    recorder = SqliteRecorder(path)
    fill(recorder)
    recorder.close()

    events, samples = read_run(path)
    assert [(e.t_ns, e.kind, e.data) for e in events] == [
        (1, "state", {"state": "measuring"}),
        (4, "mark", {"label": "문 열림"}),
    ]
    assert samples == [
        (2, "ping", "rtt_ms", 11.5),
        (2, "ping", "lost", 0.0),
        (3, "ping", "lost", 1.0),
    ]


def test_closed_run_is_sealed_and_intact(tmp_path):
    path = tmp_path / "run.sqlite"
    recorder = SqliteRecorder(path)
    fill(recorder)
    recorder.close()
    recorder.close()  # second close is harmless

    check = verify_run(path)
    assert (check.sealed, check.intact) == (True, True)
    assert (check.event_count, check.sample_count) == (2, 3)


def test_changing_a_value_after_sealing_is_detected(tmp_path):
    path = tmp_path / "run.sqlite"
    recorder = SqliteRecorder(path)
    fill(recorder)
    recorder.close()

    db = sqlite3.connect(path)
    with db:
        db.execute("UPDATE sample SET value = 1.0 WHERE metric = 'rtt_ms'")
    db.close()
    assert verify_run(path).intact is False


def test_deleting_a_row_after_sealing_is_detected(tmp_path):
    path = tmp_path / "run.sqlite"
    recorder = SqliteRecorder(path)
    fill(recorder)
    recorder.close()

    db = sqlite3.connect(path)
    with db:
        db.execute("DELETE FROM event WHERE kind = 'mark'")
    db.close()
    assert verify_run(path).intact is False


def test_after_a_crash_data_up_to_the_last_event_is_on_disk(tmp_path):
    path = tmp_path / "run.sqlite"
    recorder = SqliteRecorder(path, flush_rows=1000, flush_interval=3600)
    fill(recorder)
    recorder.sample(Sample("ping", 5, {"rtt_ms": 9.0}))  # still only in memory
    # No close(): the process "dies" here.

    check = verify_run(path)
    assert (check.sealed, check.intact) == (False, False)
    assert (check.event_count, check.sample_count) == (2, 3)


def test_samples_are_written_in_batches_without_waiting_for_an_event(tmp_path):
    path = tmp_path / "run.sqlite"
    recorder = SqliteRecorder(path, flush_rows=10, flush_interval=3600)
    for i in range(25):
        recorder.sample(Sample("ping", i, {"rtt_ms": float(i)}))
    assert verify_run(path).sample_count == 20
    recorder.close()
    assert verify_run(path).sample_count == 25


def test_writing_after_close_is_an_error(tmp_path):
    recorder = SqliteRecorder(tmp_path / "run.sqlite")
    recorder.close()
    with pytest.raises(RuntimeError):
        recorder.event(Event(1, "late", {}))


@pytest.mark.skipif(shutil.which("ping") is None, reason="no system ping")
async def test_real_ping_run_is_controlled_and_stored(tmp_path):
    path = tmp_path / "runs" / "run.sqlite"
    recorder = SqliteRecorder(path)
    controller = Controller(DeviceManager([LocalHostProvider()]), recorder)
    config = ExperimentConfig((PingProbe("127.0.0.1", interval=0.05),))

    controller.submit(Command.PREPARE, config=config)
    await controller.wait_state(State.READY)
    controller.submit(Command.START_MEASUREMENT)
    await controller.wait_state(State.MEASURING)
    controller.submit(Command.MARK, label="checkpoint")
    controller.submit(Command.STOP_MEASUREMENT)
    await controller.wait_state(State.COMPLETED)
    recorder.close()

    check = verify_run(path)
    assert check.sealed and check.intact
    events, samples = read_run(path)
    assert [e.data["state"] for e in events if e.kind == "state"][-1] == "completed"
    assert any(e.kind == "mark" for e in events)
    rtts = [value for _, probe, metric, value in samples if metric == "rtt_ms"]
    assert rtts and all(v >= 0 for v in rtts)


def test_sealed_run_is_a_single_file_even_after_reading(tmp_path):
    path = tmp_path / "run.sqlite"
    recorder = SqliteRecorder(path)
    fill(recorder)
    recorder.close()
    read_run(path)
    verify_run(path)
    assert [p.name for p in tmp_path.iterdir()] == ["run.sqlite"]
