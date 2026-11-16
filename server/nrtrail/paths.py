"""프로젝트 경로와 외부 프로그램 위치 찾기. 표준 라이브러리만 쓴다(tools/에서도 불러 쓰기 때문)."""

from __future__ import annotations

import glob
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PIPELINE = ROOT / "pipeline"
DEVICES = ROOT / "devices"
MATLAB_DIR = ROOT / "matlab"
WEB = ROOT / "web"
WEB_DIST = WEB / "dist"
GOLDEN = PIPELINE / "golden"


def sessions_dir() -> Path:
    """실행 데이터 폴더. 테스트는 NRTRAIL_SESSIONS로 바꿔 쓴다."""
    return Path(os.environ.get("NRTRAIL_SESSIONS", ROOT / "sessions"))


def venv_bin(name: str) -> str:
    """프로젝트 가상환경 안의 실행 파일 경로 (Windows는 Scripts, 그 외는 bin)."""
    sub, ext = ("Scripts", ".exe") if os.name == "nt" else ("bin", "")
    return str(ROOT / "venv" / sub / (name + ext))


def find_matlab() -> str | None:
    """MATLAB 실행 파일. NRTRAIL_MATLAB > PATH > 운영체제별 기본 설치 위치(가장 최신 버전)."""
    env = os.environ.get("NRTRAIL_MATLAB")
    if env and Path(env).exists():
        return env
    on_path = shutil.which("matlab")
    if on_path:
        return on_path
    if sys.platform == "darwin":
        pattern = "/Applications/MATLAB_R*.app/bin/matlab"
    elif os.name == "nt":
        pattern = r"C:\Program Files\MATLAB\R*\bin\matlab.exe"
    else:
        pattern = "/usr/local/MATLAB/R*/bin/matlab"
    found = sorted(glob.glob(pattern))
    return found[-1] if found else None
