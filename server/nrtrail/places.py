"""사용자가 수신 화면의 + 로 추가한 "볼 곳"(이름, 가운데 주파수, 폭)을 서버에 둔다: sessions/view-bands.json.

왜 서버인가
    전에는 브라우저의 저장소(localStorage)에 두었다. 그 저장소는 주소(포트까지)마다 따로라서,
    앱이 다른 포트로 뜨면 브라우저가 다른 사이트로 보고 추가해 둔 것이 사라진 것처럼 보였다.
    파일에 두면 포트가 바뀌어도, 브라우저를 바꿔도 그대로다.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from .paths import sessions_dir

MAX_PLACES = 50
MAX_NAME = 40


def _file() -> Path:
    return sessions_dir() / "view-bands.json"


def clean(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """받은 목록에서 쓸 수 있는 것만: 이름은 글자, 가운데와 폭은 0 보다 큰 수(MHz)."""
    out = []
    for it in items[:MAX_PLACES]:
        try:
            center, width = float(it["center_mhz"]), float(it["width_mhz"])
            name = str(it["name"]).strip()[:MAX_NAME]
        except (KeyError, TypeError, ValueError):
            continue
        if center > 0 and width > 0 and name:
            out.append({"id": str(it.get("id") or f"{center:g}-{width:g}-{len(out)}"), "name": name, "center_mhz": center, "width_mhz": width})
    return out


def load() -> list[dict[str, Any]]:
    try:
        raw = json.loads(_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return clean(raw) if isinstance(raw, list) else []


def save(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    kept = clean(items)
    _file().parent.mkdir(parents=True, exist_ok=True)
    _file().write_text(json.dumps(kept, ensure_ascii=False, indent=1), encoding="utf-8")
    return kept


class PlacesBody(BaseModel):
    bands: list[dict[str, Any]]


def register(app: FastAPI) -> None:
    @app.get("/api/bands")
    def bands_load() -> dict[str, Any]:
        return {"bands": load()}

    @app.post("/api/bands")
    def bands_save(body: PlacesBody) -> dict[str, Any]:
        try:
            return {"bands": save(body.bands)}
        except OSError as e:
            raise HTTPException(500, f"저장하지 못했습니다: {e.strerror or e}") from e
