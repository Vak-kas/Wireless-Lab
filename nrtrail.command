#!/bin/bash
# macOS: 더블클릭하면 터미널 창에서 nrtrail 을 실행한다. nrtrail 창을 닫으면(또는 이 터미널을 닫으면) 전부 꺼진다.
cd "$(dirname "$0")" || exit 1
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
if [ ! -x venv/bin/python ]; then
  echo "가상환경(venv)이 없습니다. README 의 설치 명령을 먼저 실행하세요."; read -r -p "Enter 를 누르면 닫습니다. " _; exit 1
fi
echo "nrtrail 을 시작합니다. 이 창은 그대로 두세요. nrtrail 창을 닫으면 서버와 OAI 가 함께 꺼집니다."
venv/bin/python tools/app.py "$@"
echo "모두 껐습니다. 이 창은 닫아도 됩니다."
