"""단계 0 — 대역 스캔."""

from __future__ import annotations

from typing import Any

from ..contracts_gen import StageResult
from ..nr import raster
from ..pipeline import StageDef
from ..result import ResultBuilder, fmt, inp
from .base import Ctx, Plot, PlotAnnotation, PlotAxis, PlotColumn, PlotSeries, PlotTable, thin


def derive_gscn(b: ResultBuilder, gscn: int, source: str) -> str:
    g = raster.gscn_to_freq(gscn)
    if g.m is not None:
        return b.derive(
            "gscn", r"SS_{REF} = N \cdot 1200\,\mathrm{kHz} + M \cdot 50\,\mathrm{kHz},\quad GSCN = 3N + \frac{M-3}{2}",
            [inp("GSCN", gscn, source)],
            [f"N = {g.n}, M = {g.m}  (3 × {g.n} + ({g.m} − 3)/2 = {gscn})",
             f"SS_REF = {g.n} × 1200 kHz + {g.m} × 50 kHz = {g.ss_ref_hz // 1000} kHz"],
            g.ss_ref_hz / 1e6, "MHz", "TS 38.104 5.4.3.1")
    return b.derive(
        "gscn", r"SS_{REF} = 3000\,\mathrm{MHz} + N \cdot 1.44\,\mathrm{MHz},\quad GSCN = 7499 + N",
        [inp("GSCN", gscn, source)],
        [f"N = {gscn} − 7499 = {g.n}", f"SS_REF = 3000 MHz + {g.n} × 1.44 MHz = {fmt(g.ss_ref_hz / 1e6, 8)} MHz"],
        g.ss_ref_hz / 1e6, "MHz", "TS 38.104 5.4.3.1")


def derive_pci(b: ResultBuilder, nid1: int, nid2: int, src: str) -> str:
    return b.derive(
        "pci", r"N_{ID}^{cell} = 3 N_{ID}^{(1)} + N_{ID}^{(2)}",
        [inp("N_ID^(1)", nid1, f"{src}.nid1 (SSS)"), inp("N_ID^(2)", nid2, f"{src}.nid2 (PSS)")],
        [f"3 × {nid1} + {nid2} = {raster.pci(nid1, nid2)}"], raster.pci(nid1, nid2), "", "TS 38.211 7.4.2.1")


def assemble(stage: StageDef, raw: dict[str, Any], ctx: Ctx) -> StageResult:
    b = ResultBuilder(stage)
    m = raw.get("measurements", {})
    cells: list[dict[str, Any]] = m.get("cells", [])
    candidates: list[dict[str, Any]] = ctx.params.get("candidates", [])
    ann = stage.data["annotations"]

    spec = raw.get("plots", {}).get("spectrum")
    if spec and spec.get("freq_hz"):
        xs, ys = thin([f / 1e6 for f in spec["freq_hz"]], spec["psd_db"])
        found = {c["gscn"] for c in cells}
        marks = [PlotAnnotation(kind="vline", x=c["ss_ref_hz"] / 1e6, term="gscn",
                                label=f"GSCN {c['gscn']}" + (f" · PCI {next(x['pci'] for x in cells if x['gscn'] == c['gscn'])}" if c["gscn"] in found else ""),
                                description=ann["detected"] if c["gscn"] in found else ann["candidate"],
                                category=0 if c["gscn"] in found else 1) for c in candidates]
        b.plot(Plot(id="spectrum", type="spectrum", title=b.plot_text("spectrum", "title"),
                    caption=b.plot_text("spectrum", "caption"),
                    x=PlotAxis(label=b.plot_text("spectrum", "x"), unit="MHz"),
                    y=PlotAxis(label=b.plot_text("spectrum", "y"), unit="dB"),
                    series=[PlotSeries(name="PSD", x=xs, y=ys, role="primary", mode="line")], annotations=marks))

    if (ctx.capture.get("device_stages") or {}).get("ssb") == "no":
        b.diag("RSSI_ONLY_DEVICE", default_level="warn", detail=ctx.capture.get("device_note"))
    if not raw.get("ok") or not cells:
        b.diag(raw.get("error_code") or "NO_CELL", detail=raw.get("error_detail") or None)
        return b.build("fail", n_candidates=m.get("n_candidates", len(candidates)),
                       threshold=ctx.params.get("detect_threshold_db", 8))

    best = cells[0]
    d_gscn = derive_gscn(b, best["gscn"], "scan.cells[0].gscn")
    d_pci = derive_pci(b, best["nid1"], best["nid2"], "scan.cells[0]")
    freq_mhz = raster.gscn_to_freq(best["gscn"]).ss_ref_hz / 1e6
    b.measured("n_cells", len(cells), primary=True)
    b.derived("best_freq", freq_mhz, d_gscn, primary=True)
    b.measured("best_gscn", best["gscn"])
    b.derived("best_pci", best["pci"], d_pci, primary=True)
    b.measured("best_pnr", round(best["peak_to_noise_db"], 1))
    b.measured("best_cfo", round(best["cfo_hz"]))

    col = stage.data["columns"]
    b.plot(Plot(id="cells", type="table", title=b.plot_text("cells", "title"), caption=b.plot_text("cells", "caption"),
                table=PlotTable(
                    columns=[PlotColumn(key="gscn", label=col["gscn"], term="gscn", align="right"),
                             PlotColumn(key="freq_mhz", label=col["freq_mhz"], unit="MHz", align="right"),
                             PlotColumn(key="ssb_scs_khz", label=col["ssb_scs_khz"], unit="kHz", term="scs", align="right"),
                             PlotColumn(key="pci", label=col["pci"], term="pci", align="right"),
                             PlotColumn(key="pnr_db", label=col["pnr_db"], unit="dB", align="right"),
                             PlotColumn(key="cfo_hz", label=col["cfo_hz"], unit="Hz", term="cfo", align="right"),
                             PlotColumn(key="rel_power_db", label=col["rel_power_db"], unit="dB", align="right"),
                             PlotColumn(key="n_ssb", label=col["n_ssb"], align="right")],
                    rows=[{"gscn": c["gscn"], "freq_mhz": round(c["ss_ref_hz"] / 1e6, 3), "ssb_scs_khz": c["ssb_scs_khz"],
                           "pci": c["pci"], "pnr_db": round(c["peak_to_noise_db"], 1), "cfo_hz": round(c["cfo_hz"]),
                           "rel_power_db": round(c["rel_power_db"], 1), "n_ssb": c["n_ssb_detected"]} for c in cells],
                    select_key="gscn"),
                annotations=[]))
    b.next_inputs = {"cells": cells, "selected_gscn": best["gscn"]}
    return b.build("ok", count=len(cells), freq_mhz=fmt(freq_mhz, 8), gscn=best["gscn"], pci=best["pci"],
                   pnr=fmt(best["peak_to_noise_db"], 3))
