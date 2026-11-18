"""남은 프로세스 정리: 기대한 프로세스만, 정상 종료 → 안 되면 강제로."""
import json
import os
import signal
import subprocess
import sys
import time

import pytest
from nrtrail import procs

pytestmark = pytest.mark.skipif(os.name == "nt", reason="POSIX 신호로 시험한다")


@pytest.fixture(autouse=True)
def rundir(tmp_path, monkeypatch):
    monkeypatch.setattr(procs, "sessions_dir", lambda: tmp_path)
    return tmp_path


def spawn(code: str, *args: str) -> subprocess.Popen:
    p = subprocess.Popen([sys.executable, "-c", code, *args])
    time.sleep(0.4)
    return p


POLITE = "import time; time.sleep(60)"
STUBBORN = "import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(60)"


def test_a_polite_process_is_stopped_and_a_stubborn_one_is_killed():
    a, b = spawn(POLITE, "MARK-A"), spawn(STUBBORN, "MARK-B")
    try:
        assert procs.stop_pid(a.pid, "MARK-A", grace_s=3) == "stopped"
        t0 = time.monotonic()
        assert procs.stop_pid(b.pid, "MARK-B", grace_s=1) == "killed" and time.monotonic() - t0 < 4
        a.wait(3), b.wait(3)
        assert not procs.alive(a.pid) and not procs.alive(b.pid)
        assert procs.stop_pid(a.pid, "MARK-A") == "gone"
    finally:
        for p in (a, b):
            p.poll() is None and p.kill()


def test_a_process_that_is_not_what_we_expect_is_left_alone():
    other = spawn(POLITE, "SOMETHING-ELSE")
    try:
        assert procs.stop_pid(other.pid, "MATLAB") == "skipped" and procs.alive(other.pid)      # pid 가 다른 프로그램에 다시 쓰인 경우
    finally:
        other.kill()


def test_sweep_cleans_up_what_a_dead_server_left_behind(rundir):
    leftover = spawn(STUBBORN, "fake-MATLAB-engine")                              # 죽은 서버가 남긴 MATLAB 역할
    mine = spawn(POLITE, "fake-MATLAB-of-live-server")
    (rundir / "run").mkdir(exist_ok=True)
    (rundir / "run" / "999999.json").write_text(json.dumps({"server_pid": 999999, "matlab_pid": leftover.pid}))
    (rundir / "run" / "broken.json").write_text("not json")
    live = spawn(POLITE, "-m", "nrtrail", "--port", "1")                          # 부모(이 테스트)가 살아 있는 서버 역할
    (rundir / "run" / f"{live.pid}.json").write_text(json.dumps({"server_pid": live.pid, "matlab_pid": mine.pid}))
    try:
        did = procs.sweep()
        leftover.wait(5)
        assert any("MATLAB" in line and "killed" in line for line in did)
        assert not procs.alive(leftover.pid)
        assert procs.alive(live.pid) and procs.alive(mine.pid)                    # 누가 돌리고 있는 서버와 그 MATLAB 은 건드리지 않는다
        assert sorted(p.name for p in (rundir / "run").iterdir()) == [f"{live.pid}.json"]
    finally:
        for p in (leftover, mine, live):
            p.poll() is None and p.kill()


def test_record_and_forget(rundir):
    procs.record(port=1234)
    procs.record(matlab_pid=42)
    data = json.loads((rundir / "run" / f"{os.getpid()}.json").read_text())
    assert data["port"] == 1234 and data["matlab_pid"] == 42 and data["server_pid"] == os.getpid()
    procs.forget()
    assert not list((rundir / "run").iterdir())
    assert signal.SIGTERM                                                         # (가져오기만 쓰는 것을 막는 줄)
