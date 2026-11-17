#!/usr/bin/env python3
"""DESIGN-apple.md 와 DESIGN-extensions.md 의 머리말(YAML)에서 CSS 토큰을 만든다.

사용: python tools/gen_tokens.py [--check]
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SOURCES = [ROOT / "DESIGN-apple.md", ROOT / "DESIGN-extensions.md"]
OUT = ROOT / "web" / "src" / "styles" / "tokens.css"


def front_matter(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    _, fm, _ = text.split("---", 2)
    return yaml.safe_load(fm)


def load() -> dict:
    base, ext = (front_matter(p) for p in SOURCES)
    merged = dict(base)
    for key, val in ext.items():
        merged[key] = {**merged.get(key, {}), **val} if isinstance(val, dict) else val
    return merged


def luminance(hex_color: str) -> float:
    def ch(v: int) -> float:
        c = v / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)


def contrast(fg: str, bg: str) -> float:
    a, b = sorted((luminance(fg), luminance(bg)), reverse=True)
    return (a + 0.05) / (b + 0.05)


def render(tokens: dict) -> str:
    lines = ["/* 자동 생성 파일. 고치지 말고 DESIGN-*.md 를 고친 뒤 tools/gen_tokens.py 를 돌릴 것. */", ":root {"]
    for name, value in tokens["fonts"].items():
        lines.append(f"  --font-{name}: {value};")
    for name, value in tokens["colors"].items():
        lines.append(f"  --color-{name}: {value};")
    for name, value in tokens["rounded"].items():
        lines.append(f"  --radius-{name}: {value};")
    for name, value in tokens["spacing"].items():
        lines.append(f"  --space-{name}: {value};")
    for group in ("sizes", "motion", "effects"):
        for name, value in tokens[group].items():
            lines.append(f"  --{group[:-1] if group != 'motion' else 'motion'}-{name}: {value};")
    lines.append("}")
    for name, t in tokens["typography"].items():
        lines += [
            "",
            f".t-{name} {{",
            "  font-family: var(--font-sans);",
            f"  font-size: {t['fontSize']};",
            f"  font-weight: {t['fontWeight']};",
            f"  line-height: {t['lineHeight']};",
            f"  letter-spacing: {t['letterSpacing'] if t['letterSpacing'] else '0'};",
            "}",
        ]
    return "\n".join(lines) + "\n"


def main() -> int:
    if not all(p.exists() for p in SOURCES):
        # 공개판에는 디자인 문서(내부 문서)가 없다. 생성물 tokens.css 를 그대로 쓴다.
        print("디자인 문서가 없어 토큰을 다시 만들지 않습니다(이미 생성된 tokens.css 사용).")
        return 0 if OUT.exists() else 1
    css = render(load())
    if "--check" in sys.argv:
        if not OUT.exists() or OUT.read_text(encoding="utf-8") != css:
            print("디자인 토큰이 문서와 다릅니다. python tools/gen_tokens.py 를 실행하세요.")
            return 1
        print("디자인 토큰이 문서와 일치합니다.")
        return 0
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(css, encoding="utf-8")
    print(f"생성: {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
