#!/bin/sh
# Linux: ./nrtrail.sh 로 실행한다. 창을 닫으면 전부 꺼진다.
cd "$(dirname "$0")" || exit 1
exec venv/bin/python tools/app.py "$@"
