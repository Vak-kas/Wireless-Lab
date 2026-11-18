# nrtrail — NR 기지국 "따라가기" 도구

5G NR(NTN 포함) 기지국 신호를 **찾고 → 동기를 맞추고 → 방송 정보를 단계별로 읽어 내려가는** 과정을
웹 화면에서 클릭으로 실행하고, 각 단계에서 무슨 일이 일어났는지와 값이 어떻게 계산됐는지를
그림과 수식으로 보여주는 로컬 도구입니다. 이 공개판은 **수신만** 합니다.

스캔 → SSB → MIB → SIB1 → SIB19 순서로 진행하며, 앞 단계가 성공해야 다음 단계가 열립니다.
화면에 보이는 값마다 "원시값 → 공식 → 결과 → 표준 조항"을 펼쳐 볼 수 있습니다.

## 이 저장소에 들어 있는 것

- `web/` 화면 (React + TypeScript + Vite)
- `server/` 로컬 서버 (FastAPI): 세션, 작업, ASN.1(MIB·SIB1·SIB19) 해석, 표준 표 풀이, 위성(NTN) 계산, 추적, 리포트
- `pipeline/` 단계 정의와 문구, 연습 모드가 재생하는 저장된 결과
- `tools/` 환경 점검, 실행, 전체 검증

**연습 모드**는 저장된 결과를 재생하므로 장비도 MATLAB도 없이 전 과정을 체험할 수 있습니다.
저장 파일이나 SDR 장비의 실제 신호를 처리하는 신호처리 엔진(MATLAB 5G Toolbox 기반)은 이 저장소에 들어 있지 않습니다.

## 실행

```
python3.12 -m venv venv
venv/bin/pip install -e '.[dev]'
cd web && npm install && npm run build && cd ..
venv/bin/python tools/doctor.py          # 환경 점검
venv/bin/python tools/dev.py --built     # http://127.0.0.1:8765
```

프로그램처럼 쓰려면 `pip install -e '.[app]'` 을 한 번 하고 아래를 더블클릭합니다. 서버를 띄우고 창을 열며, 창을 닫으면 전부 꺼집니다.

| 운영체제 | 실행 파일 |
|---|---|
| macOS | `nrtrail.app` 또는 `nrtrail.command` (터미널 창이 함께 열립니다. 처음 한 번 폴더 접근 허용을 물을 수 있습니다) |
| Windows | `nrtrail.bat` |
| Linux | `./nrtrail.sh` |

Windows에서는 `venv\Scripts\python`으로 바꿔 씁니다. 전체 검증은 `venv/bin/python tools/verify.py`.

## 하지 않는 것

- 이 공개판에는 송신(TX) 코드가 없습니다. 어떤 SDR API의 송신 경로도 호출하지 않습니다. (화면의 "송신" 타일은 비공개 덧붙임이 있을 때만 켜지며, 그때도 매번 책임 확인 창을 거칩니다.)
- 재밍, 스푸핑, 위조 기지국 기능은 어느 판에도 없습니다.
- 서버는 `127.0.0.1`에서만 열립니다.
- 실시간 장비 입력으로는 방송 정보(SSB, MIB, SIB)까지만 처리합니다.
