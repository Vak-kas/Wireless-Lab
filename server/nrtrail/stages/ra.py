"""랜덤 액세스 관측(SPEC 11절, 테스트베드 전용). 하향 Msg2(RAR)와 Msg4만 읽는다. 상향(프리앰블, Msg3)은 관측하지 않는다."""

from __future__ import annotations

from typing import Any

from ..asn1 import rrc
from ..contracts_gen import PlotGrid, StageResult
from ..nr import ntn, ra
from ..pipeline import StageDef
from ..result import ResultBuilder, fmt, inp
from .base import Ctx, Plot, PlotAnnotation, PlotAxis
from .sib1 import GRID_CATEGORIES, GRID_TERMS


def rnti_inputs(prach: dict[str, Any], msg1_scs_khz: int) -> dict[str, int]:
    """SIB1의 PRACH 설정에서 첫 PRACH 기회의 s_id, t_id, f_id를 구한다."""
    t_id = ra.prach_slot_index(prach["subframes"][0], msg1_scs_khz, prach.get("slots_per_subframe"))
    return {"s_id": prach["start_symbol"], "t_id": t_id, "f_id": 0, "ul_carrier_id": 0}


def assemble(stage: StageDef, raw: dict[str, Any], ctx: Ctx) -> StageResult:
    b = ResultBuilder(stage)
    ids = ctx.params.get("rnti_inputs")
    if not ids:
        b.diag("NO_PRACH_CONFIG")
        return b.build("fail", reason="no PRACH configuration in SIB1")
    rnti = ra.ra_rnti(**ids)
    d_rnti = b.derive("ra_rnti", r"RA\text{-}RNTI = 1 + s_{id} + 14 \cdot t_{id} + 14 \cdot 80 \cdot f_{id} + 14 \cdot 80 \cdot 8 \cdot ul\_carrier_{id}",
                      [inp("s_id", ids["s_id"], "SIB1 prach-ConfigurationIndex → starting symbol"), inp("t_id", ids["t_id"], "SIB1 prach-ConfigurationIndex → PRACH slot"),
                       inp("f_id", ids["f_id"], "SIB1 msg1-FDM (first occasion)"), inp("ul_carrier_id", ids["ul_carrier_id"], "NUL carrier")],
                      [f"1 + {ids['s_id']} + 14 × {ids['t_id']} + 1120 × {ids['f_id']} + 8960 × {ids['ul_carrier_id']} = {rnti}"], rnti, "", "TS 38.321 5.1.3")
    b.derived("ra_rnti", rnti, d_rnti, primary=True)
    for key in ("s_id", "t_id", "f_id"):
        b.derived(key, ids[key], d_rnti)
    b.diag("UPLINK_NOT_OBSERVED", default_level="info")

    msg2, msg4 = raw.get("msg2") or {}, raw.get("msg4") or {}
    g = (msg2.get("plots") or {}).get("coreset_grid")
    if g:
        mag = g["mag"]
        cats = [[-1] * len(mag[0]) for _ in mag]
        for reg in g.get("regions", []):
            for r in range(reg["rb0"], reg["rb1"] + 1):
                for c in range(reg["sym0"], reg["sym1"] + 1):
                    cats[r][c] = GRID_CATEGORIES.index(reg["name"])
        ann = stage.data["annotations"]
        b.plot(Plot(id="coreset_grid", type="resource_grid", title=b.plot_text("coreset_grid", "title"), caption=b.plot_text("coreset_grid", "caption"),
                    x=PlotAxis(label=b.plot_text("coreset_grid", "x")), y=PlotAxis(label=b.plot_text("coreset_grid", "y")),
                    grid=PlotGrid(rows=len(mag), cols=len(mag[0]), values=mag, categories=cats, category_names=GRID_CATEGORIES, category_terms=GRID_TERMS),
                    annotations=[PlotAnnotation(kind="region", label=n, description=ann[n], term=t, category=i)
                                 for i, (n, t) in enumerate(zip(GRID_CATEGORIES, GRID_TERMS, strict=True))]))

    tbs = (msg2.get("bits") or {}).get("tb_hex_list") or []
    pdu = None
    for hexstr in tbs:
        try:
            pdu = ra.parse_rar_pdu(bytes.fromhex(hexstr))
            break
        except ValueError:
            continue
    if not msg2.get("ok") or pdu is None or not pdu.rars:
        b.diag("NO_RAR", detail=msg2.get("error_code") or None)
        return b.build("fail", reason=msg2.get("error_code") or "NO_RAR")

    rar = pdu.rars[0]
    scs = int(ctx.params.get("scs_khz") or 15)
    n_ta = ra.n_ta_from_command(rar.ta_command, scs)
    mu = {15: 0, 30: 1, 60: 2}[scs]
    d_nta = b.derive("n_ta", r"N_{TA} = T_A \cdot \frac{16 \cdot 64}{2^{\mu}}",
                     [inp("T_A", rar.ta_command, "RAR timing advance command (12 bits)"), inp("μ", mu, f"SCS {scs} kHz")],
                     [f"{rar.ta_command} × 1024 / 2^{mu} = {fmt(n_ta)} Tc"], n_ta, "Tc", "TS 38.213 4.2")
    ta_us = n_ta * ntn.TC * 1e6
    d_us = b.derive("ta_us", r"T = N_{TA} \cdot T_c", [inp("N_TA", n_ta, "ra.n_ta", "Tc"), inp("T_c", ntn.TC, "TS 38.211 4.1", "s")],
                    [f"{fmt(n_ta)} × T_c = {fmt(ta_us, 6)} µs"], round(ta_us, 3), "µs", "TS 38.211 4.3.1")
    dist = ra.distance_from_n_ta(n_ta)
    d_dist = b.derive("distance", r"d \approx \frac{c \cdot N_{TA} \cdot T_c}{2}",
                      [inp("N_TA", n_ta, "ra.n_ta", "Tc"), inp("c", ntn.C, "constant", "m/s")],
                      [f"{fmt(ntn.C, 9)} × {fmt(ta_us, 6)} µs / 2 = {fmt(dist, 7)} m"], round(dist, 1), "m", "TS 38.213 4.2")
    gf = rar.grant_fields
    d_grant = b.derive("grant", r"\text{UL grant (27 bits)} = \text{hop}(1) \mid \text{freq}(14) \mid \text{time}(4) \mid \text{MCS}(4) \mid \text{TPC}(3) \mid \text{CSI}(1)",
                       [inp("UL grant", f"0x{rar.ul_grant:07X}", "RAR UL grant (27 bits)")], [f"{k} = {v}" for k, v in gf.items()], rar.ul_grant, "",
                       "TS 38.213 Table 8.2-1")
    b.decoded("rapid", rar.rapid, "RAR subheader RAPID (6 bits)", primary=True)
    if pdu.backoff_indicator is not None:
        b.decoded("backoff", pdu.backoff_indicator, "RAR subheader BI (4 bits)")
    b.decoded("ta_command", rar.ta_command, "MAC RAR bits 2-13", primary=True)
    b.derived("n_ta", n_ta, d_nta)
    b.derived("ta_us", round(ta_us, 3), d_us, primary=True)
    b.derived("distance", round(dist, 1), d_dist, primary=True)
    b.decoded("tc_rnti", f"0x{rar.tc_rnti:04X}", "MAC RAR bits 41-56", raw=rar.tc_rnti, primary=True)
    for key, name in (("grant_hopping", "frequency hopping flag"), ("grant_freq", "PUSCH frequency resource allocation"),
                      ("grant_time", "PUSCH time resource allocation"), ("grant_mcs", "MCS"), ("grant_tpc", "TPC command for PUSCH"),
                      ("grant_csi", "CSI request")):
        b.derived(key, gf[name], d_grant)

    status, msg4_text = "ok", "-"
    m4 = None
    for hexstr in (msg4.get("bits") or {}).get("tb_hex_list") or []:
        parsed = ra.parse_msg4_pdu(bytes.fromhex(hexstr))
        if parsed["contention_id"]:
            m4 = parsed
            break
    if m4 is None:
        b.diag("NO_MSG4", default_level="warn")
        status = "partial"
    else:
        b.decoded("contention_id", m4["contention_id"], "Msg4 MAC CE (LCID 62), 48 bits", primary=True)
        msg4_text = "contention resolution"
        if m4["ccch_sdu"]:
            try:
                value, tree = rrc.decode("DL-CCCH-Message", bytes.fromhex(m4["ccch_sdu"]))
                kind = rrc.find_path(value, "message", "c1")
                b.decoded("msg4_rrc", kind[0] if kind else "?", "Msg4 CCCH SDU (DL-CCCH-Message)")
                b.tree("msg4", "DL-CCCH-Message", tree)
                msg4_text += f" + {kind[0] if kind else '?'}"
            except rrc.Asn1Error:
                pass
    b.next_inputs = {"ra_rnti": rnti, "tc_rnti": rar.tc_rnti, "ta_command": rar.ta_command, "n_ta": n_ta}
    return b.build(status, ta_us=fmt(ta_us, 5), ra_rnti=rnti, rapid=rar.rapid, ta=rar.ta_command, n_ta=fmt(n_ta), distance_m=fmt(dist, 6),
                   tc_rnti=f"0x{rar.tc_rnti:04X}", msg4=msg4_text)
