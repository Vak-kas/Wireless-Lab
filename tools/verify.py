#!/usr/bin/env python3
"""전체 검증: 린트, 타입 검사, 테스트(MATLAB 가능하면 포함), Playwright.

사용: python tools/verify.py            전부
      python tools/verify.py --no-matlab MATLAB 테스트 건너뛰기
      python tools/verify.py --no-e2e    Playwright 건너뛰기
      python tools/verify.py --only py   한 묶음만 (py | web | matlab | e2e)
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))

from nrtrail.paths import MATLAB_DIR, ROOT, WEB, find_matlab, venv_bin  # noqa: E402

NPM = "npm.cmd" if sys.platform == "win32" else "npm"
PY = venv_bin("python")


def steps(args: list[str]) -> list[tuple[str, str, list[str], Path]]:
    only = args[args.index("--only") + 1] if "--only" in args else None
    out: list[tuple[str, str, list[str], Path]] = [
        ("py", "타입 생성물 최신 여부", [PY, "tools/gen_types.py", "--check"], ROOT),
        ("py", "ruff", [venv_bin("ruff"), "check", "server", "tools"], ROOT),
        ("py", "mypy", [venv_bin("mypy")], ROOT),
        ("py", "pytest", [venv_bin("pytest")], ROOT),
        ("web", "디자인 토큰 최신 여부", [PY, "tools/gen_tokens.py", "--check"], ROOT),
        ("web", "eslint", [NPM, "run", "--silent", "lint"], WEB),
        ("web", "tsc", [NPM, "run", "--silent", "typecheck"], WEB),
        ("web", "vitest", [NPM, "run", "--silent", "test"], WEB),
    ]
    matlab = find_matlab()
    if "--no-matlab" in args:
        pass
    elif matlab and (MATLAB_DIR / "tests").exists():
        out.append(("matlab", "MATLAB 테스트", [matlab, "-batch", "run_tests"], MATLAB_DIR))
        out.append(("matlab", "pytest (MATLAB 엔진 연동)", [venv_bin("pytest"), "-m", "matlab"], ROOT))
    if "--no-e2e" not in args:
        out.append(("e2e", "Playwright", [NPM, "run", "--silent", "e2e"], WEB))
    return [s for s in out if only in (None, s[0])]


def main() -> int:
    args = sys.argv[1:]
    env = {**os.environ, "PLAYWRIGHT_BROWSERS_PATH": "0", "CI": "1"}
    results: list[tuple[str, bool, float]] = []
    for _group, name, cmd, cwd in steps(args):
        print(f"\n=== {name} ===", flush=True)
        t0 = time.time()
        try:
            ok = subprocess.run(cmd, cwd=cwd, env=env).returncode == 0
        except OSError as e:
            print(e)
            ok = False
        results.append((name, ok, time.time() - t0))
    print("\n=== 요약 ===")
    for name, ok, dt in results:
        print(f"{'통과' if ok else '실패'}  {name}  ({dt:.1f}초)")
    if "--no-matlab" in args or not find_matlab():
        print("건너뜀  MATLAB 테스트 (" + ("--no-matlab" if find_matlab() else "MATLAB 없음") + ")")
    if "--no-e2e" in args:
        print("건너뜀  Playwright (--no-e2e)")
    failed = [n for n, ok, _ in results if not ok]
    print("\n" + ("전부 통과" if not failed else "실패: " + ", ".join(failed)))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
