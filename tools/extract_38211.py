#!/usr/bin/env python3
"""TS 38.211 원문(specs/38211-*.txt)에서 PRACH 설정 표(6.3.3.2-2 FR1 FDD/SUL, 6.3.3.2-3 FR1 TDD)를 뽑아
pipeline/tables/ts38211_prach.json 으로 저장한다. 표를 손으로 옮기지 않기 위한 도구다(원문은 git에 넣지 않는다).

사용: python tools/extract_38211.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "pipeline" / "tables" / "ts38211_prach.json"
TABLES = {"6.3.3.2-2": "fr1_paired", "6.3.3.2-3": "fr1_unpaired"}


def parse(lines: list[str], name: str) -> list[dict]:
    start = max(i for i, ln in enumerate(lines) if ln.startswith(f"Table {name}:"))
    cells: list[str] = []
    for ln in lines[start + 1:]:
        s = ln.strip()
        if s.startswith("Table ") or (cells and re.match(r"^\d+(\.\d+)+\t", s)):
            break
        if s:
            cells.append(s)
    first = next(i for i, c in enumerate(cells) if "PRACH duration" in c) + 1
    body = cells[first:]
    rows: list[dict] = []
    i = 0
    while i + 6 < len(body):
        idx, fmt, x, y, subframes, start_sym = body[i:i + 6]
        if not idx.isdigit() or int(idx) != len(rows):
            break
        i += 6
        if fmt in ("0", "1", "2", "3"):
            # 긴 프리앰블: 슬롯 수·기회 수 칸은 "-"이고(원문 변환에서 빈칸으로 빠지기도 한다) 길이는 0
            while body[i] == "-":
                i += 1
            slots, occasions, duration = "-", "-", body[i]
            i += 1
        else:
            slots, occasions, duration = body[i:i + 3]
            i += 3
        rows.append({
            "format": fmt, "x": int(x), "y": [int(v) for v in y.split(",")],
            "subframes": [int(v) for v in subframes.split(",")], "start_symbol": int(start_sym),
            "slots_per_subframe": None if slots == "-" else int(slots),
            "occasions_per_slot": None if occasions == "-" else int(occasions), "duration": int(duration),
        })
    assert len(rows) >= 256, f"표 {name}: 256행 이상이어야 하는데 {len(rows)}행"
    return rows


def main() -> int:
    sources = sorted((ROOT / "specs").glob("38211-*.txt"))
    sources = [s for s in sources if not s.name.endswith(".math.txt")]
    if not sources:
        print("specs/38211-*.txt 가 없습니다.")
        return 1
    lines = sources[-1].read_text(encoding="utf-8").splitlines()
    out = {"_source": f"3GPP TS 38.211 ({sources[-1].stem}), 표 6.3.3.2-2, 6.3.3.2-3. tools/extract_38211.py 로 원문에서 추출. 손으로 고치지 말 것."}
    for name, key in TABLES.items():
        out[key] = parse(lines, name)
        print(f"표 {name}: {len(out[key])}행")
    OUT.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"생성: {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
