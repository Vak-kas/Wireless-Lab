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


def test_orphans_without_a_record_are_swept_only_when_their_parent_is_gone(monkeypatch):
    """기록에 없어도, 부모가 사라진(ppid 1) 서버·장비 프로그램은 치운다. 부모가 살아 있는 것과 무관한 것은 건드리지 않는다."""
    rows = "\n".join([
        "  100     1 /opt/python -m nrtrail --port 52500",
        "  101   900 /opt/python -m nrtrail --port 8765",          # 부모가 살아 있다
        "  102     1 /repo/native/uhdio/build/uhdio",
        "  103     1 /usr/bin/some-other-daemon --port 1",
    ])
    monkeypatch.setattr(procs.subprocess, "run", lambda *a, **k: type("P", (), {"stdout": rows})())
    stopped = []
    monkeypatch.setattr(procs, "stop_pid", lambda pid, mark: stopped.append((pid, mark)) or "stopped")
    out = procs.sweep_orphans(("-m nrtrail --port", "/repo/native/uhdio/build/uhdio"))
    assert stopped == [(100, "-m nrtrail --port"), (102, "/repo/native/uhdio/build/uhdio")] and len(out) == 2


def test_stop_all_ends_every_matching_process_whatever_its_parent(monkeypatch):
    """새로 고침: 장비 프로그램은 부모가 살아 있어도(다른 창이 띄운 것) 모두 끝낸다. 무관한 프로세스와 나 자신은 뺀다."""
    rows = "\n".join(["  200 /repo/native/uhdio/build/uhdio", "  201 /usr/bin/other", f"  {os.getpid()} /repo/native/uhdio/build/uhdio --me",
                      "  202 /repo/native/uhdio/build/uhdio"])
    monkeypatch.setattr(procs.subprocess, "run", lambda *a, **k: type("P", (), {"stdout": rows})())
    stopped = []
    monkeypatch.setattr(procs, "stop_pid", lambda pid, mark, grace_s=5.0: stopped.append(pid) or "stopped")
    assert len(procs.stop_all("/repo/native/uhdio/build/uhdio")) == 2 and stopped == [200, 202]
