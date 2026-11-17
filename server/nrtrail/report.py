"""세션 리포트(SPEC 8절): 세션 하나를 HTML 한 장으로 내보낸다. 브라우저에서 인쇄하면 PDF가 된다.

단계별 요약, 주요 값, 그림(SVG), 계산 과정을 담는다. 문구는 pipeline/stages.json의 "report"에서,
색·글꼴은 화면과 같은 디자인 토큰(web/src/styles/tokens.css)에서 가져온다. 외부 자원을 불러오지 않는다.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from html import escape
from math import cos, radians, sin
from typing import Any

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from .contracts_gen import Plot, StageResult
from .paths import WEB
from .pipeline import Pipeline
from .sessions import Session, SessionStore

W, H, PAD = 720, 260, 44
CSS = """
body{margin:0;font-family:var(--font-sans);color:var(--color-ink);background:var(--color-canvas);font-size:15px;line-height:1.47}
main{max-width:860px;margin:0 auto;padding:var(--space-xl) var(--space-lg)}
h1{font-size:34px;font-weight:600;letter-spacing:-0.374px;margin:0 0 var(--space-xs)}
h2{font-size:24px;font-weight:600;margin:var(--space-xxl) 0 var(--space-xs);padding-top:var(--space-lg);border-top:1px solid var(--color-hairline)}
h3{font-size:17px;font-weight:600;margin:var(--space-lg) 0 var(--space-xs)}
p{margin:var(--space-xxs) 0}.muted{color:var(--color-ink-muted-48);font-size:14px}
table{border-collapse:collapse;width:100%;font-size:14px;margin:var(--space-xs) 0}
th,td{text-align:left;padding:6px 8px;border-bottom:1px solid var(--color-hairline);vertical-align:top}
th{font-weight:600}td.n{text-align:right;font-variant-numeric:tabular-nums}
.ok{color:var(--color-success)}.partial{color:var(--color-warning)}.fail{color:var(--color-error)}
.card{border:1px solid var(--color-hairline);border-radius:var(--radius-lg);padding:var(--space-md);margin:var(--space-xs) 0;break-inside:avoid}
code{font-family:var(--font-mono);font-size:13px}svg{max-width:100%;height:auto;display:block;margin:var(--space-xs) 0}
svg text{font-family:var(--font-sans);font-size:11px;fill:var(--color-ink-muted-48)}
button{font:inherit;border:0;border-radius:var(--radius-pill);background:var(--color-primary);color:var(--color-on-primary);padding:8px 18px;cursor:pointer}
@media print{button{display:none}h2{break-after:avoid}}
"""


def _tokens() -> str:
    path = WEB / "src" / "styles" / "tokens.css"
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _scalar(v: Any) -> str:
    v = getattr(v, "root", v)
    if isinstance(v, list):
        return ", ".join(_scalar(x) for x in v)
    if isinstance(v, bool):
        return "✓" if v else "✕"
    if isinstance(v, float):
        return f"{v:.6g}"
    return "" if v is None else str(v)


def _line_svg(plot: Plot) -> str:
    series = [s for s in plot.series or [] if s.x and s.y]
    if not series:
        return ""
    xs = [x for s in series for x in s.x or []]
    ys = [y for s in series for y in s.y or []]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    if plot.type == "constellation":
        x0 = y0 = -max(1.5, max(map(abs, xs + ys)))
        x1 = y1 = -x0
    x1, y1 = (x1 if x1 > x0 else x0 + 1), (y1 if y1 > y0 else y0 + 1)

    def px(x: float) -> float:
        return PAD + (x - x0) / (x1 - x0) * (W - 2 * PAD)

    def py(y: float) -> float:
        return H - PAD - (y - y0) / (y1 - y0) * (H - 2 * PAD)

    parts = [f'<rect x="{PAD}" y="{PAD}" width="{W - 2 * PAD}" height="{H - 2 * PAD}" fill="none" stroke="var(--color-viz-grid)"/>']
    for s in series:
        colour = "var(--color-viz-accent)" if s.role == "accent" else "var(--color-viz-muted)" if s.role == "muted" else "var(--color-viz-ink)"
        if s.mode == "points":
            parts += [f'<circle cx="{px(x):.1f}" cy="{py(y):.1f}" r="1.6" fill="{colour}"/>' for x, y in zip(s.x or [], s.y or [], strict=False)]
        elif s.mode == "bars":
            parts += [f'<rect x="{px(x) - 20:.1f}" y="{py(y):.1f}" width="40" height="{H - PAD - py(y):.1f}" fill="{colour}"/>'
                      f'<text x="{px(x):.1f}" y="{H - PAD + 14}" text-anchor="middle">{escape(s.name)}</text>'
                      for x, y in zip(s.x or [], s.y or [], strict=False)]
        else:
            pts = " ".join(f"{px(x):.1f},{py(y):.1f}" for x, y in zip(s.x or [], s.y or [], strict=False))
            parts.append(f'<polyline points="{pts}" fill="none" stroke="{colour}" stroke-width="1.2"/>')
    for a in plot.annotations:
        if a.kind == "vline" and a.x is not None and x0 <= a.x <= x1:
            parts.append(f'<line x1="{px(a.x):.1f}" x2="{px(a.x):.1f}" y1="{PAD}" y2="{H - PAD}" stroke="var(--color-viz-accent)" stroke-dasharray="4 3"/>'
                         f'<text x="{px(a.x) + 4:.1f}" y="{PAD + 12}">{escape(a.label)}</text>')
        if a.kind == "point" and a.x is not None and a.y is not None and y0 <= a.y <= y1:
            parts.append(f'<circle cx="{px(a.x):.1f}" cy="{py(a.y):.1f}" r="4" fill="var(--color-viz-accent)"/>')
    xl = f"{plot.x.label} ({plot.x.unit})" if plot.x and plot.x.unit else (plot.x.label if plot.x else "")
    yl = f"{plot.y.label} ({plot.y.unit})" if plot.y and plot.y.unit else (plot.y.label if plot.y else "")
    parts += [f'<text x="{PAD}" y="{H - 8}">{x0:.6g}</text>', f'<text x="{W - PAD}" y="{H - 8}" text-anchor="end">{x1:.6g}</text>',
              f'<text x="{W / 2}" y="{H - 8}" text-anchor="middle">{escape(xl)}</text>',
              f'<text x="{PAD - 4}" y="{H - PAD}" text-anchor="end">{y0:.4g}</text>', f'<text x="{PAD - 4}" y="{PAD + 10}" text-anchor="end">{y1:.4g}</text>',
              f'<text x="{PAD}" y="{PAD - 8}">{escape(yl)}</text>']
    return f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="{escape(plot.title)}">{"".join(parts)}</svg>'


def _grid_svg(plot: Plot) -> str:
    g = plot.grid
    if g is None:
        return ""
    cw, ch = (W - 2 * PAD) / g.cols, (H - 2 * PAD) / g.rows
    cells = "".join(
        f'<rect x="{PAD + c * cw:.1f}" y="{H - PAD - (r + 1) * ch:.2f}" width="{cw:.1f}" height="{ch + 0.3:.2f}" '
        f'fill="var(--color-viz-accent)" fill-opacity="{min(max(g.values[r][c], 0), 1):.2f}"/>'
        for r in range(g.rows) for c in range(g.cols))
    xl, yl = (plot.x.label if plot.x else ""), (plot.y.label if plot.y else "")
    return (f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="{escape(plot.title)}">{cells}'
            f'<rect x="{PAD}" y="{PAD}" width="{W - 2 * PAD}" height="{H - 2 * PAD}" fill="none" stroke="var(--color-viz-grid)"/>'
            f'<text x="{W / 2}" y="{H - 8}" text-anchor="middle">{escape(xl)}</text><text x="{PAD}" y="{PAD - 8}">{escape(yl)}</text></svg>')


def _sky_svg(plot: Plot) -> str:
    sky = plot.sky
    if sky is None:
        return ""
    cx, cy, r = W / 2, H / 2, H / 2 - 24

    def pt(az: float, el: float) -> tuple[float, float]:
        d = r * (90 - max(el, 0)) / 90
        return cx + d * sin(radians(az)), cy - d * cos(radians(az))

    parts = [f'<circle cx="{cx}" cy="{cy}" r="{r * k:.1f}" fill="none" stroke="var(--color-viz-grid)"/>' for k in (1, 2 / 3, 1 / 3)]
    parts += [f'<text x="{cx}" y="{cy - r - 6}" text-anchor="middle">N</text>']
    for t in sky.tracks:
        pts = " ".join("{:.1f},{:.1f}".format(*pt(a, e)) for a, e in zip(t.az_deg, t.el_deg, strict=True))
        parts.append(f'<polyline points="{pts}" fill="none" stroke="var(--color-viz-ink)" stroke-width="1.2"/>')
    for m in sky.markers:
        x, y = pt(m.az_deg, m.el_deg)
        parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="5" fill="var(--color-viz-accent)"/><text x="{x + 8:.1f}" y="{y + 4:.1f}">{escape(m.name)}</text>')
    return f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="{escape(plot.title)}">{"".join(parts)}</svg>'


def _table_html(plot: Plot) -> str:
    t = plot.table
    if t is None:
        return ""
    head = "".join(f"<th>{escape(c.label)}{f' ({escape(c.unit)})' if c.unit else ''}</th>" for c in t.columns)
    rows = "".join("<tr>" + "".join(f'<td class="{"n" if c.align == "right" else ""}">{escape(_scalar(row.get(c.key)))}</td>' for c in t.columns) + "</tr>"
                   for row in t.rows)
    return f"<table><thead><tr>{head}</tr></thead><tbody>{rows}</tbody></table>"


def plot_html(plot: Plot) -> str:
    body = {"table": _table_html, "resource_grid": _grid_svg, "sky_geometry": _sky_svg}.get(plot.type, _line_svg)(plot)
    cap = f'<p class="muted">{escape(plot.caption)}</p>' if plot.caption else ""
    return f"<h3>{escape(plot.title)}</h3>{body}{cap}" if body else ""


def stage_html(title: str, result: StageResult | None, tx: dict[str, str]) -> str:
    if result is None:
        return f'<h2>{escape(title)}</h2><p class="muted">{escape(tx["not_run"])}</p>'
    status = tx[f"status_{result.status}"]
    out = [f'<h2>{escape(title)} <span class="{result.status}">· {escape(status)}</span></h2>',
           f"<p>{escape(result.summary_easy)}</p>", f'<p class="muted">{escape(tx["expert"])}: <code>{escape(result.summary_expert)}</code></p>']
    for diag in result.diagnostics:
        out.append(f'<div class="card"><strong>{escape(diag.message_easy)}</strong><p>{escape(diag.fix)}</p></div>')
    if result.values:
        rows = "".join(f'<tr><td>{escape(v.label)}</td><td class="n">{escape(_scalar(v.value))} {escape(v.unit)}</td>'
                       f'<td class="muted">{escape(v.source or v.derivation_id or "")}</td></tr>' for v in result.values)
        out.append(f'<h3>{escape(tx["values"])}</h3><table><tbody>{rows}</tbody></table>')
    out += [plot_html(p) for p in result.plots]
    if result.derivations:
        out.append(f'<h3>{escape(tx["derivations"])}</h3>')
        for d in result.derivations:
            inputs = "; ".join(f"{escape(i.symbol)} = {escape(_scalar(i.value))}{' ' + escape(i.unit) if i.unit else ''} ({escape(i.source)})" for i in d.inputs)
            steps = "".join(f"<li><code>{escape(s)}</code></li>" for s in d.steps)
            out.append(f'<div class="card"><strong>{escape(d.title)}</strong> <span class="muted">{escape(d.id)} · {escape(d.spec_ref)}</span>'
                       f'<p><code>{escape(d.formula_tex)}</code></p><p class="muted">{escape(tx["inputs"])}: {inputs}</p>'
                       f'<ol>{steps}</ol><p>{escape(tx["result"])}: <strong>{escape(_scalar(d.result.value))} {escape(d.result.unit)}</strong></p></div>')
    if result.spec_refs:
        out.append(f'<p class="muted">{escape(tx["refs"])}: {escape(", ".join(result.spec_refs))}</p>')
    return "".join(out)


def render(session: Session, pipeline: Pipeline, ntn_result: StageResult | None = None, track: dict[str, Any] | None = None,
           changes: list[dict[str, Any]] | None = None) -> str:
    tx: dict[str, str] = pipeline.stage("report").data["text"]
    src = session.source
    kind = tx.get(f"kind_{src.get('kind')}", str(src.get("kind")))
    detail = src.get("scenario") or src.get("path") or src.get("device_label") or ""
    body = [f"<h1>{escape(session.name)}</h1>",
            f'<p class="muted">{escape(tx["created"])}: {escape(session.created_at)} · {escape(tx["source"])}: {escape(kind)} {escape(str(detail))} · '
            f'{escape(tx["engine"])}: {escape(session.engine)}</p>', f'<p><button onclick="print()">{escape(tx["print"])}</button></p>']
    for s in pipeline.stages:
        body.append(stage_html(f"{s.data['title']} — {s.data.get('question', '')}", session.state.results.get(s.id), tx))
    if ntn_result is not None:
        body.append(stage_html(pipeline.stage("ntn").data["title"], ntn_result, tx))
    if track and track.get("points"):
        cols = ["t_s"] + [s["key"] for s in track["series"]]
        head = f'<th>{escape(tx["time"])} (s)</th>' + "".join(f"<th>{escape(s['label'])} ({escape(s['unit'])})</th>" for s in track["series"])
        rows = "".join("<tr>" + "".join(f'<td class="n">{escape(_scalar(p.get(c)))}</td>' for c in cols) + "</tr>" for p in track["points"][:200])
        body.append(f'<h2>{escape(tx["track"])}</h2><table><thead><tr>{head}</tr></thead><tbody>{rows}</tbody></table>')
    if changes:
        rows = "".join(f'<tr><td class="n">{c["t_s"]}</td><td>{escape(c["label"])}</td><td>{escape(c["before"])}</td><td>{escape(c["after"])}</td></tr>' for c in changes)
        body.append(f'<h3>{escape(tx["changes"])}</h3><table><thead><tr><th>{escape(tx["time"])} (s)</th><th>{escape(tx["field"])}</th>'
                    f'<th>{escape(tx["before"])}</th><th>{escape(tx["after"])}</th></tr></thead><tbody>{rows}</tbody></table>')
    body.append(f'<p class="muted" style="margin-top:var(--space-xxl)">{escape(tx["footer"])}</p>')
    meta = json.dumps({"session": session.id}, ensure_ascii=False)
    return (f'<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
            f"<title>{escape(session.name)} — nrtrail</title><style>{_tokens()}{CSS}</style></head>"
            f"<body><main>{''.join(body)}</main><script type=\"application/json\" id=\"meta\">{meta}</script></body></html>")


def register(app: FastAPI, store: SessionStore, pipeline: Pipeline, session: Callable[[str], Session]) -> None:
    @app.get("/api/sessions/{sid}/report.html", response_class=HTMLResponse)
    def report(sid: str) -> str:
        s = session(sid)
        ntn_result = None
        if s.state.done("sib19"):
            from types import SimpleNamespace

            from .stages import ntn

            loc = s.state.settings.get("location") or ntn.DEFAULT_LOCATION
            ntn_result = ntn.compute(SimpleNamespace(state=s.state), loc["lat"], loc["lon"], loc["alt_m"])
        trackers = getattr(app.state, "trackers", {})
        t = trackers.get(sid)
        return render(s, pipeline, ntn_result, t.data() if t else None, t.changes if t else None)
