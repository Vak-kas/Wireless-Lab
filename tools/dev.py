#!/usr/bin/env python3
"""서버(127.0.0.1:8765)와 웹 개발 서버(127.0.0.1:5173)를 함께 실행한다. Ctrl+C로 둘 다 끝낸다.

사용: python tools/dev.py            개발 모드 (화면은 http://127.0.0.1:5173)
      python tools/dev.py --built    web/dist 를 서버가 직접 제공 (http://127.0.0.1:8765)
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))

from nrtrail.paths import ROOT, WEB, venv_bin  # noqa: E402

NPM = "npm.cmd" if sys.platform == "win32" else "npm"


def main() -> int:
    procs = [subprocess.Popen([venv_bin("python"), "-m", "nrtrail", *[a for a in sys.argv[1:] if a != "--built"]], cwd=ROOT)]
    if "--built" in sys.argv:
        print("화면: http://127.0.0.1:8765")
    else:
        procs.append(subprocess.Popen([NPM, "run", "dev"], cwd=WEB))
        print("화면: http://127.0.0.1:5173")
    try:
        for p in procs:
            p.wait()
    except KeyboardInterrupt:
        pass
    finally:
        for p in procs:
            p.terminate()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
