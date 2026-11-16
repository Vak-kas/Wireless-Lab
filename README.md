# nrtrail — NR 기지국 "따라가기" 도구

5G NR(NTN 포함) 기지국 신호를 찾고, 동기를 맞추고, 방송 정보를 단계별로 읽어 내려가는 과정을
웹 화면에서 클릭으로 실행하고 그림과 계산 과정으로 보여주는 **수신 전용** 로컬 도구.

- 무엇을 만드는가: [SPEC.md](SPEC.md)
- 지금 어디까지 됐는가: [PROGRESS.md](PROGRESS.md)
- 왜 그렇게 정했는가: [DECISIONS.md](DECISIONS.md)

## 실행

```
python3.12 -m venv venv
venv/bin/pip install -e '.[dev]'
cd web && npm install && cd ..
venv/bin/python tools/doctor.py
venv/bin/python tools/dev.py
```

Windows에서는 `venv\Scripts\python`으로 바꿔 쓴다.

## 하지 않는 것

송신(TX), 재밍, 스푸핑, 위조 기지국 기능은 없다. 서버는 `127.0.0.1`에서만 열린다.
실시간 장비 입력으로는 방송 정보(SSB, MIB, SIB)까지만 처리한다.
