#!/usr/bin/env python3
"""macOS: Dock 과 메뉴 막대에 "Wireless Lab" 으로 뜨는 앱 꾸러미를 이 컴퓨터에 맞춰 만든다.

    python tools/make_app.py [--check]

만드는 것: sessions/run/Wireless Lab.app (저장소에 넣지 않는다)
    Contents/MacOS/Wireless Lab   tools/launcher/wireless_lab.c 를 clang 으로 만든 것. 파이썬을 안에서 돌린다
    Contents/Info.plist           이름, 아이콘, 폴더 접근을 물을 때 보일 문구
    Contents/Resources/AppIcon.icns

왜 저장소에 넣지 않는가: 실행 파일이 이 컴퓨터의 파이썬(위치, 버전)과 저장소 경로에 맞춰 만들어지기 때문이다.
저장소의 "Wireless Lab.app" 은 작은 실행기이고, 이 꾸러미가 있으면 그것을 열고 없으면 예전 방식으로 띄운다.

필요한 것: clang(Xcode 명령줄 도구). 없으면 만들지 않고 예전 방식이 그대로 쓰인다.
--check: 이미 만들어져 있고 재료가 바뀌지 않았으면 아무것도 하지 않는다(프로그램이 뜰 때마다 불러도 된다).
"""

from __future__ import annotations

import hashlib
import plistlib
import shutil
import subprocess
import sys
import sysconfig
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "tools" / "launcher" / "wireless_lab.c"
ICON = ROOT / "Wireless Lab.app" / "Contents" / "Resources" / "AppIcon.icns"
BUNDLE = ROOT / "sessions" / "run" / "Wireless Lab.app"
NAME = "Wireless Lab"
WHY = "Wireless Lab 의 프로그램과 저장한 신호 파일이 이 폴더에 있습니다."


def venv_python() -> Path:
    return ROOT / "venv" / "bin" / "python"


def stamp() -> str:
    """만든 재료의 지문: 소스, 파이썬 위치·버전, 저장소 경로. 바뀌면 다시 만든다."""
    parts = [SOURCE.read_bytes(), sys.base_prefix.encode(), sys.version.encode(), str(ROOT).encode(), Path(__file__).read_bytes()]
    return hashlib.sha256(b"\0".join(parts)).hexdigest()[:16]


def build() -> int:
    if sys.platform != "darwin":
        print("macOS 에서만 씁니다.")
        return 0
    clang = shutil.which("clang")
    if not clang:
        print("clang 이 없어 만들지 않습니다(예전 방식으로 뜹니다). Xcode 명령줄 도구를 설치하면 만들 수 있습니다.")
        return 1
    include = sysconfig.get_config_var("INCLUDEPY")
    # 파이썬 해석기 라이브러리: 프레임워크로 설치된 것은 <base_prefix>/Python, 그 밖에는 lib/libpythonX.Y.dylib
    version = sysconfig.get_config_var("LDVERSION")
    candidates = [Path(sys.base_prefix) / "Python", Path(sysconfig.get_config_var("LIBDIR") or "") / f"libpython{version}.dylib"]
    library = next((c for c in candidates if c.is_file()), None)
    if not include or library is None:
        print("이 파이썬의 해석기 라이브러리를 찾지 못해 안에 넣어 돌릴 수 없습니다(예전 방식으로 뜹니다).")
        return 1
    macos = BUNDLE / "Contents" / "MacOS"
    resources = BUNDLE / "Contents" / "Resources"
    shutil.rmtree(BUNDLE, ignore_errors=True)
    macos.mkdir(parents=True)
    resources.mkdir(parents=True)
    done = subprocess.run(
        [clang, "-O2", "-o", str(macos / NAME), str(SOURCE), f"-I{include}", str(library), f"-Wl,-rpath,{library.parent}", f'-DROOT="{ROOT}"', f'-DVENV_PYTHON="{venv_python()}"', f'-DAPP_PY="{ROOT / "tools" / "app.py"}"'],
        capture_output=True, text=True)
    if done.returncode != 0:
        print("만들지 못했습니다:\n" + done.stderr[-2000:])
        shutil.rmtree(BUNDLE, ignore_errors=True)
        return 1
    if ICON.exists():
        shutil.copy(ICON, resources / "AppIcon.icns")
    info = {
        "CFBundleName": NAME, "CFBundleDisplayName": NAME, "CFBundleExecutable": NAME,
        "CFBundleIdentifier": "local.wirelesslab.app", "CFBundleVersion": "0.1.0", "CFBundleShortVersionString": "0.1.0",
        "CFBundlePackageType": "APPL", "CFBundleIconFile": "AppIcon", "LSMinimumSystemVersion": "11.0", "NSHighResolutionCapable": True,
        # macOS 가 폴더 접근을 물을 때 보여 주는 까닭
        "NSDesktopFolderUsageDescription": WHY, "NSDocumentsFolderUsageDescription": WHY, "NSDownloadsFolderUsageDescription": WHY,
        "NSRemovableVolumesUsageDescription": WHY,
        "WirelessLabStamp": stamp(),
    }
    with (BUNDLE / "Contents" / "Info.plist").open("wb") as f:
        plistlib.dump(info, f)
    # 이 컴퓨터에서만 쓰는 서명(인증서 없이). 서명이 있어야 macOS 가 폴더 접근을 "물어볼" 수 있다
    signed = subprocess.run(["codesign", "--force", "--sign", "-", str(BUNDLE)], capture_output=True, text=True)
    if signed.returncode != 0:
        print("서명하지 못했습니다(그래도 써 볼 수는 있습니다):\n" + signed.stderr[-500:])
    print(f"만들었습니다: {BUNDLE.relative_to(ROOT)}")
    return 0


def fresh() -> bool:
    try:
        with (BUNDLE / "Contents" / "Info.plist").open("rb") as f:
            return plistlib.load(f).get("WirelessLabStamp") == stamp() and (BUNDLE / "Contents" / "MacOS" / NAME).exists()
    except (OSError, plistlib.InvalidFileException):
        return False


def main() -> int:
    if "--check" in sys.argv and fresh():
        return 0
    return build()


if __name__ == "__main__":
    raise SystemExit(main())
