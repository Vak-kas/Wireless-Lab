#!/bin/bash
# macOS: 더블클릭하면 터미널 창에서 nrtrail 을 실행한다. 창(또는 이 터미널)을 닫으면 전부 꺼진다.
cd "$(dirname "$0")" || exit 1
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
exec venv/bin/python tools/app.py "$@"
