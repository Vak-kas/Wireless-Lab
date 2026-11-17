"""단계 3 — SIB1. PDCCH/PDSCH 복호 결과(전송 블록)를 ASN.1로 풀고 요약 카드와 계산 과정을 만든다."""

from __future__ import annotations

from typing import Any

from ..asn1 import rrc
from ..contracts_gen import PlotGrid, StageResult
from ..nr import sched
from ..pipeline import StageDef
from ..result import ResultBuilder, fmt, inp
from .base import Ctx, Plot, PlotAnnotation, PlotAxis, PlotColumn, PlotSeries, PlotTable

GRID_CATEGORIES = ["CORESET0", "PDCCH", "PDSCH", "PDSCH DM-RS"]
GRID_TERMS = ["coreset0", "pdcch", "pdsch", "dmrs"]
P = "SIB1"


def si_messages(sib1: dict[str, Any]) -> list[dict[str, Any]]:
    """SIB1의 SI 시간표(기본 목록 + Rel-17 확장 목록)를 한 목록으로. 각 항목: sibs, period, n(창 순서/위치), broadcasting, list."""
    out: list[dict[str, Any]] = []
    info = sib1.get("si-SchedulingInfo") or {}
    for n, s in enumerate(info.get("schedulingInfoList", []), start=1):
        out.append({"sibs": [x["type"].replace("sibType", "SIB") for x in s["sib-MappingInfo"]],
                    "period": s["si-Periodicity"], "n": n, "broadcasting": s["si-BroadcastStatus"] == "broadcasting",
                    "list": "schedulingInfoList"})
    v1700 = rrc.find_path(sib1, "nonCriticalExtension", "nonCriticalExtension", "nonCriticalExtension") or {}
    for s in (v1700.get("si-SchedulingInfo-v1700") or {}).get("schedulingInfoList2-r17", []):
        names = []
        for x in s["sib-MappingInfo-r17"]:
            kind, val = x["sibType-r17"]
            names.append(val.replace("sibType", "SIB").split("-")[0] if kind == "type1-r17" else "posSIB")
        out.append({"sibs": names, "period": s["si-Periodicity-r17"], "n": s["si-WindowPosition-r17"],
                    "broadcasting": s["si-BroadcastStatus-r17"] == "broadcasting", "list": "schedulingInfoList2-r17"})
    return out


def assemble(stage: StageDef, raw: dict[str, Any], ctx: Ctx) -> StageResult:
    b = ResultBuilder(stage)
    m = raw.get("measurements", {})
    plots = raw.get("plots", {})
    ann = stage.data["annotations"]

    g = plots.get("coreset_grid")
    if g:
        mag = g["mag"]
        cats = [[-1] * len(mag[0]) for _ in mag]
        for reg in g.get("regions", []):
            ci = GRID_CATEGORIES.index(reg["name"])
            for r in range(reg["rb0"], reg["rb1"] + 1):
                for c in range(reg["sym0"], reg["sym1"] + 1):
                    if reg["name"] != "PDSCH DM-RS" or cats[r][c] in (-1, 2):
                        cats[r][c] = ci
        b.plot(Plot(id="coreset_grid", type="resource_grid", title=b.plot_text("coreset_grid", "title"),
                    caption=b.plot_text("coreset_grid", "caption"),
                    x=PlotAxis(label=b.plot_text("coreset_grid", "x")), y=PlotAxis(label=b.plot_text("coreset_grid", "y")),
                    grid=PlotGrid(rows=len(mag), cols=len(mag[0]), values=mag, categories=cats,
                                  category_names=GRID_CATEGORIES, category_terms=GRID_TERMS),
                    annotations=[PlotAnnotation(kind="region", label=n, description=ann[n], term=t, category=i)
                                 for i, (n, t) in enumerate(zip(GRID_CATEGORIES, GRID_TERMS, strict=True))]))

    if not raw.get("ok"):
        code = raw.get("error_code") or "NO_PDCCH"
        b.diag(code, detail=raw.get("error_detail") or None)
        return b.build("fail", reason=code)

    tb_hex = raw["bits"]["tb_hex"]
    try:
        value, tree = rrc.decode("BCCH-DL-SCH-Message", bytes.fromhex(tb_hex))
        sib1 = rrc.find_path(value, "message", "c1", "systemInformationBlockType1")
        if sib1 is None:
            raise rrc.Asn1Error("not SIB1")
    except rrc.Asn1Error as e:
        b.diag("ASN1_FAIL", detail=f"{e} / {tb_hex}")
        return b.build("fail", reason="ASN1_FAIL")

    con = plots.get("constellation")
    if con:
        b.plot(Plot(id="constellation", type="constellation", title=b.plot_text("constellation", "title"),
                    caption=b.plot_text("constellation", "caption"),
                    x=PlotAxis(label="I", min=-1.5, max=1.5), y=PlotAxis(label="Q", min=-1.5, max=1.5),
                    series=[PlotSeries(name="PDSCH", x=con["re"], y=con["im"], role="primary", mode="points")], annotations=[]))

    # --- 통신망과 셀 ---
    info = sib1["cellAccessRelatedInfo"]["plmn-IdentityInfoList"][0]
    ident = info["plmn-IdentityList"][0]
    plmn = sched.plmn_string(ident.get("mcc", []), ident["mnc"])
    b.decoded("plmn", plmn, f"{P}.cellAccessRelatedInfo.plmn-IdentityInfoList[0].plmn-IdentityList[0]", primary=True)
    if "trackingAreaCode" in info:
        b.decoded("tac", f"0x{info['trackingAreaCode'][0]:06X}", f"{P}.…trackingAreaCode", raw=info["trackingAreaCode"][0], primary=True)
    b.decoded("cell_id", f"0x{info['cellIdentity'][0]:09X}", f"{P}.…cellIdentity", raw=info["cellIdentity"][0])
    q = (sib1.get("cellSelectionInfo") or {}).get("q-RxLevMin")
    if q is not None:
        d = b.derive("q_rxlevmin", r"Q_{rxlevmin} = 2 \cdot \mathrm{q\text{-}RxLevMin}\ \mathrm{[dBm]}",
                     [inp("q-RxLevMin", q, f"{P}.cellSelectionInfo.q-RxLevMin")], [f"2 × {q} = {2 * q} dBm"], 2 * q, "dBm",
                     "TS 38.331 6.3.2 SIB1 / TS 38.304 5.2.3.2")
        b.derived("q_rxlevmin", 2 * q, d, raw=q)

    # --- 주파수 ---
    scc = sib1.get("servingCellConfigCommon") or {}
    dl = scc.get("downlinkConfigCommon") or {}
    fdl = dl.get("frequencyInfoDL") or {}
    if fdl:
        band = fdl["frequencyBandList"][0].get("freqBandIndicatorNR")
        carrier = fdl["scs-SpecificCarrierList"][0]
        scs = sched.SCS_KHZ[carrier["subcarrierSpacing"]]
        n_rb = carrier["carrierBandwidth"]
        b.decoded("band", f"n{band}", f"{P}.…frequencyInfoDL.frequencyBandList[0]", raw=band)
        b.decoded("offset_to_point_a", fdl["offsetToPointA"], f"{P}.…frequencyInfoDL.offsetToPointA")
        b.decoded("carrier_bw", n_rb, f"{P}.…scs-SpecificCarrierList[0].carrierBandwidth")
        bw = n_rb * 12 * scs / 1000
        d = b.derive("carrier_bw_mhz", r"BW = N_{RB} \cdot 12 \cdot \Delta f",
                     [inp("N_RB", n_rb, f"{P}.…carrierBandwidth"), inp("Δf", scs, f"{P}.…subcarrierSpacing", "kHz")],
                     [f"{n_rb} × 12 × {scs} kHz = {fmt(bw)} MHz"], bw, "MHz", "TS 38.211 4.4.4.1")
        b.derived("carrier_bw_mhz", bw, d)
        lab = dl["initialDownlinkBWP"]["genericParameters"]["locationAndBandwidth"]
        start, length = sched.riv_decode(lab, 275)
        d = b.derive("initial_bwp", r"RIV = N(L-1) + RB_{start}\ \ (N = 275)",
                     [inp("locationAndBandwidth", lab, f"{P}.…initialDownlinkBWP.genericParameters")],
                     [f"L = ⌊{lab} / 275⌋ + 1 = {lab // 275 + 1}", f"RB_start = {lab} mod 275 = {lab % 275}",
                      f"→ RB_start = {start}, L = {length}"], length, "RB", "TS 38.214 5.1.2.2.2")
        b.derived("initial_bwp", f"RB {start} – {start + length - 1} ({length} RB)", d, raw=lab)

    # --- RACH ---
    rach = rrc.find_path(scc, "uplinkConfigCommon", "initialUplinkBWP", "rach-ConfigCommon", "setup")
    if rach:
        gen = rach["rach-ConfigGeneric"]
        rp = f"{P}.…rach-ConfigCommon"
        b.decoded("prach_config_index", gen["prach-ConfigurationIndex"], f"{rp}.rach-ConfigGeneric.prach-ConfigurationIndex")
        b.decoded("msg1_fdm", gen["msg1-FDM"], f"{rp}.rach-ConfigGeneric.msg1-FDM")
        b.decoded("msg1_freq_start", gen["msg1-FrequencyStart"], f"{rp}.rach-ConfigGeneric.msg1-FrequencyStart")
        b.decoded("zczc", gen["zeroCorrelationZoneConfig"], f"{rp}.rach-ConfigGeneric.zeroCorrelationZoneConfig")
        kind, root = rach["prach-RootSequenceIndex"]
        b.decoded("root_seq", f"{root} ({kind})", f"{rp}.prach-RootSequenceIndex", raw=root)
        b.decoded("ra_window", int(gen["ra-ResponseWindow"][2:]), f"{rp}.rach-ConfigGeneric.ra-ResponseWindow", raw=gen["ra-ResponseWindow"])
        if "msg1-SubcarrierSpacing" in rach:
            b.decoded("msg1_scs", sched.SCS_KHZ[rach["msg1-SubcarrierSpacing"]], f"{rp}.msg1-SubcarrierSpacing", raw=rach["msg1-SubcarrierSpacing"])

    # --- SSB, 타이밍 ---
    if scc:
        kind, bits = next(iter(scc["ssb-PositionsInBurst"].items()))
        b.decoded("ssb_positions", format(bits[0], f"0{bits[1]}b"), f"{P}.servingCellConfigCommon.ssb-PositionsInBurst.{kind}")
        b.decoded("ssb_period", sched.SSB_PERIOD_MS[scc["ssb-PeriodicityServingCell"]], f"{P}.servingCellConfigCommon.ssb-PeriodicityServingCell",
                  raw=scc["ssb-PeriodicityServingCell"])
        nta = scc.get("n-TimingAdvanceOffset")
        if nta:
            d = b.derive("n_ta_offset", r"N_{TA,offset} = \mathrm{n\text{-}TimingAdvanceOffset}\ [T_c]",
                         [inp("n-TimingAdvanceOffset", nta, f"{P}.servingCellConfigCommon")],
                         [f"{nta} → {sched.N_TA_OFFSET[nta]} Tc"], sched.N_TA_OFFSET[nta], "Tc", "TS 38.133 7.1.2 / TS 38.211 4.3.1")
            b.derived("n_ta_offset", sched.N_TA_OFFSET[nta], d, raw=nta)
        tdd = scc.get("tdd-UL-DL-ConfigurationCommon")
        b.decoded("tdd", "TDD" if tdd else "FDD", f"{P}.servingCellConfigCommon.tdd-UL-DL-ConfigurationCommon")

    # --- SI 시간표 ---
    msgs = si_messages(sib1)
    win = (sib1.get("si-SchedulingInfo") or {}).get("si-WindowLength")
    mib_res = ctx.prior.get("mib", {}).get("resolved", {})
    scs_c = int(mib_res.get("scs_common_khz", 15))
    slots_per_frame = 10 * scs_c // 15
    names = [s for msg in msgs if msg["broadcasting"] for s in msg["sibs"]]
    has19 = "SIB19" in names
    if win:
        b.decoded("si_window", sched.SI_WINDOW_SLOTS[win], f"{P}.si-SchedulingInfo.si-WindowLength", raw=win)
    b.decoded("si_list", names, f"{P}.si-SchedulingInfo (+ si-SchedulingInfo-v1700)", primary=True)
    b.decoded("has_sib19", has19, f"{P}.…si-SchedulingInfo-v1700.schedulingInfoList2-r17", primary=True)
    col = stage.data["columns"]
    rows = []
    for msg in msgs:
        w = sched.si_window(msg["n"], win, msg["period"], slots_per_frame) if win else None
        rows.append({"sib": ", ".join(msg["sibs"]), "period": f"{sched.SI_PERIOD_FRAMES[msg['period']] * 10} ms",
                     "window": f"SFN mod {w.period_frames} = {w.frame_offset}, slot {w.slot}" if w else "",
                     "status": msg["broadcasting"]})
        if w and "SIB19" in msg["sibs"]:
            d = b.derive("si_window", r"x = (n-1) \cdot w,\quad a = x \bmod N,\quad SFN \bmod T = \lfloor x / N \rfloor",
                         [inp("n", msg["n"], f"{P}.…{msg['list']}"), inp("w", w.window_slots, f"{P}.si-SchedulingInfo.si-WindowLength", "slots"),
                          inp("N", slots_per_frame, "slots per frame"), inp("T", w.period_frames, f"{P}.…si-Periodicity", "frames")],
                         [f"x = ({msg['n']} − 1) × {w.window_slots} = {w.x}", f"a = {w.x} mod {slots_per_frame} = {w.slot}",
                          f"SFN mod {w.period_frames} = ⌊{w.x} / {slots_per_frame}⌋ = {w.frame_offset}"],
                         w.slot, "slot", "TS 38.331 5.2.2.3.2")
            b.derived("sib19_window_start", f"SFN mod {w.period_frames} = {w.frame_offset}, slot {w.slot}", d)
            b.next_inputs["sib19_window"] = {"period_frames": w.period_frames, "frame_offset": w.frame_offset, "slot": w.slot,
                                             "window_slots": w.window_slots, "slots_per_frame": slots_per_frame}
    b.plot(Plot(id="si_schedule", type="table", title=b.plot_text("si_schedule", "title"), caption=b.plot_text("si_schedule", "caption"),
                table=PlotTable(columns=[PlotColumn(key="sib", label=col["sib"]), PlotColumn(key="period", label=col["period"]),
                                         PlotColumn(key="window", label=col["window"], term="si_window"),
                                         PlotColumn(key="status", label=col["status"])], rows=rows), annotations=[]))
    v1700 = rrc.find_path(sib1, "nonCriticalExtension", "nonCriticalExtension", "nonCriticalExtension") or {}
    if "cellBarredNTN-r17" in v1700:
        b.decoded("cell_barred_ntn", v1700["cellBarredNTN-r17"], f"{P}.…SIB1-v1700-IEs.cellBarredNTN-r17")

    # --- DCI ---
    dci = m.get("dci") or {}
    if dci:
        n_bwp = int(m.get("n_rb_coreset0") or mib_res.get("coreset0", {}).get("n_rb") or 24)
        start, length = sched.riv_decode(dci["riv"], n_bwp)
        d = b.derive("riv", r"RIV = N(L-1) + RB_{start}\ \ \left(L - 1 \le \lfloor N/2 \rfloor\right),\quad N = N_{RB}^{CORESET0}",
                     [inp("RIV", dci["riv"], "DCI 1_0 frequency domain resource assignment"), inp("N", n_bwp, "CORESET0 size", "RB")],
                     [f"L = ⌊{dci['riv']} / {n_bwp}⌋ + 1 = {dci['riv'] // n_bwp + 1}", f"RB_start = {dci['riv']} mod {n_bwp} = {dci['riv'] % n_bwp}",
                      f"→ RB_start = {start}, L = {length}"], length, "RB", "TS 38.214 5.1.2.2.2")
        b.measured("dci_al", m.get("al"))
        b.decoded("dci_riv", dci["riv"], "DCI 1_0 frequency domain resource assignment")
        b.derived("dci_rb", f"{start} – {start + length - 1} ({length} RB)", d)
        b.decoded("dci_tdra", dci["tdra"], "DCI 1_0 time domain resource assignment")
        if m.get("sym_len"):
            b.measured("dci_symbols", f"{m['sym_start']} – {m['sym_start'] + m['sym_len'] - 1}")
        b.decoded("dci_mcs", dci["mcs"], "DCI 1_0 modulation and coding scheme")
        b.decoded("dci_rv", dci["rv"], "DCI 1_0 redundancy version")
        b.decoded("dci_si_indicator", dci["si_indicator"], "DCI 1_0 system information indicator")
        b.measured("tbs", m.get("tbs"))
        summary = {"al": m.get("al"), "riv": dci["riv"], "rb_start": start, "rb_len": length, "mcs": dci["mcs"], "tbs": m.get("tbs")}
    else:
        summary = {"al": "-", "riv": "-", "rb_start": "-", "rb_len": "-", "mcs": "-", "tbs": len(tb_hex) * 4}

    b.tree("sib1", "BCCH-DL-SCH-Message (SIB1)", tree)
    raw["decoded"] = {"sib1": tree["message"]["c1"]["systemInformationBlockType1"], "hex": tb_hex, "si_messages": msgs}
    b.next_inputs |= {"has_sib19": has19, "si_messages": msgs, "si_window": win}
    if not has19:
        b.diag("NO_SIB19", default_level="info")
    return b.build("ok", plmn=plmn, si_count=len(names), **summary)
