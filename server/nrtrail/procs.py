"""이 도구가 띄운 프로세스(서버, MATLAB 엔진)를 남기지 않기 위한 기록과 정리.

왜 필요한가: 서버가 강제로 꺼지면 그 서버가 띄운 MATLAB 엔진이 부모 없이 남는다. 남은 MATLAB 이 USRP 수신기를 열어 둔 채라면
다음에 프로그램을 열었을 때 장비가 "사용 중"으로 나와 잡히지 않는다.

- 서버는 뜰 때 `sessions/run/<서버 pid>.json` 을 쓰고, MATLAB 엔진을 띄우면 그 pid 를 거기에 적는다.
- 끌 때: 먼저 정상 종료를 청하고, 정해진 시간 안에 안 끝나면 강제로 끝낸다.
- 켤 때: 지난 실행이 남긴 기록을 훑어, 주인 없는 서버와 MATLAB 을 끝낸다.
- 다른 프로그램을 잘못 끝내지 않도록, pid 의 명령줄이 기대한 것(nrtrail 서버, MATLAB)일 때만 끝낸다.
표준 라이브러리만 쓴다(실행기와 서버가 같이 쓴다).
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import time
from pathlib import Path
from typing import Any

from .paths import sessions_dir

SERVER_MARK = "-m nrtrail"
MATLAB_MARK = "MATLAB"


def run_dir() -> Path:
    d = sessions_dir() / "run"
    d.mkdir(parents=True, exist_ok=True)
    return d


def alive(pid: int) -> bool:
    if os.name == "nt":
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True).stdout
        return str(pid) in out
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    # 끝났지만 부모가 아직 거두지 않은 프로세스(좀비)는 신호를 받는 것처럼 보인다. 끝난 것으로 친다.
    try:
        state = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True, timeout=10).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return True
    return bool(state) and not state.startswith("Z")


def command_of(pid: int) -> str:
    """pid 의 명령줄(모르면 빈 문자열)."""
    try:
        if os.name == "nt":
            # wmic 는 최신 Windows 에서 빠졌다. PowerShell 로 묻는다.
            return subprocess.run(["powershell", "-NoProfile", "-Command",
                                   f"(Get-CimInstance Win32_Process -Filter 'ProcessId={pid}').CommandLine"],
                                  capture_output=True, text=True, timeout=15).stdout
        return subprocess.run(["ps", "-o", "command=", "-p", str(pid)], capture_output=True, text=True, timeout=10).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def parent_of(pid: int) -> int | None:
    if os.name == "nt":
        return None
    try:
        out = subprocess.run(["ps", "-o", "ppid=", "-p", str(pid)], capture_output=True, text=True, timeout=10).stdout.strip()
        return int(out) if out else None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def stop_pid(pid: int, expect: str, grace_s: float = 5.0) -> str:
    """pid 가 기대한 프로세스면 끝낸다. "gone"(이미 없음) / "skipped"(다른 프로세스) / "stopped"(정상 종료) / "killed"(강제 종료)."""
    if not pid or not alive(pid):
        return "gone"
    if expect not in command_of(pid):
        return "skipped"                      # pid 가 다른 프로그램에 다시 쓰였을 수 있다. 건드리지 않는다.
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        return "gone"
    deadline = time.monotonic() + grace_s
    while time.monotonic() < deadline:
        if not alive(pid):
            return "stopped"
        time.sleep(0.2)
    try:
        os.kill(pid, getattr(signal, "SIGKILL", signal.SIGTERM))
    except OSError:
        return "stopped"
    return "killed"


def record(**fields: Any) -> None:
    """이 서버의 실행 기록을 쓰거나 고친다."""
    path = run_dir() / f"{os.getpid()}.json"
    data: dict[str, Any] = {"server_pid": os.getpid(), "started_at": time.time()}
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            pass
    data.update(fields)
    path.write_text(json.dumps(data), encoding="utf-8")


def add_matlab(pid: int) -> None:
    """이 서버가 띄운 MATLAB 하나를 기록에 더한다(장비마다 하나씩 띄울 수 있어 여러 개일 수 있다)."""
    path = run_dir() / f"{os.getpid()}.json"
    try:
        have = list(json.loads(path.read_text(encoding="utf-8")).get("matlab_pids") or []) if path.exists() else []
    except ValueError:
        have = []
    record(matlab_pids=sorted({*have, int(pid)}))


def drop_matlab(pid: int) -> None:
    """끝낸 MATLAB 을 기록에서 뺀다."""
    path = run_dir() / f"{os.getpid()}.json"
    try:
        have = list(json.loads(path.read_text(encoding="utf-8")).get("matlab_pids") or []) if path.exists() else []
    except ValueError:
        have = []
    record(matlab_pids=[p for p in have if p != int(pid)])


def forget() -> None:
    (run_dir() / f"{os.getpid()}.json").unlink(missing_ok=True)


def stop_server(server_pid: int, grace_s: float = 8.0) -> list[str]:
    """서버와 그 서버가 띄운 MATLAB 을 끝낸다. 무엇을 했는지 돌려준다."""
    did: list[str] = []
    path = run_dir() / f"{server_pid}.json"
    matlab_pids: list[int] = []
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            matlab_pids = sorted({int(p) for p in [data.get("matlab_pid") or 0, *(data.get("matlab_pids") or [])] if int(p) > 0})
        except (ValueError, TypeError):
            matlab_pids = []
    r = stop_pid(server_pid, SERVER_MARK, grace_s)
    if r in ("stopped", "killed"):
        did.append(f"서버 {server_pid}: {r}")
    for matlab_pid in matlab_pids:                      # 서버가 정상 종료했다면 이미 없다
        r = stop_pid(matlab_pid, MATLAB_MARK, 3.0)
        if r in ("stopped", "killed"):
            did.append(f"MATLAB {matlab_pid}: {r}")
    if not alive(server_pid):
        path.unlink(missing_ok=True)
    return did


def sweep_orphans(marks: tuple[str, ...]) -> list[str]:
    """기록에 없이 남은 것까지 치운다: 부모가 사라졌는데(ppid 1) 아직 도는, 명령줄에 marks 가운데 하나가 든 프로세스.

    기록(sessions/run)은 서버가 정상으로 떴을 때만 남는다. 기록이 지워졌거나 옛 판이 띄운 서버, 서버 없이 남은 장비 프로그램(uhdio)은
    기록으로는 찾을 수 없다. 그런 것이 USRP 를 잡고 있으면 새로 연 프로그램에서 장비가 잡히지 않는다.
    부모가 살아 있는 것(터미널에서 직접 띄운 서버, 지금 도는 실행기의 서버)은 건드리지 않는다.
    """
    if os.name == "nt":
        return []
    try:
        rows = subprocess.run(["ps", "-axo", "pid=,ppid=,command="], capture_output=True, text=True, timeout=15).stdout.splitlines()
    except (OSError, subprocess.SubprocessError):
        return []
    did: list[str] = []
    for row in rows:
        parts = row.split(None, 2)
        if len(parts) < 3 or not parts[0].isdigit() or parts[1] != "1":
            continue
        pid, command = int(parts[0]), parts[2]
        mark = next((m for m in marks if m in command), None)
        if mark is None or pid == os.getpid():
            continue
        did.append(f"주인 없는 프로세스 {pid}: {stop_pid(pid, mark)}")
    return did


def sweep(keep_parent: int | None = None) -> list[str]:
    """지난 실행이 남긴 것을 치운다: 죽은 서버의 MATLAB, 그리고 부모가 사라진(주인 없는) 서버.

    keep_parent 가 부모인 서버(지금 실행기가 방금 띄운 것)와, 다른 실행기가 살아서 돌리고 있는 서버는 건드리지 않는다.
    """
    did: list[str] = []
    for path in sorted(run_dir().glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            server_pid = int(data.get("server_pid") or 0)
        except (ValueError, TypeError):
            path.unlink(missing_ok=True)
            continue
        if server_pid == os.getpid():
            continue
        if alive(server_pid) and SERVER_MARK in command_of(server_pid):
            parent = parent_of(server_pid)
            if parent is not None and parent != 1:
                continue                      # 살아 있는 실행기(또는 터미널)가 돌리고 있다
            if keep_parent is not None and parent == keep_parent:
                continue
        did += stop_server(server_pid)
        path.unlink(missing_ok=True)
    return did
