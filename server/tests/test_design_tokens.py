"""디자인 규칙을 기계로 확인한다: 명도 대비, 컴포넌트에 색상 코드 직접 쓰기 금지."""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import gen_tokens  # noqa: E402


def test_contrast_pairs_meet_4_5():
    tokens = gen_tokens.load()
    colors = tokens["colors"]
    low = [(fg, bg, round(gen_tokens.contrast(colors[fg], colors[bg]), 2))
           for fg, bg in tokens["contrast_pairs"]
           if gen_tokens.contrast(colors[fg], colors[bg]) < 4.5]
    assert not low, f"명도 대비 4.5:1 미만: {low}"


def test_no_raw_colors_outside_tokens():
    src = ROOT / "web" / "src"
    pattern = re.compile(r"#[0-9a-fA-F]{3,8}\b|rgba?\(")
    bad = []
    for path in src.rglob("*"):
        if path.suffix not in {".css", ".ts", ".tsx"} or path.name in {"tokens.css", "contracts.gen.ts"}:
            continue
        if "__fixtures__" in path.parts:
            continue
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if pattern.search(line) and "token-ok" not in line:
                bad.append(f"{path.relative_to(ROOT)}:{n}: {line.strip()[:80]}")
    assert not bad, "토큰 대신 색상 코드를 직접 쓴 곳:\n" + "\n".join(bad)
