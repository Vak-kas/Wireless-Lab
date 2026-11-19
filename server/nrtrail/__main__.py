"""서버 실행: python -m nrtrail [--port 8765] [--engine auto|mock|matlab] [--mock-delay 0.35]

항상 127.0.0.1 에만 연다. 다른 주소에 바인딩하는 옵션은 없다.
"""

from __future__ import annotations

import argparse

import uvicorn

from .app import create_app
from .engines.base import Engine
from .engines.mock import MockEngine

HOST = "127.0.0.1"


def build_engines(choice: str, mock_delay: float) -> dict[str, Engine]:
    engines: dict[str, Engine] = {"mock": MockEngine(delay_s=mock_delay)}
    if choice in ("auto", "matlab"):
        try:
            from .engines.matlab import shared as shared_matlab

            matlab = shared_matlab()
            if matlab.available():
                engines["matlab"] = matlab
            elif choice == "matlab":
                raise SystemExit("MATLAB을 찾지 못했습니다. tools/doctor.py 로 환경을 확인하세요.")
        except ImportError:
            if choice == "matlab":
                raise SystemExit("MATLAB 엔진 모듈이 없습니다.") from None
    return engines


def main() -> None:
    parser = argparse.ArgumentParser(prog="nrtrail", description="NR 기지국 따라가기 도구 (로컬 전용, 수신 전용)")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--engine", choices=["auto", "mock", "matlab"], default="auto")
    parser.add_argument("--mock-delay", type=float, default=0.35, help="연습 모드에서 진행 문구마다 쉬는 시간(초)")
    args = parser.parse_args()
    app = create_app(build_engines(args.engine, args.mock_delay), default_engine="matlab" if args.engine == "matlab" else None)
    try:
        from . import usrp_matlab

        usrp_matlab.warm()          # USRP 찾기를 미리 시작한다(MATLAB 을 띄우는 데 시간이 걸린다)
    except ImportError:
        pass
    from . import procs

    procs.record(port=args.port)
    print(f"nrtrail 서버: http://{HOST}:{args.port}")
    try:
        uvicorn.run(app, host=HOST, port=args.port, log_level="warning")
    finally:
        # 꺼질 때 MATLAB 을 남기지 않는다(남으면 USRP 를 잡은 채로 다음 실행을 막는다)
        try:
            from .engines import matlab as matlab_engine

            matlab_engine.close_all()          # 장비마다 띄운 것까지 전부
        except ImportError:
            pass
        procs.forget()


if __name__ == "__main__":
    main()
