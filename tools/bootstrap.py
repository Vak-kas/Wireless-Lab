#!/usr/bin/env python3
"""처음 한 번: 프로젝트 안에 가상환경을 만들고 필요한 파이썬 패키지를 깐다. 실행기(nrtrail.command 등)가 가상환경이 없을 때 부른다.

    python3 tools/bootstrap.py            가상환경 만들기 + pip 설치 (+ 화면이 아직 안 지어졌고 npm 이 있으면 화면 짓기)
    python3 tools/bootstrap.py --dry-run  무엇을 할지만 보여 준다

- 프로젝트 폴더 안(venv/, web/node_modules, web/dist)에만 쓴다. 시스템에 까는 것은 없다.
- pip 로 깔 수 없는 것은 여기서 하지 않는다: MATLAB, Node.js, Docker, SoapySDR(파이썬 패키지로 배포되지 않는다. 운영체제의 패키지 관리자로 깐다).
  USRP 는 MATLAB 의 USRP 지원 패키지로 연결하므로 SoapySDR 이 없어도 된다.
- 표준 라이브러리만 쓴다(가상환경이 생기기 전에 시스템 파이썬으로 돌기 때문).
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MIN_PY = (3, 10)


def venv_python() -> Path:
    return ROOT / "venv" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")


def plan() -> list[tuple[str, list[str], Path]]:
    """할 일 목록: (설명, 명령, 실행할 폴더). 이미 된 것은 뺀다."""
    steps: list[tuple[str, list[str], Path]] = []
    py = venv_python()
    if not py.exists():
        steps.append(("가상환경 만들기 (venv/)", [sys.executable, "-m", "venv", str(ROOT / "venv")], ROOT))
    steps.append(("파이썬 패키지 설치 (pip)", [str(py), "-m", "pip", "install", "--disable-pip-version-check", "-q", "-e", ".[app]"], ROOT))
    web = ROOT / "web"
    if not (web / "dist" / "index.html").exists():
        npm = shutil.which("npm")
        if npm:
            if not (web / "node_modules").exists():
                steps.append(("화면 의존성 설치 (npm install)", [npm, "install", "--no-fund", "--no-audit"], web))
            steps.append(("화면 짓기 (npm run build)", [npm, "run", "build"], web))
    return steps


def main() -> int:
    if sys.version_info < MIN_PY:
        print(f"파이썬 {MIN_PY[0]}.{MIN_PY[1]} 이상이 필요합니다(지금: {sys.version.split()[0]}).")
        return 1
    steps = plan()
    if "--dry-run" in sys.argv:
        for label, cmd, cwd in steps:
            print(f"- {label}: {' '.join(cmd)}  ({cwd})")
        return 0
    for label, cmd, cwd in steps:
        print(f"[설치] {label} …", flush=True)
        if subprocess.run(cmd, cwd=cwd).returncode != 0:
            print(f"실패했습니다: {label}")
            return 1
    if not (ROOT / "web" / "dist" / "index.html").exists():
        print("화면이 아직 지어지지 않았습니다. Node.js 20 이상을 설치한 뒤 다시 실행하세요.")
        return 1
    print("설치가 끝났습니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
