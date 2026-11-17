"""단계 4 — 그 외 SI 메시지(SIB19 중심). 원시값과 물리량(단위 환산)을 함께 보여준다."""

from __future__ import annotations

from math import sqrt
from typing import Any

from ..asn1 import rrc
from ..contracts_gen import StageResult
from ..pipeline import StageDef
from ..result import ResultBuilder, fmt, inp
from .base import Ctx, Plot, PlotColumn, PlotTable

# NTN-Config-r17 필드의 단위. TS 38.331 6.3.2 NTN-Config, EphemerisInfo, TA-Info 필드 설명 (원문 미대조).
POS_UNIT_M = 1.3
VEL_UNIT_MPS = 0.06
TA_COMMON_UNIT_US = 4.072e-3
TA_DRIFT_UNIT_US_S = 0.2e-3
TA_DRIFT_VARIANT_UNIT_US_S2 = 0.2e-4
EARTH_RADIUS_KM = 6371.0  # 평균 반지름. 정밀한 고도(타원체 기준)는 NTN 계산 화면에서 구한다.
REF = "TS 38.331 6.3.2 NTN-Config"
P = "SIB19.ntn-Config-r17"


def find_sib19(si_values: list[Any]) -> tuple[dict[str, Any] | None, list[str]]:
    """복호한 SI 메시지들에서 SIB19와, 받은 SIB 이름 전체를 찾는다."""
    names: list[str] = []
    found = None
    for value in si_values:
        items = rrc.find_path(value, "message", "c1", "systemInformation", "criticalExtensions", "systemInformation", "sib-TypeAndInfo") or []
        for kind, val in items:
            names.append(kind.split("-")[0].upper())
            if kind == "sib19-v1700":
                found = val
    return found, names


def assemble(stage: StageDef, raw: dict[str, Any], ctx: Ctx) -> StageResult:
    b = ResultBuilder(stage)
    if not raw.get("ok"):
        code = raw.get("error_code") or "SI_TIMEOUT"
        b.diag(code, detail=raw.get("error_detail") or None)
        return b.build("fail", reason=code)

    values, trees = [], []
    for hexstr in raw["bits"]["tb_hex_list"]:
        try:
            v, t = rrc.decode("BCCH-DL-SCH-Message", bytes.fromhex(hexstr))
            values.append(v)
            trees.append(t)
        except rrc.Asn1Error as e:
            b.diag("ASN1_FAIL", detail=f"{e} / {hexstr}")
    sib19, names = find_sib19(values)
    if sib19 is None:
        if not b.diagnostics:
            b.diag("NOT_SCHEDULED")
        return b.build("fail", reason="SIB19 not found")

    ntn = sib19.get("ntn-Config-r17") or {}
    b.decoded("received_sibs", names, "BCCH-DL-SCH-Message.…sib-TypeAndInfo", primary=True)
    rows: list[dict[str, Any]] = []

    def row(field: str, rawv: Any, phys: Any, unit: str) -> None:
        rows.append({"field": field, "raw": rawv, "physical": phys, "unit": unit})

    epoch = ntn.get("epochTime-r17")
    if epoch:
        b.decoded("epoch_sfn", epoch["sfn-r17"], f"{P}.epochTime-r17.sfn-r17")
        b.decoded("epoch_subframe", epoch["subFrameNR-r17"], f"{P}.epochTime-r17.subFrameNR-r17")
        row("epochTime-r17", f"SFN {epoch['sfn-r17']}, subframe {epoch['subFrameNR-r17']}", "", "")
    val = ntn.get("ntn-UlSyncValidityDuration-r17")
    if val:
        secs = int(val[1:])
        d = b.derive("validity", r"T_{valid} = \mathrm{ntn\text{-}UlSyncValidityDuration}\ [\mathrm{s}]",
                     [inp("ntn-UlSyncValidityDuration", val, f"{P}.ntn-UlSyncValidityDuration-r17")], [f"{val} → {secs} s"], secs, "s", REF)
        b.derived("validity", secs, d, raw=val, primary=True)
        row("ntn-UlSyncValidityDuration-r17", val, secs, "s")

    summary = {"altitude_km": "?", "speed_kms": "?"}
    eph_choice: tuple[str | None, dict[str, Any]] = ntn.get("ephemerisInfo-r17") or (None, {})
    kind, eph = eph_choice
    if kind == "positionVelocity-r17":
        pos = [eph[f"position{a}-r17"] for a in "XYZ"]
        vel = [eph[f"velocityV{a}-r17"] for a in "XYZ"]
        pos_km = [p * POS_UNIT_M / 1000 for p in pos]
        vel_kms = [v * VEL_UNIT_MPS / 1000 for v in vel]
        d_pos = b.derive("pos", r"x = \mathrm{positionX} \times 1.3\,\mathrm{m}",
                         [inp(f"position{a}", p, f"{P}.ephemerisInfo-r17.positionVelocity-r17.position{a}-r17") for a, p in zip("XYZ", pos, strict=True)],
                         [f"{p} × 1.3 m = {fmt(k, 8)} km" for p, k in zip(pos, pos_km, strict=True)], round(pos_km[0], 3), "km", REF)
        d_vel = b.derive("vel", r"v_x = \mathrm{velocityVX} \times 0.06\,\mathrm{m/s}",
                         [inp(f"velocityV{a}", v, f"{P}.ephemerisInfo-r17.positionVelocity-r17.velocityV{a}-r17") for a, v in zip("XYZ", vel, strict=True)],
                         [f"{v} × 0.06 m/s = {fmt(k, 6)} km/s" for v, k in zip(vel, vel_kms, strict=True)], round(vel_kms[0], 4), "km/s", REF)
        for a, p, k in zip("xyz", pos, pos_km, strict=True):
            b.derived(f"pos_{a}", round(k, 3), d_pos, raw=p)
            row(f"position{a.upper()}-r17", p, round(k, 3), "km")
        for a, v, k in zip("xyz", vel, vel_kms, strict=True):
            b.derived(f"vel_{a}", round(k, 4), d_vel, raw=v)
            row(f"velocityV{a.upper()}-r17", v, round(k, 4), "km/s")
        r = sqrt(sum(k * k for k in pos_km))
        alt = r - EARTH_RADIUS_KM
        d_alt = b.derive("altitude", r"h = \sqrt{x^2 + y^2 + z^2} - R_E",
                         [inp("x", round(pos_km[0], 3), "SIB19 position", "km"), inp("y", round(pos_km[1], 3), "SIB19 position", "km"),
                          inp("z", round(pos_km[2], 3), "SIB19 position", "km"), inp("R_E", EARTH_RADIUS_KM, "mean Earth radius", "km")],
                         [f"|r| = {fmt(r, 8)} km", f"{fmt(r, 8)} − {EARTH_RADIUS_KM} = {fmt(alt, 6)} km"], round(alt, 1), "km", "TR 38.821 4.1")
        speed = sqrt(sum(k * k for k in vel_kms))
        d_spd = b.derive("speed", r"|v| = \sqrt{v_x^2 + v_y^2 + v_z^2}",
                         [inp(f"v_{a}", round(k, 4), "SIB19 velocity", "km/s") for a, k in zip("xyz", vel_kms, strict=True)],
                         [f"|v| = {fmt(speed, 5)} km/s"], round(speed, 3), "km/s", REF)
        b.derived("altitude", round(alt, 1), d_alt, primary=True)
        b.derived("speed", round(speed, 3), d_spd, primary=True)
        summary = {"altitude_km": fmt(round(alt), 4), "speed_kms": fmt(speed, 3)}
        b.next_inputs["ephemeris"] = {"format": "positionVelocity", "pos_m": [p * POS_UNIT_M for p in pos], "vel_mps": [v * VEL_UNIT_MPS for v in vel]}
    elif kind == "orbital-r17":
        b.next_inputs["ephemeris"] = {"format": "orbital", "raw": eph}
        for key, v in eph.items():
            row(key, v, "", "")

    k_off = ntn.get("cellSpecificKoffset-r17")
    if k_off is not None:
        d = b.derive("k_offset", r"K_{offset} = \mathrm{cellSpecificKoffset} \times 1\,\mathrm{ms}\ (15\,\mathrm{kHz}\ \text{slots})",
                     [inp("cellSpecificKoffset", k_off, f"{P}.cellSpecificKoffset-r17", "slots")], [f"{k_off} × 1 ms = {k_off} ms"], k_off, "ms", REF)
        b.derived("k_offset", k_off, d, raw=k_off, primary=True)
        row("cellSpecificKoffset-r17", k_off, k_off, "ms")
    if "kmac-r17" in ntn:
        b.decoded("kmac", ntn["kmac-r17"], f"{P}.kmac-r17")
        row("kmac-r17", ntn["kmac-r17"], ntn["kmac-r17"], "ms")
    ta = ntn.get("ta-Info-r17")
    if ta:
        specs = [("ta_common", "ta-Common-r17", TA_COMMON_UNIT_US, "µs", r"TA_{common} = \mathrm{ta\text{-}Common} \times 4.072 \times 10^{-3}\,\mu\mathrm{s}"),
                 ("ta_drift", "ta-CommonDrift-r17", TA_DRIFT_UNIT_US_S, "µs/s", r"\dot{TA}_{common} = \mathrm{ta\text{-}CommonDrift} \times 0.2 \times 10^{-3}\,\mu\mathrm{s/s}"),
                 ("ta_drift_variant", "ta-CommonDriftVariant-r17", TA_DRIFT_VARIANT_UNIT_US_S2, "µs/s²", r"\ddot{TA}_{common} = \mathrm{ta\text{-}CommonDriftVariant} \times 0.2 \times 10^{-4}\,\mu\mathrm{s/s^2}")]
        for key, field, unit_val, unit, tex in specs:
            if field in ta:
                phys = ta[field] * unit_val
                d = b.derive(key, tex, [inp(field[:-4], ta[field], f"{P}.ta-Info-r17.{field}")],
                             [f"{ta[field]} × {fmt(unit_val)} = {fmt(phys, 8)} {unit}"], round(phys, 6), unit, REF)
                b.derived(key, round(phys, 6), d, raw=ta[field], primary=key == "ta_common")
                row(field, ta[field], round(phys, 6), unit)
        b.next_inputs["ta_info"] = {k: ta.get(f) for k, f in (("ta_common", "ta-Common-r17"), ("ta_drift", "ta-CommonDrift-r17"),
                                                              ("ta_drift_variant", "ta-CommonDriftVariant-r17"))}
    if "ntn-PolarizationDL-r17" in ntn:
        b.decoded("polarization", ntn["ntn-PolarizationDL-r17"], f"{P}.ntn-PolarizationDL-r17")
        row("ntn-PolarizationDL-r17", ntn["ntn-PolarizationDL-r17"], "", "")
    if "distanceThresh-r17" in sib19:
        b.decoded("distance_thresh", sib19["distanceThresh-r17"] * 0.05, "SIB19.distanceThresh-r17", raw=sib19["distanceThresh-r17"])
    if "t-Service-r17" in sib19:
        b.decoded("t_service", sib19["t-Service-r17"], "SIB19.t-Service-r17")
    b.decoded("n_neighbours", len(sib19.get("ntn-NeighCellConfigList-r17", [])), "SIB19.ntn-NeighCellConfigList-r17")

    col = stage.data["columns"]
    b.plot(Plot(id="fields", type="table", title=b.plot_text("fields", "title"), caption=b.plot_text("fields", "caption"),
                table=PlotTable(columns=[PlotColumn(key="field", label=col["field"]), PlotColumn(key="raw", label=col["raw"], align="right"),
                                         PlotColumn(key="physical", label=col["physical"], align="right"), PlotColumn(key="unit", label=col["unit"])],
                                rows=rows), annotations=[]))
    for i, t in enumerate(trees):
        b.tree(f"si{i}", f"BCCH-DL-SCH-Message (SI #{i + 1})", t)
    m = raw.get("measurements", {})
    b.next_inputs |= {"epoch": epoch, "validity_s": int(val[1:]) if val else None, "k_offset": k_off}
    raw["decoded"] = {"sib19": trees and rrc.find_path(trees[-1], "message", "c1", "systemInformation") or None, "names": names}
    return b.build("ok", windows=len(m.get("windows", [])), sibs=", ".join(names),
                   epoch_sfn=epoch["sfn-r17"] if epoch else "-", epoch_sf=epoch["subFrameNR-r17"] if epoch else "-",
                   k_offset=k_off if k_off is not None else "-", ta_common=ta.get("ta-Common-r17", "-") if ta else "-", **summary)
