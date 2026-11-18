#!/bin/bash
# macOS: 더블클릭하면 터미널 창에서 nrtrail 을 실행한다. nrtrail 창을 닫으면(또는 이 터미널을 닫으면) 전부 꺼진다.
cd "$(dirname "$0")" || exit 1
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
if [ ! -x venv/bin/python ] || [ ! -f web/dist/index.html ]; then
  # 처음 실행: 프로젝트 안에 가상환경을 만들고 필요한 패키지를 깐다(몇 분 걸릴 수 있다)
  echo "처음 실행이라 필요한 것을 설치합니다…"
  PY="$(command -v python3.12 || command -v python3)"
  if [ -z "$PY" ] || ! "$PY" tools/bootstrap.py; then
    echo "설치하지 못했습니다. 위의 내용을 확인하세요."; read -r -p "Enter 를 누르면 닫습니다. " _; exit 1
  fi
fi
echo "nrtrail 을 시작합니다. 이 창은 그대로 두세요. nrtrail 창을 닫으면 서버와 OAI 가 함께 꺼집니다."
venv/bin/python tools/app.py "$@"
echo "모두 껐습니다. 이 창은 닫아도 됩니다."
