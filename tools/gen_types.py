#!/usr/bin/env python3
"""pipeline/schema/contracts.schema.json 에서 Python(pydantic)과 TypeScript 타입을 만든다.

사용: python tools/gen_types.py          생성
      python tools/gen_types.py --check  생성물이 최신인지 확인만 (다르면 1로 종료)
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))

from nrtrail.paths import PIPELINE, ROOT, WEB, venv_bin  # noqa: E402

SCHEMA = PIPELINE / "schema" / "contracts.schema.json"
PY_OUT = ROOT / "server" / "nrtrail" / "contracts_gen.py"
TS_OUT = WEB / "src" / "api" / "contracts.gen.ts"
NPX = "npx.cmd" if sys.platform == "win32" else "npx"


def generate(py_out: Path, ts_out: Path) -> None:
    subprocess.run(
        [venv_bin("datamodel-codegen"), "--input", str(SCHEMA), "--input-file-type", "jsonschema",
         "--output", str(py_out), "--output-model-type", "pydantic_v2.BaseModel",
         "--target-python-version", "3.10", "--use-standard-collections", "--use-union-operator",
         "--disable-timestamp", "--use-annotated", "--enum-field-as-literal", "all", "--use-schema-description"],
        check=True,
    )
    ts = subprocess.run(
        [NPX, "--no-install", "json2ts", "--input", str(SCHEMA), "--unreachableDefinitions",
         "--bannerComment", "/* 자동 생성 파일. 고치지 말고 tools/gen_types.py 를 다시 돌릴 것. */"],
        check=True, capture_output=True, text=True, cwd=WEB,
    ).stdout
    ts_out.parent.mkdir(parents=True, exist_ok=True)
    ts_out.write_text(ts, encoding="utf-8")


def main() -> int:
    if "--check" not in sys.argv:
        generate(PY_OUT, TS_OUT)
        print(f"생성: {PY_OUT.relative_to(ROOT)}, {TS_OUT.relative_to(ROOT)}")
        return 0
    with tempfile.TemporaryDirectory() as tmp:
        py_tmp, ts_tmp = Path(tmp) / "c.py", Path(tmp) / "c.ts"
        generate(py_tmp, ts_tmp)
        stale = [str(out.relative_to(ROOT)) for out, new in ((PY_OUT, py_tmp), (TS_OUT, ts_tmp))
                 if not out.exists() or out.read_text(encoding="utf-8") != new.read_text(encoding="utf-8")]
    if stale:
        print("스키마와 생성된 타입이 다릅니다. python tools/gen_types.py 를 실행하세요: " + ", ".join(stale))
        return 1
    print("생성된 타입이 스키마와 일치합니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
