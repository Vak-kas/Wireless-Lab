# nrtrail — SDR 로 무선 신호를 보고 따라가는 로컬 도구

**한국어** · [English](README.en.md)

SDR 장비(또는 저장된 파일)의 신호를 웹 화면에서 클릭으로 받아 보고, 무슨 일이 일어났는지를
그림과 수식으로 보여주는 로컬 도구입니다. 브라우저 ↔ 내 컴퓨터의 서버(`127.0.0.1`)로만 동작합니다.

- **5G NR 기지국 따라가기** (NTN 포함): 스캔 → SSB → MIB → SIB1 → SIB19 순서로 진행합니다. 화면의 값마다 "원시값 → 공식 → 결과 → 표준 조항"을 펼쳐 볼 수 있습니다.
- **주파수 보기**: 가운데 주파수와 폭을 정해 스펙트럼을 보고, Wi-Fi 2.4 / 5 / 6 GHz 채널별 세기를 계속 지켜봅니다.
- **블루투스**: BLE 광고(누구나 받으라고 내보내는 방송)를 받아 풉니다.
- **연습 모드**: 저장된 결과를 재생하므로 장비 없이 전 과정을 체험할 수 있습니다.

이 공개판(Basic)은 **수신만** 합니다.

## Basic 과 Pro

| | Basic (이 저장소, 무료) | Pro (비공개) |
|---|---|---|
| 화면, 로컬 서버, 연습 모드 | ✓ | ✓ |
| 방송 정보 해석(MIB·SIB1·SIB19), 위성(NTN) 계산, 추적, 리포트 | ✓ | ✓ |
| 채널 세기 모니터, 스펙트럼, BLE 광고 수신 | ✓ | ✓ |
| 실제 신호의 5G NR 신호처리 엔진 (MATLAB 5G Toolbox 기반) | — | ✓ |
| USRP 자동 등록·수신 (MATLAB) | — | ✓ |
| Wi-Fi 비콘·프리앰블 풀이 (주변 AP, 대역폭) | — | ✓ |
| 실험용 송신 (매번 책임 확인 창을 거침) | — | ✓ |
| OAI NTN 시뮬레이터 테스트베드 | — | ✓ |

Pro 는 이 저장소 위에 덧붙이는 형태이며 MATLAB 과 해당 툴박스가 필요합니다.

**Pro 문의**: [smjgallery.kr](https://smjgallery.kr) · <mjseo@smjgallery.kr>

## 이 저장소에 들어 있는 것

- `web/` 화면 (React + TypeScript + Vite)
- `server/` 로컬 서버 (FastAPI): 세션, 작업, 장비 계층, ASN.1 해석, 표준 표 풀이, 위성 계산, 채널 모니터, BLE 수신
- `pipeline/` 단계 정의와 문구, 연습 모드가 재생하는 저장된 결과
- `tools/` 환경 점검, 실행, 전체 검증

Basic 에서 실제 장비를 쓰려면 SoapySDR 과 장비 모듈을 따로 설치해야 합니다(없어도 연습 모드는 됩니다).

## 실행

```
python3.12 -m venv venv
venv/bin/pip install -e '.[dev]'
cd web && npm install && npm run build && cd ..
venv/bin/python tools/doctor.py          # 환경 점검
venv/bin/python tools/dev.py --built     # http://127.0.0.1:8765
```

프로그램처럼 쓰려면 아래를 더블클릭합니다. 가상환경이 없으면 처음 한 번 스스로 만들고 필요한 파이썬 패키지를 깝니다(`tools/bootstrap.py`. 화면을 지으려면 Node.js 가 있어야 합니다). 서버를 띄우고 창을 열며, 창을 닫으면 전부 꺼집니다.

| 운영체제 | 실행 파일 |
|---|---|
| macOS | `nrtrail.app` 또는 `nrtrail.command` (터미널 창이 함께 열립니다. 처음 한 번 폴더 접근 허용을 물을 수 있습니다) |
| Windows | `nrtrail.bat` |
| Linux | `./nrtrail.sh` |

Windows에서는 `venv\Scripts\python`으로 바꿔 씁니다. 전체 검증은 `venv/bin/python tools/verify.py`.

## 하지 않는 것

- 이 공개판에는 송신(TX) 코드가 없습니다. 어떤 SDR API 의 송신 경로도 호출하지 않습니다. (화면의 "송신" 타일은 Pro 가 있을 때만 켜집니다.)
- 재밍, 스푸핑, 위조 기지국 기능은 어느 판에도 없습니다.
- 서버는 `127.0.0.1`에서만 열립니다.
- 실시간 장비 입력으로는 방송 정보(기지국의 SSB·MIB·SIB, Wi-Fi 비콘과 프레임 머리말, BLE 광고)까지만 처리합니다. 개별 기기끼리 주고받는 내용은 풀지 않습니다.

## 라이선스

Apache License 2.0 — [LICENSE](LICENSE) 참고. Pro 덧붙임은 이 라이선스에 포함되지 않습니다.
함께 쓰는 외부 프로그램(MATLAB, UHD 등)은 각자의 라이선스를 따르며 이 저장소에 들어 있지 않습니다.
