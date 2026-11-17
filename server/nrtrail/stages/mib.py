"""단계 2 — MIB. PBCH 복호 결과(24비트)를 ASN.1로 풀고, SIB1을 찾는 데 필요한 값을 계산한다."""

from __future__ import annotations

from typing import Any

from ..asn1 import rrc
from ..contracts_gen import StageResult
from ..nr import ssb as nrssb
from ..nr import type0
from ..pipeline import StageDef
from ..result import ResultBuilder, fmt, inp
from .base import Ctx, Plot, PlotColumn, PlotTable

# BCCH-BCH-Message 24비트 안의 위치(1부터, MSB 먼저). 첫 비트는 메시지 종류 CHOICE. TS 38.331 6.2.2 MIB
BITS = {
    "systemFrameNumber": "2-7", "subCarrierSpacingCommon": "8", "ssb-SubcarrierOffset": "9-12",
    "dmrs-TypeA-Position": "13", "pdcch-ConfigSIB1": "14-21", "cellBarred": "22",
    "intraFreqReselection": "23", "spare": "24",
}


def scs_common_khz(value: str, fr2: bool = False) -> int:
    """subCarrierSpacingCommon: FR1에서 scs15or60=15 kHz, scs30or120=30 kHz. TS 38.331 MIB 필드 설명."""
    table = {"scs15or60": (15, 60), "scs30or120": (30, 120)}
    return table[value][1 if fr2 else 0]


def assemble(stage: StageDef, raw: dict[str, Any], ctx: Ctx) -> StageResult:
    b = ResultBuilder(stage)
    m = raw.get("measurements", {})
    if not raw.get("ok") or not m.get("crc_ok"):
        b.diag(raw.get("error_code") or "PBCH_CRC_FAIL", detail=raw.get("error_detail") or None)
        return b.build("fail")

    hexstr = raw["bits"]["bch_trblk_hex"]
    value, tree = rrc.decode("BCCH-BCH-Message", bytes.fromhex(hexstr))
    mib = rrc.find_path(value, "message", "mib")
    sfn_msb = mib["systemFrameNumber"][0]
    k_lsb = mib["ssb-SubcarrierOffset"]
    pdcch_cfg = mib["pdcch-ConfigSIB1"]["controlResourceSetZero"] * 16 + mib["pdcch-ConfigSIB1"]["searchSpaceZero"]
    scs_c = scs_common_khz(mib["subCarrierSpacingCommon"])
    dmrs_pos = 2 if mib["dmrs-TypeA-Position"] == "pos2" else 3

    ssb_m = ctx.prior["ssb"]["measurements"]
    l_max = int(m.get("lmax") or ctx.cell.get("lmax") or 4)
    idx_lsb, _ = nrssb.split_ibar(ssb_m["ibar_ssb"], l_max)
    hrf = int(m["half_frame"])
    ssb_index = idx_lsb  # FR1(L_max <= 8)에서는 DM-RS의 비트가 SSB 번호 전체다
    # msb_idx_offset = a_{A+5..A+7}을 a_{A+5}가 MSB인 3비트 정수. L_max 4/8에서는 a_{A+5}가 k_SSB의 MSB다 (TS 38.212 7.1.1).
    k_msb = (int(m["msb_idx_offset"]) >> 2) & 1 if l_max != 64 else 0
    sfn = nrssb.full_sfn(sfn_msb, int(m["sfn_4lsb"]))
    k = nrssb.k_ssb(k_msb, k_lsb)
    present = nrssb.sib1_present_fr1(k)

    # --- 계산 과정 ---
    d_sfn = b.derive("sfn", r"SFN = 16 \cdot SFN_{MSB6} + SFN_{LSB4}",
                     [inp("SFN_MSB6", sfn_msb, "MIB.systemFrameNumber"), inp("SFN_LSB4", m["sfn_4lsb"], "PBCH payload a_{A}..a_{A+3}")],
                     [f"16 × {sfn_msb} + {m['sfn_4lsb']} = {sfn}"], sfn, "", "TS 38.212 7.1.1")
    d_idx = b.derive("ssb_index", r"i_{SSB} = \bar{i}_{SSB} \bmod L_{max}" if l_max == 4 else r"i_{SSB} = \bar{i}_{SSB}",
                     [inp("ī_SSB", ssb_m["ibar_ssb"], "ssb.ibar_ssb (PBCH DM-RS)"), inp("L_max", l_max, "TS 38.213 4.1")],
                     [f"i_SSB = {ssb_index}"], ssb_index, "", "TS 38.213 4.1")
    d_k = b.derive("k_ssb", r"k_{SSB} = 16 \cdot k_{MSB} + k_{LSB4},\quad k_{SSB} \le 23 \Rightarrow \text{CORESET0}",
                   [inp("k_MSB", k_msb, "PBCH payload a_{A+5}"), inp("k_LSB4", k_lsb, "MIB.ssb-SubcarrierOffset")],
                   [f"16 × {k_msb} + {k_lsb} = {k}", f"{k} {'≤' if present else '>'} 23"], k, "", "TS 38.213 13")
    crs0, ss0 = pdcch_cfg >> 4, pdcch_cfg & 0xF
    d_cfg = b.derive("pdcch_config", r"\mathrm{controlResourceSetZero} = \lfloor v / 16 \rfloor,\quad \mathrm{searchSpaceZero} = v \bmod 16",
                     [inp("v", pdcch_cfg, "MIB.pdcch-ConfigSIB1")],
                     [f"⌊{pdcch_cfg} / 16⌋ = {crs0}", f"{pdcch_cfg} mod 16 = {ss0}"], crs0, "", "TS 38.213 13")

    fs = float(ctx.capture["sample_rate_hz"])
    pattern = ctx.cell.get("pattern", "A")
    ssb_scs = int(ctx.cell.get("ssb_scs_khz", 15))
    fc = float(ctx.cell.get("ss_ref_hz") or ctx.capture["center_freq_hz"])
    starts = nrssb.burst_start_symbols(pattern, fc, bool(ctx.cell.get("paired", True)))
    sym = starts[ssb_index]
    off = hrf * 0.005 * fs + nrssb.symbol_start_in_half_frame(sym, ssb_scs, fs)
    frame_len = 0.010 * fs
    frame_start = (ssb_m["timing_offset_samples"] - off) % frame_len
    d_frame = b.derive("frame_start", r"n_{frame} = \left(n_{SSB} - n_{hf} \cdot 5\,\mathrm{ms} \cdot f_s - n_{sym}(l_{SSB})\right) \bmod (10\,\mathrm{ms} \cdot f_s)",
                       [inp("n_SSB", ssb_m["timing_offset_samples"], "ssb.timing_offset_samples"),
                        inp("n_hf", hrf, "PBCH payload a_{A+4}"), inp("i_SSB", ssb_index, "ssb.ibar_ssb"),
                        inp("l_SSB", sym, f"Case {pattern}"), inp("f_s", fs, "capture.sample_rate", "Hz")],
                       [f"Case {pattern}: l = {starts}", f"l_SSB = {sym} → n_sym = {fmt(nrssb.symbol_start_in_half_frame(sym, ssb_scs, fs), 9)}",
                        f"({ssb_m['timing_offset_samples']} − {fmt(off, 9)}) mod {fmt(frame_len, 9)} = {fmt(frame_start, 9)}"],
                       round(frame_start, 1), "samples", "TS 38.213 4.1")

    b.derived("sfn", sfn, d_sfn, raw=sfn_msb, primary=True)
    b.decoded("half_frame", hrf, "PBCH payload a_{A+4}")
    b.derived("ssb_index", ssb_index, d_idx)
    b.derived("k_ssb", k, d_k, raw=k_lsb, primary=True)
    b.derived("sib1_present", present, d_k)
    b.decoded("scs_common", scs_c, f"MIB.subCarrierSpacingCommon (bit {BITS['subCarrierSpacingCommon']})", raw=mib["subCarrierSpacingCommon"])
    b.decoded("dmrs_typea_pos", dmrs_pos, f"MIB.dmrs-TypeA-Position (bit {BITS['dmrs-TypeA-Position']})", raw=mib["dmrs-TypeA-Position"])
    b.decoded("pdcch_config_sib1", pdcch_cfg, f"MIB.pdcch-ConfigSIB1 (bits {BITS['pdcch-ConfigSIB1']})")
    b.derived("coreset0_index", crs0, d_cfg, primary=True)
    b.derived("ss0_index", ss0, d_cfg)
    b.decoded("cell_barred", mib["cellBarred"] == "notBarred", f"MIB.cellBarred (bit {BITS['cellBarred']})", raw=mib["cellBarred"], primary=True)
    b.decoded("intra_freq", mib["intraFreqReselection"] == "allowed", f"MIB.intraFreqReselection (bit {BITS['intraFreqReselection']})",
              raw=mib["intraFreqReselection"])
    b.derived("frame_start", round(frame_start, 1), d_frame)

    resolved: dict[str, Any] = {"sfn": sfn, "half_frame": hrf, "ssb_index": ssb_index, "k_ssb": k, "sib1_present": present,
                                "scs_common_khz": scs_c, "dmrs_typea_pos": dmrs_pos, "frame_start_sample": frame_start,
                                "lmax": l_max, "ssb_symbol": sym}
    status = "ok"
    if not present:
        b.diag("NO_SIB1_HERE", default_level="warn")
        status = "partial"
    else:
        try:
            cs = type0.coreset0(crs0, ssb_scs, scs_c, int(ctx.cell.get("min_bw_mhz", 5)))
            mon = type0.monitoring(ss0, ssb_index, scs_c, cs.n_sym)
        except type0.Type0Error as e:
            b.diag("NO_SIB1_HERE", default_level="warn", detail=str(e))
            status = "partial"
        else:
            d_cs = b.derive("coreset0", r"(N_{RB}^{CORESET}, N_{symb}^{CORESET}, \mathrm{offset}) = \mathrm{Table}(\mathrm{controlResourceSetZero})",
                            [inp("controlResourceSetZero", crs0, "MIB.pdcch-ConfigSIB1"), inp("SCS_SSB", ssb_scs, "scan", "kHz"),
                             inp("SCS_PDCCH", scs_c, "MIB.subCarrierSpacingCommon", "kHz")],
                            [f"Table {cs.table}, index {crs0}", f"N_RB = {cs.n_rb}, N_symb = {cs.n_sym}, offset = {cs.offset_rb} RB"],
                            cs.n_rb, "RB", f"TS 38.213 Table {cs.table}")
            bw = cs.bandwidth_hz / 1e6
            d_bw = b.derive("coreset0_bw", r"BW = N_{RB}^{CORESET} \cdot 12 \cdot \Delta f",
                            [inp("N_RB", cs.n_rb, f"TS 38.213 Table {cs.table}"), inp("Δf", scs_c, "MIB.subCarrierSpacingCommon", "kHz")],
                            [f"{cs.n_rb} × 12 × {scs_c} kHz = {fmt(bw)} MHz"], bw, "MHz", "TS 38.211 4.4.4.1")
            mu = {15: 0, 30: 1, 60: 2}[scs_c]
            d_mon = b.derive("monitor", r"n_0 = \left(O \cdot 2^{\mu} + \lfloor i \cdot M \rfloor\right) \bmod N_{slot}^{frame,\mu}",
                             [inp("searchSpaceZero", ss0, "MIB.pdcch-ConfigSIB1"), inp("O", mon.o, "TS 38.213 Table 13-11"),
                              inp("M", mon.m, "TS 38.213 Table 13-11"), inp("i", ssb_index, "ssb.ibar_ssb"), inp("μ", mu, "MIB.subCarrierSpacingCommon")],
                             [f"({fmt(mon.o)} × 2^{mu} + ⌊{ssb_index} × {fmt(mon.m)}⌋) mod {mon.slots_per_frame} = {mon.slot}",
                              f"SFN mod 2 = {mon.frame_parity}", f"first symbol = {mon.first_symbol}"], mon.slot, "", "TS 38.213 13")
            b.derived("coreset0_rbs", cs.n_rb, d_cs)
            b.derived("coreset0_symbols", cs.n_sym, d_cs)
            b.derived("coreset0_offset", cs.offset_rb, d_cs)
            b.derived("coreset0_bw", bw, d_bw)
            b.derived("monitor_slot", f"{mon.slot}, {mon.slot + 1}", d_mon)
            b.derived("monitor_symbol", mon.first_symbol, d_mon)
            pos = type0.crb_grid_from_ssb(fc, ssb_scs, k, cs.offset_rb, scs_c)
            resolved |= {"coreset0": {"table": cs.table, "n_rb": cs.n_rb, "n_sym": cs.n_sym, "offset_rb": cs.offset_rb,
                                      "scs_khz": scs_c, "low_hz": pos["coreset0_low_hz"], "crb_ssb_low_hz": pos["crb_ssb_low_hz"]},
                         "monitoring": {"slot": mon.slot, "frame_parity": mon.frame_parity, "first_symbol": mon.first_symbol,
                                        "sets_per_slot": mon.sets_per_slot, "slots_per_frame": mon.slots_per_frame}}
            centre = float(ctx.capture["center_freq_hz"])
            need = 2 * max(abs(pos["coreset0_low_hz"] - centre), abs(pos["coreset0_low_hz"] + cs.bandwidth_hz - centre))
            max_rate = float(ctx.capture.get("max_sample_rate_hz") or fs)
            if need > max_rate:
                b.diag("DEVICE_BW_TOO_NARROW", default_level="warn",
                       detail=f"need {fmt(need / 1e6)} MHz, device {fmt(max_rate / 1e6)} MHz")
    if mib["cellBarred"] == "barred":
        b.diag("CELL_BARRED", default_level="info")

    col = stage.data["columns"]
    fields = [("systemFrameNumber", sfn_msb), ("subCarrierSpacingCommon", mib["subCarrierSpacingCommon"]),
              ("ssb-SubcarrierOffset", k_lsb), ("dmrs-TypeA-Position", mib["dmrs-TypeA-Position"]),
              ("pdcch-ConfigSIB1", pdcch_cfg), ("cellBarred", mib["cellBarred"]),
              ("intraFreqReselection", mib["intraFreqReselection"])]
    meaning = {"systemFrameNumber": f"SFN = {sfn}", "subCarrierSpacingCommon": f"{scs_c} kHz", "ssb-SubcarrierOffset": f"k_SSB = {k}",
               "dmrs-TypeA-Position": f"symbol {dmrs_pos}", "pdcch-ConfigSIB1": f"CORESET0 #{crs0}, SS0 #{ss0}",
               "cellBarred": "", "intraFreqReselection": ""}
    b.plot(Plot(id="payload", type="table", title=b.plot_text("payload", "title"), caption=b.plot_text("payload", "caption"),
                table=PlotTable(columns=[PlotColumn(key="field", label=col["field"]), PlotColumn(key="bits", label=col["bits"]),
                                         PlotColumn(key="raw", label=col["raw"]), PlotColumn(key="meaning", label=col["meaning"])],
                                rows=[{"field": f, "bits": BITS[f], "raw": v, "meaning": meaning[f]} for f, v in fields]),
                annotations=[]))
    b.tree("mib", "BCCH-BCH-Message", tree)
    raw["decoded"] = {"mib": tree["message"]["mib"], "hex": hexstr}
    raw["resolved"] = resolved
    b.next_inputs = resolved
    return b.build(status, sfn=sfn, hrf=hrf, k_ssb=k, coreset0=crs0, ss0=ss0)
