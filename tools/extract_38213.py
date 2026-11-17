#!/usr/bin/env python3
"""TS 38.213 원문(specs/38213-*.txt)에서 13절의 표를 뽑아 pipeline/tables/ts38213_13.json 으로 저장한다.

표를 손으로 옮기지 않기 위한 도구다. 원문 텍스트는 docx를 `textutil -convert txt`로 바꾼 것으로,
표의 칸이 한 줄에 하나씩 나온다. 저작권 때문에 원문은 git에 넣지 않고, 뽑아낸 숫자 표만 넣는다.

사용: python tools/extract_38213.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "pipeline" / "tables" / "ts38213_13.json"

# FR1에서 쓰는 CORESET0 표와 감시 시점 표. (표 이름, SSB SCS kHz, PDCCH SCS kHz, 조건)
CORESET_TABLES = {
    "13-1": (15, 15, "min_bw_5_or_10"),
    "13-2": (15, 30, "min_bw_5_or_10"),
    "13-3": (30, 15, "min_bw_5_or_10"),
    "13-4": (30, 30, "min_bw_5_or_10"),
    "13-5": (30, 15, "min_bw_40"),
    "13-6": (30, 30, "min_bw_40"),
}


def table_cells(lines: list[str], name: str) -> tuple[str, list[str]]:
    start = next(i for i, ln in enumerate(lines) if ln.startswith(f"Table {name}:"))
    cells: list[str] = []
    for ln in lines[start + 1:]:
        s = ln.strip()
        if s.startswith("Table ") or (not s and "0" in cells):
            break
        if s:
            cells.append(s)
    return lines[start].strip(), cells


def parse_coreset(cells: list[str]) -> list[dict | None]:
    body = cells[cells.index("0"):]
    rows: list[dict | None] = []
    i = 0
    while i < len(body):
        index = int(body[i])
        assert index == len(rows), f"행 번호가 순서대로가 아님: {index}"
        if body[i + 1] == "Reserved":
            rows.append(None)
            i += 2
            continue
        pattern, n_rb, n_sym, offset = (int(float(x)) for x in body[i + 1:i + 5])
        rows.append({"pattern": pattern, "n_rb": n_rb, "n_sym": n_sym, "offset_rb": offset})
        i += 5
    assert len(rows) == 16, f"16행이어야 함: {len(rows)}"
    return rows


def parse_monitoring(cells: list[str]) -> list[dict]:
    """표 13-11: (O, 슬롯당 탐색 공간 수, M, 첫 심볼). 첫 심볼이 식이면 'alt'로 적는다(짝수 i는 0, 홀수 i는 N_symb^CORESET)."""
    body = cells[cells.index("0"):]
    rows: list[dict] = []
    i = 0
    while i < len(body):
        assert int(body[i]) == len(rows)
        o, n_sets, m, first = body[i + 1:i + 5]
        rows.append({
            "o": float(o), "sets_per_slot": int(n_sets),
            "m": 0.5 if m == "1/2" else float(m),
            "first_symbol": "alt" if first.startswith("{") else int(first),
        })
        i += 5
    assert len(rows) == 16
    return rows


def main() -> int:
    sources = sorted((ROOT / "specs").glob("38213-*.txt"))
    if not sources:
        print("specs/38213-*.txt 가 없습니다. TS 38.213 docx를 specs/에 두고 textutil -convert txt 로 바꾸세요.")
        return 1
    src = sources[-1]
    lines = src.read_text(encoding="utf-8").splitlines()
    version = re.search(r"38213-(\w+)", src.name)
    out: dict = {
        "_source": f"3GPP TS 38.213 ({src.stem}), 13절. tools/extract_38213.py 로 원문에서 추출. 손으로 고치지 말 것.",
        "version": version.group(1) if version else "",
        "coreset0": {},
        "monitoring_pattern1_fr1": [],
    }
    for name, (ssb_scs, pdcch_scs, cond) in CORESET_TABLES.items():
        title, cells = table_cells(lines, name)
        out["coreset0"][name] = {"ssb_scs_khz": ssb_scs, "pdcch_scs_khz": pdcch_scs, "condition": cond,
                                 "title": title[:80], "rows": parse_coreset(cells)}
    _, cells = table_cells(lines, "13-11")
    out["monitoring_pattern1_fr1"] = parse_monitoring(cells)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"생성: {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
