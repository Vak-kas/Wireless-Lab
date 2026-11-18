#!/bin/sh
# Linux: ./nrtrail.sh 로 실행한다. 창을 닫으면 전부 꺼진다.
cd "$(dirname "$0")" || exit 1
if [ ! -x venv/bin/python ] || [ ! -f web/dist/index.html ]; then
  # 처음 실행: 프로젝트 안에 가상환경을 만들고 필요한 패키지를 깐다
  PY="$(command -v python3.12 || command -v python3)"
  [ -n "$PY" ] && "$PY" tools/bootstrap.py || { echo "설치하지 못했습니다."; exit 1; }
fi
exec venv/bin/python tools/app.py "$@"
