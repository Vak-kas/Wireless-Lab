"""단계 1 — SSB 동기."""

from __future__ import annotations

from typing import Any

from ..contracts_gen import PlotGrid, StageResult
from ..nr import ssb as nrssb
from ..pipeline import StageDef
from ..result import ResultBuilder, fmt, inp
from .base import Ctx, Plot, PlotAnnotation, PlotAxis, PlotSeries
from .scan import derive_pci

CATEGORY_NAMES = ["PSS", "SSS", "PBCH", "PBCH DM-RS"]
CATEGORY_TERMS = ["pss", "sss", "pbch", "dmrs"]
LOW_SINR_DB = 3.0


def assemble(stage: StageDef, raw: dict[str, Any], ctx: Ctx) -> StageResult:
    b = ResultBuilder(stage)
    m = raw.get("measurements", {})
    plots = raw.get("plots", {})
    ann = stage.data["annotations"]
    fs = float(ctx.capture["sample_rate_hz"])
    search = m.get("cfo_search_hz", ctx.params.get("cfo_search_hz", 0))

    corr = plots.get("correlation")
    if corr and corr.get("lag_samples"):
        peak = corr.get("peak") or {}
        series = [PlotSeries(name=f"N_ID2 = {k}", x=[lag / fs * 1e3 for lag in corr["lag_samples"]], y=mag,
                             role="accent" if k == peak.get("nid2") else "muted", mode="line")
                  for k, mag in enumerate(corr["mag"])]
        marks = [PlotAnnotation(kind="vline", x=peak["lag"] / fs * 1e3, label=ann["peak"], term="pss")] if peak else []
        b.plot(Plot(id="correlation", type="correlation", title=b.plot_text("correlation", "title"),
                    caption=b.plot_text("correlation", "caption"),
                    x=PlotAxis(label=b.plot_text("correlation", "x"), unit="ms"),
                    y=PlotAxis(label=b.plot_text("correlation", "y"), min=0, max=1), series=series, annotations=marks))

    if not raw.get("ok"):
        b.diag(raw.get("error_code") or "NO_SSB", detail=raw.get("error_detail") or None)
        return b.build("fail", cfo_search_khz=fmt(search / 1e3))

    pci = m["pci"]
    l_max = int(ctx.cell.get("lmax") or ctx.params.get("lmax") or 4)
    idx_lsb, hrf = nrssb.split_ibar(m["ibar_ssb"], l_max)

    grid = plots.get("ssb_grid")
    if grid:
        mag = grid["mag"]
        cats = [[nrssb.ssb_category(k, s, pci) for s in range(4)] for k in range(len(mag))]
        b.plot(Plot(id="ssb_grid", type="resource_grid", title=b.plot_text("ssb_grid", "title"),
                    caption=b.plot_text("ssb_grid", "caption"),
                    x=PlotAxis(label=b.plot_text("ssb_grid", "x")), y=PlotAxis(label=b.plot_text("ssb_grid", "y")),
                    grid=PlotGrid(rows=len(mag), cols=4, values=mag, categories=cats, category_names=CATEGORY_NAMES,
                                  category_terms=CATEGORY_TERMS),
                    annotations=[PlotAnnotation(kind="region", label=name, description=ann[name], term=term, category=i)
                                 for i, (name, term) in enumerate(zip(CATEGORY_NAMES, CATEGORY_TERMS, strict=True))]))
    con = plots.get("constellation")
    if con:
        b.plot(Plot(id="constellation", type="constellation", title=b.plot_text("constellation", "title"),
                    caption=b.plot_text("constellation", "caption"),
                    x=PlotAxis(label="I", min=-1.5, max=1.5), y=PlotAxis(label="Q", min=-1.5, max=1.5),
                    series=[PlotSeries(name="PBCH", x=con["re"], y=con["im"], role="primary", mode="points")],
                    annotations=[]))

    d_pci = derive_pci(b, m["nid1"], m["nid2"], "ssb")
    t_us = m["timing_offset_samples"] / fs * 1e6
    d_t = b.derive("timing_us", r"t = \frac{n}{f_s}",
                   [inp("n", m["timing_offset_samples"], "ssb.timing_offset_samples", "samples"),
                    inp("f_s", fs, "capture.sample_rate", "Hz")],
                   [f"{m['timing_offset_samples']} / {fmt(fs, 9)} Hz = {fmt(t_us, 7)} µs"], round(t_us, 2), "µs", "TS 38.211 4.1")
    cfo = m["cfo_hz"]
    d_cfo = b.derive("cfo_total", r"\Delta f = \Delta f_{coarse} + \Delta f_{fine}",
                     [inp("Δf_coarse", m["cfo_coarse_hz"], "ssb.cfo_coarse_hz (PSS hypothesis)", "Hz"),
                      inp("Δf_fine", m["cfo_fine_hz"], "ssb.cfo_fine_hz (CP phase)", "Hz")],
                     [f"{fmt(m['cfo_coarse_hz'])} + {fmt(m['cfo_fine_hz'])} = {fmt(cfo, 7)} Hz"], round(cfo, 1), "Hz",
                     "TS 38.211 5.3.1")
    fc = float(ctx.cell.get("ss_ref_hz") or ctx.capture["center_freq_hz"])
    ppm = cfo / fc * 1e6
    d_ppm = b.derive("cfo_ppm", r"\mathrm{ppm} = \frac{\Delta f}{f_c} \times 10^6",
                     [inp("Δf", round(cfo, 1), "ssb.cfo_hz", "Hz"), inp("f_c", fc, "SS_REF", "Hz")],
                     [f"{fmt(cfo, 7)} / {fmt(fc, 10)} × 10⁶ = {fmt(ppm, 4)} ppm"], round(ppm, 3), "ppm", "TS 38.104 5.4.3.1")
    if l_max == 4:
        d_idx = b.derive("ssb_index", r"\bar{i}_{SSB} = i_{SSB} + 4 n_{hf}",
                         [inp("ī_SSB", m["ibar_ssb"], "ssb.ibar_ssb (PBCH DM-RS)"), inp("L_max", l_max, "TS 38.213 4.1")],
                         [f"i_SSB = {m['ibar_ssb']} mod 4 = {idx_lsb}", f"n_hf = ⌊{m['ibar_ssb']} / 4⌋ = {hrf}"],
                         idx_lsb, "", "TS 38.211 7.4.1.4.1")
    else:
        d_idx = b.derive("ssb_index", r"\bar{i}_{SSB} = i_{SSB} \bmod 8",
                         [inp("ī_SSB", m["ibar_ssb"], "ssb.ibar_ssb (PBCH DM-RS)"), inp("L_max", l_max, "TS 38.213 4.1")],
                         [f"i_SSB (3 LSB) = {idx_lsb}"], idx_lsb, "", "TS 38.211 7.4.1.4.1")

    b.derived("pci", pci, d_pci, primary=True)
    b.measured("nid1", m["nid1"])
    b.measured("nid2", m["nid2"])
    b.derived("ssb_index", idx_lsb, d_idx, raw=m["ibar_ssb"], primary=True)
    b.measured("timing_samples", m["timing_offset_samples"])
    b.derived("timing_us", round(t_us, 2), d_t)
    b.derived("cfo_hz", round(cfo, 1), d_cfo, primary=True)
    b.derived("cfo_ppm", round(ppm, 3), d_ppm)
    b.measured("cfo_search", f"±{fmt(search / 1e3)}")
    b.measured("rsrp", round(m["rsrp_dbfs"], 1))
    b.measured("sinr", round(m["sinr_db"], 1), primary=True)

    b.diag("RSRP_UNCALIBRATED")
    if ctx.cell.get("ntn"):
        b.diag("WIDE_CFO_SEARCH")
    low = m["sinr_db"] < LOW_SINR_DB or "LOW_SNR" in raw.get("warnings", [])
    if low:
        b.diag("LOW_SNR")
    if "DMRS_AMBIGUOUS" in raw.get("warnings", []):
        b.diag("DMRS_AMBIGUOUS")
    b.next_inputs = {"pci": pci, "ssb_index_lsb": idx_lsb, "half_frame_from_dmrs": hrf, "lmax": l_max}
    return b.build("partial" if low else "ok", pci=pci, ssb_index=idx_lsb, timing_us=fmt(t_us, 6), cfo_hz=fmt(cfo, 6),
                   cfo_ppm=fmt(ppm, 3), sinr=fmt(m["sinr_db"], 3))
