"""환경 점검. tools/doctor.py와 서버의 /api/doctor가 같이 쓴다. 표준 라이브러리만 쓴다.

아무것도 설치하거나 바꾸지 않는다. 읽어서 보고만 한다.
"""

from __future__ import annotations

import importlib.util
import json
import platform
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass

from .paths import ROOT, find_matlab

REQUIRED_TOOLBOXES = ["5G Toolbox", "Communications Toolbox", "Signal Processing Toolbox"]


@dataclass
class Check:
    id: str
    label: str
    status: str  # ok | warn | missing
    detail: str
    fix: str = ""


def _run(cmd: list[str], timeout: float = 20) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout + p.stderr).strip()
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, str(e)


def check_python() -> Check:
    v = sys.version_info
    ok = v >= (3, 10)
    return Check("python", "Python", "ok" if ok else "missing", platform.python_version(),
                 "" if ok else "Python 3.10 이상을 설치하세요.")


def check_packages() -> Check:
    need = ["fastapi", "uvicorn", "pydantic", "numpy", "pycrate_asn1dir"]
    missing = [m for m in need if importlib.util.find_spec(m) is None]
    if missing:
        return Check("python_packages", "Python 패키지", "missing", "없음: " + ", ".join(missing),
                     "프로젝트 가상환경에서 pip install -e '.[dev]' 를 실행하세요.")
    return Check("python_packages", "Python 패키지", "ok", "필수 패키지 설치됨")


def check_matlab(quick: bool) -> list[Check]:
    exe = find_matlab()
    if not exe:
        return [Check("matlab", "MATLAB", "missing", "찾지 못함",
                      "MATLAB을 설치하거나 환경 변수 NRTRAIL_MATLAB에 실행 파일 경로를 넣으세요. "
                      "없어도 연습 모드(저장된 결과 재생)는 동작합니다.")]
    out = [Check("matlab", "MATLAB", "ok", exe)]
    if quick:
        out.append(Check("matlab_toolboxes", "MATLAB 툴박스", "warn", "빠른 점검에서는 확인하지 않음"))
    else:
        code, text = _run([exe, "-batch", "v=ver; disp(['NRTRAIL_VER|' version]); disp(['NRTRAIL_TB|' strjoin({v.Name},'|')])"],
                          timeout=180)
        line = next((ln for ln in text.splitlines() if ln.startswith("NRTRAIL_TB|")), "")
        ver = next((ln.split("|", 1)[1] for ln in text.splitlines() if ln.startswith("NRTRAIL_VER|")), "")
        if code != 0 or not line:
            out.append(Check("matlab_batch", "matlab -batch 실행", "missing", text[-300:],
                             "터미널에서 matlab -batch \"ver\" 가 되는지, 라이선스가 유효한지 확인하세요."))
        else:
            out[0].detail = f"{ver} · {exe}"
            have = line.split("|")[1:]
            lack = [t for t in REQUIRED_TOOLBOXES if t not in have]
            out.append(Check("matlab_toolboxes", "MATLAB 툴박스", "missing" if lack else "ok",
                             ("없음: " + ", ".join(lack)) if lack else ", ".join(REQUIRED_TOOLBOXES),
                             "MATLAB 애드온 관리자에서 빠진 툴박스를 설치하세요." if lack else ""))
    has_engine = importlib.util.find_spec("matlab") is not None and importlib.util.find_spec("matlab.engine") is not None
    out.append(Check("matlab_engine", "MATLAB Engine for Python", "ok" if has_engine else "warn",
                     "설치됨" if has_engine else "없음 (matlab -batch로 대신 실행, 단계마다 기동 시간이 더 걸림)",
                     "" if has_engine else "가상환경에서 pip install matlabengine==<MATLAB 릴리스에 맞는 버전>"))
    return out


def check_node() -> Check:
    node = shutil.which("node")
    if not node:
        return Check("node", "Node.js", "missing", "찾지 못함", "화면을 빌드하려면 Node.js 20 이상을 설치하세요.")
    _, ver = _run([node, "--version"])
    return Check("node", "Node.js", "ok", ver)


def check_soapy() -> list[Check]:
    has_mod = importlib.util.find_spec("SoapySDR") is not None
    util = shutil.which("SoapySDRUtil")
    if not has_mod:
        return [Check("soapysdr", "SoapySDR (Python)", "missing", "모듈 없음",
                      "실제 SDR 장비를 쓰려면 SoapySDR과 장비 모듈(SoapyUHD, SoapyHackRF, SoapyPlutoSDR 등)을 설치하세요. "
                      "파일 재생과 연습 모드는 없어도 동작합니다. 설치는 사람이 직접 해야 합니다.")]
    out = [Check("soapysdr", "SoapySDR (Python)", "ok", "모듈 있음")]
    if util:
        _, text = _run([util, "--find"], timeout=30)
        n = text.count("driver")
        out.append(Check("sdr_devices", "SDR 장비", "ok" if n else "warn", f"{n}대 인식" if n else "인식된 장비 없음",
                         "" if n else "장비 연결과 USB 케이블, 전원을 확인하세요."))
    return out


def check_adb() -> Check:
    adb = shutil.which("adb")
    if not adb:
        return Check("adb", "adb (휴대폰 연동)", "warn", "찾지 못함",
                     "휴대폰 연동을 쓰려면 Android platform-tools를 설치하세요. 선택 기능입니다.")
    _, text = _run([adb, "devices"], timeout=10)
    devs = [ln for ln in text.splitlines()[1:] if "\tdevice" in ln]
    return Check("adb", "adb (휴대폰 연동)", "ok", f"설치됨 · 연결된 휴대폰 {len(devs)}대",
                 "" if devs else "휴대폰에서 USB 디버깅을 켜고 연결하면 셀 정보를 가져올 수 있습니다.")


def check_disk() -> Check:
    free_gb = shutil.disk_usage(ROOT).free / 1e9
    return Check("disk", "남은 디스크", "ok" if free_gb > 10 else "warn", f"{free_gb:.0f} GB",
                 "" if free_gb > 10 else "긴 IQ 기록은 수 GB가 필요합니다. 공간을 확보하세요.")


def run_checks(quick: bool = False) -> dict:
    checks: list[Check] = [
        Check("os", "운영체제", "ok", f"{platform.system()} {platform.release()} ({platform.machine()})"),
        check_python(),
        check_packages(),
        *check_matlab(quick),
        check_node(),
        *check_soapy(),
        check_adb(),
        check_disk(),
    ]
    matlab_ok = all(c.status == "ok" for c in checks if c.id in ("matlab", "matlab_toolboxes", "matlab_batch"))
    return {
        "checks": [asdict(c) for c in checks],
        "engines": {"mock": True, "matlab": (find_matlab() is not None) if quick else matlab_ok},
    }


def format_text(report: dict) -> str:
    mark = {"ok": "[ OK ]", "warn": "[주의]", "missing": "[없음]"}
    lines = ["nrtrail 환경 점검", ""]
    for c in report["checks"]:
        lines.append(f"{mark[c['status']]} {c['label']}: {c['detail']}")
        if c["fix"]:
            lines.append(f"        → {c['fix']}")
    lines.append("")
    lines.append("사용 가능한 엔진: " + ", ".join(k for k, v in report["engines"].items() if v))
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    report = run_checks(quick="--quick" in args)
    print(json.dumps(report, ensure_ascii=False, indent=2) if "--json" in args else format_text(report))
    return 0
