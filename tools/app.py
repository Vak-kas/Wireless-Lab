#!/usr/bin/env python3
"""nrtrail 을 프로그램처럼 실행한다: 서버를 띄우고, 창을 열고, 창을 닫으면 전부 끈다.

    python tools/app.py              창을 연다 (macOS 는 "Wireless Lab.app" 을 더블클릭해도 같다)
    python tools/app.py --oai        OAI 기지국 시뮬레이터도 처음부터 켜 둔다(평소에는 켜지 않는다)
    python tools/app.py --self-test  창 없이 켜고 끄는 동작만 확인한다

켜는 것
  1. 로컬 서버 (127.0.0.1, 빈 포트). 화면이 빌드돼 있지 않으면 먼저 빌드한다.
  2. --oai 를 줬을 때만: OAI NTN RF 시뮬레이터 gNB (testbed/oai-ntn 과 빌드된 이미지가 있어야 한다).
     Docker 가 꺼져 있으면 켠다. 전파를 내보내지 않는 소프트웨어 시뮬레이터다.
     평소에는 켜지 않는다 — 시뮬레이션 화면에서 "새로 기록"을 누를 때 서버가 그때 켜고, 기록이 끝나면 끈다.
끄는 것 (창의 X, 종료 메뉴, Ctrl+C 어느 것이든)
  서버, 이 실행기가 띄운 OAI 컨테이너, 그리고 이 실행기가 켠 경우에만 Docker.
"""

from __future__ import annotations

import atexit
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))

from nrtrail import procs  # noqa: E402
from nrtrail.paths import ROOT, WEB, WEB_DIST, sessions_dir, venv_bin  # noqa: E402

HOST = "127.0.0.1"
OAI_DIR = ROOT / "testbed" / "oai-ntn"
OAI_IMAGE = "nrtrail-testbed/oai-ntn-rfsim"
NPM = "npm.cmd" if sys.platform == "win32" else "npm"


def log(msg: str) -> None:
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    try:
        path = sessions_dir() / "launcher.log"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def free_port(preferred: int = 8765) -> int:
    for port in (preferred, 0):
        with socket.socket() as s:
            # 방금 끈 서버가 쓰던 포트를 바로 다시 쓸 수 있게 한다. 이것이 없으면 다시 켤 때마다 다른 포트로 떠서
            # 브라우저가 다른 사이트로 본다(브라우저에 둔 설정이 사라진 것처럼 보인다).
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind((HOST, port))
                return int(s.getsockname()[1])
            except OSError:
                continue
    raise RuntimeError("빈 포트를 찾지 못했습니다")


def healthy(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://{HOST}:{port}/api/health", timeout=1) as r:
            return bool(r.status == 200)
    except OSError:
        return False


def run_quiet(cmd: list[str], cwd: Path | None = None, timeout: float = 120) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout + p.stderr).strip()
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, str(e)


STATE = "launcher-state.json"


def write_state(state: dict[str, object]) -> None:
    path = sessions_dir() / STATE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state), encoding="utf-8")


def cleanup(server_pid: int | None, oai: bool, docker_started: bool) -> None:
    """서버, OAI 컨테이너, (이 실행기가 켰다면) Docker 를 끈다. 실행기와 뒷정리 프로세스가 같이 쓴다."""
    if server_pid:
        for line in procs.stop_server(server_pid):       # 정상 종료를 청하고, 안 끝나면 강제로. 그 서버의 MATLAB 까지.
            log("정리: " + line)
    docker = shutil.which("docker")
    if oai and docker:
        run_quiet([docker, "compose", "--profile", "leo", "--profile", "geo", "--profile", "leo-ue", "--profile", "geo-ue", "down"],
                  cwd=OAI_DIR, timeout=120)
    if docker_started and sys.platform == "darwin":
        run_quiet(["osascript", "-e", 'quit app "Docker"'], timeout=30)


def alive(pid: int) -> bool:
    """프로세스가 살아 있는지. Windows 에서 os.kill(pid, 0) 은 프로세스를 죽이므로 따로 처리한다."""
    if os.name == "nt":
        import ctypes

        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        code = ctypes.c_ulong()
        ok = ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
        ctypes.windll.kernel32.CloseHandle(handle)
        return bool(ok) and code.value == 259  # STILL_ACTIVE
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def reaper(parent_pid: int) -> int:
    """실행기가 정상 종료 절차 없이 사라졌을 때(강제 종료, Cmd+Q, 충돌) 남은 것을 끈다."""
    while alive(parent_pid):
        time.sleep(1)
    try:
        state = json.loads((sessions_dir() / STATE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 0
    if state.get("pid") == parent_pid and not state.get("stopped"):
        cleanup(state.get("server_pid"), bool(state.get("oai")), bool(state.get("docker_started")))
        write_state({**state, "stopped": True})
        log("실행기가 갑자기 끝나서 뒷정리 프로세스가 나머지를 껐습니다")
    return 0


class Launcher:
    def __init__(self, with_oai: bool) -> None:
        self.with_oai = with_oai
        self.port = 0
        self.server: subprocess.Popen[bytes] | None = None
        self.oai_started = False
        self.docker_started = False
        self.oai_note = ""
        self._stopped = False

    def save_state(self, stopped: bool = False) -> None:
        write_state({"pid": os.getpid(), "server_pid": self.server.pid if self.server else None, "port": self.port,
                     "oai": self.oai_started, "docker_started": self.docker_started, "stopped": stopped})

    # ---------- 서버 ----------
    def start_server(self) -> None:
        if not (WEB_DIST / "index.html").exists():
            log("화면이 빌드돼 있지 않아 먼저 빌드합니다 (처음 한 번, 1분쯤 걸립니다)")
            if not (WEB / "node_modules").exists():
                run_quiet([NPM, "install"], cwd=WEB, timeout=900)
            code, out = run_quiet([NPM, "run", "build"], cwd=WEB, timeout=600)
            if code != 0:
                raise RuntimeError("화면 빌드 실패: " + out[-400:])
        for line in procs.sweep():                        # 지난 실행이 남긴 서버·MATLAB 을 먼저 치운다
            log("지난 실행의 남은 것 정리: " + line)
        # 기록에 없이 남은 서버와 장비 프로그램(uhdio)도 치운다: 이런 것이 USRP 를 잡고 있으면 장비가 잡히지 않는다
        for line in procs.sweep_orphans((procs.SERVER_MARK + " --port", str(ROOT / "native" / "uhdio" / "build" / "uhdio"))):
            log("지난 실행의 남은 것 정리: " + line)
        self.port = free_port()
        self.server = subprocess.Popen([venv_bin("python"), "-m", "nrtrail", "--port", str(self.port)], cwd=ROOT)
        self.save_state()
        # 뒷정리 프로세스: 실행기가 어떤 식으로 끝나든 서버와 컨테이너가 남지 않게 한다.
        detach: dict[str, object] = ({"creationflags": 0x00000008 | 0x00000200} if os.name == "nt"  # DETACHED | NEW_GROUP
                                     else {"start_new_session": True})
        subprocess.Popen([venv_bin("python"), str(Path(__file__).resolve()), "--reaper", str(os.getpid())], cwd=ROOT,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **detach)  # type: ignore[call-overload]
        for _ in range(120):
            if healthy(self.port):
                log(f"서버 준비됨: http://{HOST}:{self.port}")
                return
            if self.server.poll() is not None:
                raise RuntimeError("서버가 시작하다 멈췄습니다. sessions/launcher.log 와 터미널 출력을 확인하세요.")
            time.sleep(0.5)
        raise RuntimeError("서버가 60초 안에 뜨지 않았습니다")

    # ---------- OAI 테스트베드 (있을 때만) ----------
    def start_oai(self) -> None:
        if not self.with_oai:
            self.oai_note = "OAI: 켜지 않음(필요할 때 화면에서 켠다. 처음부터 켜 두려면 --oai)"
            return
        if not (OAI_DIR / "docker-compose.yml").exists():
            self.oai_note = "OAI: 테스트베드 파일이 없어 건너뜀"
            return
        docker = shutil.which("docker")
        if not docker:
            self.oai_note = "OAI: Docker 가 설치돼 있지 않아 건너뜀"
            return
        if run_quiet([docker, "info"], timeout=15)[0] != 0:
            if sys.platform != "darwin":
                self.oai_note = "OAI: Docker 가 꺼져 있어 건너뜀"
                return
            log("Docker 를 켭니다")
            run_quiet(["open", "-g", "-a", "Docker"], timeout=20)
            self.docker_started = True
            self.save_state()
            for _ in range(60):
                if self._stopped:
                    return
                if run_quiet([docker, "info"], timeout=10)[0] == 0:
                    break
                time.sleep(2)
            else:
                self.oai_note = "OAI: Docker 가 2분 안에 켜지지 않아 건너뜀"
                return
        if not run_quiet([docker, "images", "-q", OAI_IMAGE], timeout=20)[1]:
            self.oai_note = "OAI: 이미지가 아직 빌드되지 않아 건너뜀 (docs/oai-ntn-testbed.md 의 빌드 명령을 한 번 실행)"
            return
        code, out = run_quiet([docker, "compose", "--profile", "leo", "up", "-d"], cwd=OAI_DIR, timeout=180)
        if code == 0:
            self.oai_started = True
            self.save_state()
            self.oai_note = "OAI: 저궤도 NTN gNB 실행 중"
        else:
            self.oai_note = "OAI: 시작 실패 — " + out[-200:]

    # ---------- 종료 ----------
    def stop(self) -> None:
        if self._stopped:
            return
        self._stopped = True
        log("끄는 중…")
        self.save_state(stopped=True)
        cleanup(self.server.pid if self.server else None, self.oai_started, self.docker_started)
        if self.server:
            try:
                self.server.wait(timeout=2)
            except subprocess.TimeoutExpired:
                pass
        log("모두 껐습니다")


APP_NAME = "Wireless Lab"


def dress_as_app() -> None:
    """macOS: 독과 메뉴 막대에 "Python" 대신 이 앱의 이름과 아이콘이 보이게 한다. 안 돼도 그대로 간다."""
    if sys.platform != "darwin":
        return
    try:
        from AppKit import NSApplication, NSBundle, NSImage

        info = NSBundle.mainBundle().localizedInfoDictionary() or NSBundle.mainBundle().infoDictionary()
        if info is not None:
            info["CFBundleName"] = APP_NAME
        icon = NSImage.alloc().initWithContentsOfFile_(str(ROOT / "tools" / "icon" / "wireless-lab.png"))
        if icon is not None:
            NSApplication.sharedApplication().setApplicationIconImage_(icon)
    except Exception:  # noqa: BLE001, S110 — 꾸미기에 실패해도 프로그램은 뜬다
        pass


def main() -> int:
    args = sys.argv[1:]
    if "--reaper" in args:
        return reaper(int(args[args.index("--reaper") + 1]))
    launcher = Launcher(with_oai="--oai" in args)
    atexit.register(launcher.stop)
    for sig in (signal.SIGINT, signal.SIGTERM, *([signal.SIGHUP] if hasattr(signal, "SIGHUP") else [])):
        signal.signal(sig, lambda *_: sys.exit(0))

    try:
        launcher.start_server()
    except RuntimeError as e:
        log(f"시작 실패: {e}")
        return 1
    url = f"http://{HOST}:{launcher.port}"

    def oai_job() -> None:
        launcher.start_oai()
        log(launcher.oai_note)

    oai_thread = threading.Thread(target=oai_job, daemon=True)
    oai_thread.start()

    if "--self-test" in args:
        oai_thread.join(timeout=200)
        ok = healthy(launcher.port)
        log(f"자체 점검: 서버 {'정상' if ok else '응답 없음'} · {launcher.oai_note}")
        return 0 if ok else 1

    try:
        import webview  # pywebview: 화면을 독립된 창으로 연다
    except ImportError:
        import webbrowser

        log("창 라이브러리(pywebview)가 없어 기본 브라우저로 엽니다. 끝내려면 이 창에서 Ctrl+C.")
        webbrowser.open(url)
        while launcher.server and launcher.server.poll() is None:
            time.sleep(1)
        return 0

    dress_as_app()
    webview.create_window(APP_NAME, url, width=1320, height=900, min_size=(380, 600))
    webview.start()  # 창을 닫으면 돌아온다 → atexit 가 전부 끈다
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
