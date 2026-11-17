"""pipeline/stages.json 읽기. 단계 이름·선행 조건·문구·표준 조항은 전부 그 파일에 있고 코드는 키만 참조한다."""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

from .paths import PIPELINE

PUBLIC_KEYS = ("id", "requires", "label", "title", "question", "intro", "analogy", "button",
               "locked_reason", "spec_refs", "progress", "groups")


def _overlay(base: Any, over: Any) -> Any:
    """영어 덮어쓰기. 비어 있는 문자열은 한국어를 그대로 둔다."""
    if isinstance(base, dict) and isinstance(over, dict):
        return {k: _overlay(v, over[k]) if k in over else v for k, v in base.items()}
    if isinstance(base, list) and isinstance(over, list) and len(base) == len(over):
        return [_overlay(b, o) for b, o in zip(base, over, strict=True)]
    if isinstance(base, str) and isinstance(over, str) and over:
        return over
    return base


class StageDef:
    def __init__(self, data: dict[str, Any]):
        self.data = data
        self.id: str = data["id"]
        self.requires: list[str] = data.get("requires", [])

    def text(self, *path: str, **vars: Any) -> str:
        cur: Any = self.data
        for key in path:
            cur = cur[key]
        if not isinstance(cur, str):
            raise KeyError("/".join(path))
        return cur.format(**vars) if vars else cur

    def public(self) -> dict[str, Any]:
        return {k: self.data.get(k) for k in PUBLIC_KEYS}


class Pipeline:
    def __init__(self, data: dict[str, Any]):
        self.stages = [StageDef(s | {"_common_diagnostics": data.get("common_diagnostics", {})}) for s in data["stages"]]
        self.order = [s.id for s in self.stages]

    def stage(self, stage_id: str) -> StageDef:
        for s in self.stages:
            if s.id == stage_id:
                return s
        raise KeyError(stage_id)

    def public(self) -> dict[str, Any]:
        return {"stages": [s.public() for s in self.stages]}


@lru_cache(maxsize=4)
def load_pipeline(lang: str = "ko") -> Pipeline:
    data = json.loads((PIPELINE / "stages.json").read_text(encoding="utf-8"))
    over_path = PIPELINE / f"stages.{lang}.json"
    if lang != "ko" and over_path.exists():
        data = _overlay(data, json.loads(over_path.read_text(encoding="utf-8")))
    return Pipeline(data)


@lru_cache(maxsize=4)
def load_glossary(lang: str = "ko") -> dict[str, dict[str, str]]:
    data = json.loads((PIPELINE / "glossary.json").read_text(encoding="utf-8"))
    over_path = PIPELINE / f"glossary.{lang}.json"
    if lang != "ko" and over_path.exists():
        data = _overlay(data, json.loads(over_path.read_text(encoding="utf-8")))
    return data["terms"]
