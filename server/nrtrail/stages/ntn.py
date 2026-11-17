"""NTN 계산 화면(SPEC 7절). SIB19 값 + 측정 CFO + 사용자 위치 → 기하·지연·TA·도플러와 이상 징후.

모든 항목은 Derivation으로 계산 과정을 남긴다. 수식의 근거와 대조 상태는 nr/ntn.py 머리말 참고.
"""

from __future__ import annotations

from typing import Any

from ..contracts_gen import Marker as SkyMarker
from ..contracts_gen import PlotSky, StageResult
from ..contracts_gen import Track as SkyTrack
from ..nr import ntn
from ..pipeline import StageDef, load_pipeline
from ..result import ResultBuilder, fmt, inp
from .base import Plot, PlotAnnotation, PlotAxis, PlotSeries
from .sib19 import TA_COMMON_UNIT_US, TA_DRIFT_UNIT_US_S, TA_DRIFT_VARIANT_UNIT_US_S2

DEFAULT_LOCATION = {"lat": 36.35, "lon": 127.38, "alt_m": 60.0}
CURVE_POINTS = 21


def _value(result: StageResult, key: str) -> Any:
    v = next((v for v in result.values if v.key == key), None)
    return None if v is None else getattr(v.value, "root", v.value)


def compute(session: Any, lat: float, lon: float, alt_m: float, t_offset_s: float = 0.0) -> StageResult:
    """서버가 부르는 진입점. session은 sessions.Session (state.results/raws/cell/settings를 쓴다)."""
    st = session.state
    return assemble(load_pipeline().stage("ntn"), sib19=st.results["sib19"].next_inputs,
                    n_ta_offset=_value(st.results["sib1"], "n_ta_offset") if "sib1" in st.results else None,
                    mib=st.raws.get("mib", {}).get("resolved", {}), cfo_hz=st.raws.get("ssb", {}).get("measurements", {}).get("cfo_hz"),
                    carrier_hz=float(st.cell.get("ss_ref_hz") or st.capture["center_freq_hz"]),
                    location={"lat": lat, "lon": lon, "alt_m": alt_m}, t_offset_s=t_offset_s,
                    thresholds=st.settings.get("thresholds", {}))


def assemble(stage: StageDef, *, sib19: dict[str, Any], n_ta_offset: int | None, mib: dict[str, Any], cfo_hz: float | None,
             carrier_hz: float, location: dict[str, float], t_offset_s: float, thresholds: dict[str, float]) -> StageResult:
    b = ResultBuilder(stage)
    ann = stage.data["annotations"]
    eph = sib19.get("ephemeris") or {}
    if eph.get("format") != "positionVelocity":
        b.diag("NO_EPHEMERIS")
        return b.build("fail", reason="ephemerisInfo: " + str(eph.get("format")))
    pos0, vel0 = tuple(eph["pos_m"]), tuple(eph["vel_mps"])
    epoch = sib19.get("epoch") or {}
    validity = sib19.get("validity_s")
    lat, lon, alt = location["lat"], location["lon"], location["alt_m"]

    # --- 기준 시각 ---
    sfn_now = int(mib.get("sfn", epoch.get("sfn-r17", 0)))
    half = int(mib.get("half_frame", 0))
    dt_rx = ntn.epoch_delta_s(sfn_now, epoch.get("sfn-r17", sfn_now), epoch.get("subFrameNR-r17", 0), half * 0.005)
    dt = dt_rx + t_offset_s
    d_dt = b.derive("dt", r"\Delta t = \left[(SFN - SFN_{epoch} + 512) \bmod 1024 - 512\right] \cdot 10\,\mathrm{ms} - sf_{epoch} \cdot 1\,\mathrm{ms} + n_{hf} \cdot 5\,\mathrm{ms} + t_{elapsed}",
                    [inp("SFN", sfn_now, "mib.sfn"), inp("SFN_epoch", epoch.get("sfn-r17"), "SIB19.ntn-Config-r17.epochTime-r17.sfn-r17"),
                     inp("sf_epoch", epoch.get("subFrameNR-r17"), "SIB19.ntn-Config-r17.epochTime-r17.subFrameNR-r17"),
                     inp("n_hf", half, "PBCH payload"), inp("t_elapsed", t_offset_s, "user", "s")],
                    [f"Δt(rx) = {fmt(dt_rx, 6)} s", f"Δt = {fmt(dt_rx, 6)} + {fmt(t_offset_s)} = {fmt(dt, 6)} s"], round(dt, 4), "s",
                    "TS 38.331 6.3.2 NTN-Config (epochTime)")
    b.derived("dt", round(dt, 3), d_dt)
    left = None
    if validity is not None:
        left = validity - max(dt, 0.0)
        d = b.derive("validity_left", r"T_{left} = T_{valid} - \max(\Delta t, 0)",
                     [inp("T_valid", validity, "SIB19.ntn-Config-r17.ntn-UlSyncValidityDuration-r17", "s"), inp("Δt", round(dt, 4), "ntn.dt", "s")],
                     [f"{validity} − {fmt(max(dt, 0.0), 6)} = {fmt(left, 6)} s"], round(left, 2), "s", "TS 38.331 5.2.2.6")
        b.derived("validity_left", round(left, 1), d, primary=True)

    # --- 위성 위치를 지금으로 ---
    pos, vel = ntn.propagate(pos0, vel0, dt)
    b.derive("propagate", r"\ddot{\mathbf{r}} = -\frac{\mu}{|\mathbf{r}|^3}\mathbf{r},\quad \mathbf{v}_{inertial} = \mathbf{v}_{ECEF} + \boldsymbol{\omega}_E \times \mathbf{r}",
                      [inp("r(t_epoch)", ", ".join(fmt(x / 1e3, 8) for x in pos0), "SIB19 positionX/Y/Z × 1.3 m", "km"),
                       inp("v(t_epoch)", ", ".join(fmt(x / 1e3, 6) for x in vel0), "SIB19 velocityVX/VY/VZ × 0.06 m/s", "km/s"),
                       inp("Δt", round(dt, 4), "ntn.dt", "s"), inp("μ", ntn.MU, "WGS-84", "m³/s²"), inp("ω_E", ntn.OMEGA_E, "WGS-84", "rad/s")],
                      ["RK4 two-body integration in the inertial frame, then rotate back by −ω_E·Δt",
                       f"r(t) = ({', '.join(fmt(x / 1e3, 8) for x in pos)}) km", f"v(t) = ({', '.join(fmt(x / 1e3, 6) for x in vel)}) km/s"],
                      round(ntn.norm(pos) / 1e3, 3), "km", "TR 38.821 6.1")
    s_lat, s_lon, s_alt = ntn.ecef_to_geodetic(pos)
    speed = ntn.inertial_speed(pos, vel)  # 관성계 속력. 정지 위성은 ECEF 속도가 0이어도 약 3.07 km/s로 돈다
    radius = ntn.norm(pos)
    v_circ = ntn.circular_speed(radius)
    d_alt = b.derive("altitude", r"h = \text{WGS-84 ellipsoidal height of } \mathbf{r},\quad |\mathbf{v}_{inertial}| = |\mathbf{v}_{ECEF} + \boldsymbol{\omega}_E \times \mathbf{r}|,\quad v_{circ} = \sqrt{\mu / |\mathbf{r}|}",
                     [inp("|r|", round(radius / 1e3, 3), "ntn.propagate", "km"), inp("|v_inertial|", round(speed / 1e3, 4), "ntn.propagate", "km/s")],
                     [f"h = {fmt(s_alt / 1e3, 6)} km (lat {fmt(s_lat, 5)}°, lon {fmt(s_lon, 6)}°)",
                      f"v_circ = √(μ/|r|) = {fmt(v_circ / 1e3, 5)} km/s, |v| = {fmt(speed / 1e3, 5)} km/s"], round(s_alt / 1e3, 1), "km", "TR 38.821 4.1")
    b.derived("sat_lat", round(s_lat, 3), d_alt)
    b.derived("sat_lon", round(s_lon, 3), d_alt)
    b.derived("altitude", round(s_alt / 1e3, 1), d_alt, primary=True)
    b.derived("speed", round(speed / 1e3, 3), d_alt)

    # --- 기하 ---
    lk = ntn.look(lat, lon, alt, pos, vel)
    ue = ntn.geodetic_to_ecef(lat, lon, alt)
    d_rng = b.derive("range", r"d = |\mathbf{r}_{sat} - \mathbf{r}_{UE}|",
                     [inp("r_sat", ", ".join(fmt(x / 1e3, 8) for x in pos), "ntn.propagate", "km"),
                      inp("r_UE", ", ".join(fmt(x / 1e3, 8) for x in ue), f"user location ({lat}, {lon}, {alt} m) → ECEF", "km")],
                     [f"d = {fmt(lk.range_m / 1e3, 8)} km"], round(lk.range_m / 1e3, 3), "km", "TR 38.821 6.1")
    d_ang = b.derive("angles", r"el = \arcsin\frac{u}{d},\quad az = \operatorname{atan2}(e, n)\quad (e, n, u: \text{local east, north, up})",
                     [inp("d", round(lk.range_m / 1e3, 3), "ntn.range", "km"), inp("lat", lat, "user location", "°"), inp("lon", lon, "user location", "°")],
                     [f"el = {fmt(lk.elevation_deg, 5)}°", f"az = {fmt(lk.azimuth_deg, 5)}°"], round(lk.elevation_deg, 2), "°", "TR 38.821 6.1")
    b.derived("range", round(lk.range_m / 1e3, 2), d_rng)
    b.derived("elevation", round(lk.elevation_deg, 1), d_ang, primary=True)
    b.derived("azimuth", round(lk.azimuth_deg, 1), d_ang)

    # --- 지연과 TA ---
    delay = lk.range_m / ntn.C
    d_sd = b.derive("service_delay", r"\tau_{service} = d / c",
                    [inp("d", round(lk.range_m, 1), "ntn.range", "m"), inp("c", ntn.C, "constant", "m/s")],
                    [f"{fmt(lk.range_m, 9)} / {fmt(ntn.C, 9)} = {fmt(delay * 1e3, 6)} ms"], round(delay * 1e3, 4), "ms", "TR 38.821 6.1")
    n_ue = 2 * delay / ntn.TC
    d_ue = b.derive("ta_ue", r"N_{TA,adj}^{UE} = \frac{2 d / c}{T_c},\quad T_c = \frac{1}{480000 \cdot 4096}\,\mathrm{s}",
                    [inp("d/c", round(delay * 1e3, 6), "ntn.service_delay", "ms"), inp("T_c", ntn.TC, "TS 38.211 4.1", "s")],
                    [f"2 × {fmt(delay * 1e3, 6)} ms / T_c = {fmt(n_ue, 9)} T_c"], round(n_ue), "Tc", "TS 38.213 4.2")
    ta = sib19.get("ta_info") or {}
    tc_us = (ta.get("ta_common") or 0) * TA_COMMON_UNIT_US
    td_us = (ta.get("ta_drift") or 0) * TA_DRIFT_UNIT_US_S
    tv_us = (ta.get("ta_drift_variant") or 0) * TA_DRIFT_VARIANT_UNIT_US_S2
    cd = ntn.common_delay_s(tc_us, td_us, tv_us, dt)
    d_cd = b.derive("common_delay", r"Delay_{common}(t) = \frac{TA_{Common}}{2} + \frac{TA_{CommonDrift}}{2}(t - t_{epoch}) + \frac{TA_{CommonDriftVariant}}{2}(t - t_{epoch})^2",
                    [inp("TA_Common", round(tc_us, 6), "SIB19 ta-Common × 4.072e-3 µs", "µs"), inp("TA_CommonDrift", round(td_us, 6), "SIB19 ta-CommonDrift × 0.2e-3 µs/s", "µs/s"),
                     inp("TA_CommonDriftVariant", round(tv_us, 8), "SIB19 ta-CommonDriftVariant × 0.2e-4 µs/s²", "µs/s²"), inp("t − t_epoch", round(dt, 4), "ntn.dt", "s")],
                    [f"{fmt(tc_us / 2, 9)} + {fmt(td_us / 2, 6)} × {fmt(dt, 6)} + {fmt(tv_us / 2, 6)} × {fmt(dt, 6)}² = {fmt(cd * 1e6, 9)} µs"],
                    round(cd * 1e3, 5), "ms", "TS 38.213 4.2")
    n_common = 2 * cd / ntn.TC
    d_cta = b.derive("ta_common", r"N_{TA,adj}^{common} = \frac{2 \cdot Delay_{common}(t)}{T_c}",
                     [inp("Delay_common", round(cd * 1e3, 6), "ntn.common_delay", "ms"), inp("T_c", ntn.TC, "TS 38.211 4.1", "s")],
                     [f"2 × {fmt(cd * 1e3, 6)} ms / T_c = {fmt(n_common, 9)} T_c"], round(n_common), "Tc", "TS 38.213 4.2")
    n_off = int(n_ta_offset or 0)
    total = (0 + n_off + n_common + n_ue) * ntn.TC
    d_tot = b.derive("ta_total", r"T_{TA} = \left(N_{TA} + N_{TA,offset} + N_{TA,adj}^{common} + N_{TA,adj}^{UE}\right) T_c",
                     [inp("N_TA", 0, "before any TA command", "Tc"), inp("N_TA,offset", n_off, "SIB1 n-TimingAdvanceOffset", "Tc"),
                      inp("N_TA,adj^common", round(n_common), "ntn.ta_common", "Tc"), inp("N_TA,adj^UE", round(n_ue), "ntn.ta_ue", "Tc")],
                     [f"(0 + {n_off} + {fmt(round(n_common), 12)} + {fmt(round(n_ue), 12)}) × T_c = {fmt(total * 1e3, 7)} ms"],
                     round(total * 1e3, 4), "ms", "TS 38.211 4.3.1")
    b.derived("service_delay", round(delay * 1e3, 3), d_sd, primary=True)
    b.derived("ta_ue", round(n_ue), d_ue)
    b.derived("common_delay", round(cd * 1e3, 3), d_cd)
    b.derived("ta_common", round(n_common), d_cta)
    b.derived("ta_total", round(total * 1e3, 3), d_tot, primary=True)
    k_off = sib19.get("k_offset")
    if k_off is not None:
        covers = k_off >= total * 1e3
        d = b.derive("k_offset_ok", r"K_{offset} \cdot 1\,\mathrm{ms} \ge T_{TA}",
                     [inp("K_offset", k_off, "SIB19.ntn-Config-r17.cellSpecificKoffset-r17", "ms"), inp("T_TA", round(total * 1e3, 4), "ntn.ta_total", "ms")],
                     [f"{k_off} ms {'≥' if covers else '<'} {fmt(total * 1e3, 6)} ms"], covers, "", "TS 38.213 4.2")
        b.derived("k_offset_ok", covers, d)
        if not covers:
            b.diag("K_OFFSET_TOO_SMALL", default_level="warn")

    # --- 도플러 ---
    dop = ntn.doppler_hz(lk.range_rate_mps, carrier_hz)
    d_dop = b.derive("doppler_pred", r"f_D = -\frac{\dot{d}}{c} f_c,\quad \dot{d} = \frac{(\mathbf{r}_{sat} - \mathbf{r}_{UE}) \cdot \mathbf{v}_{sat}}{d}",
                     [inp("ḋ", round(lk.range_rate_mps, 2), "ntn.propagate / ntn.range", "m/s"), inp("f_c", carrier_hz, "SS_REF", "Hz"), inp("c", ntn.C, "constant", "m/s")],
                     [f"−({fmt(lk.range_rate_mps, 7)}) / {fmt(ntn.C, 9)} × {fmt(carrier_hz, 10)} = {fmt(dop, 7)} Hz"], round(dop, 1), "Hz", "TR 38.821 6.1")
    b.derived("doppler_pred", round(dop, 1), d_dop, primary=True)
    residual = None
    if cfo_hz is not None:
        residual = cfo_hz - dop
        d = b.derive("doppler_residual", r"\Delta = CFO_{meas} - f_D",
                     [inp("CFO_meas", round(cfo_hz, 1), "ssb.cfo_hz", "Hz"), inp("f_D", round(dop, 1), "ntn.doppler_pred", "Hz")],
                     [f"{fmt(cfo_hz, 7)} − ({fmt(dop, 7)}) = {fmt(residual, 6)} Hz"], round(residual, 1), "Hz", "TR 38.821 6.1")
        b.measured("cfo_meas", round(cfo_hz, 1))
        b.derived("doppler_residual", round(residual, 1), d, primary=True)

    # --- 변화율과 예측 곡선 ---
    def at(t: float) -> tuple[ntn.Look, float, float]:
        p, v = ntn.propagate(pos0, vel0, t)
        look = ntn.look(lat, lon, alt, p, v)
        t_ta = (n_off * ntn.TC + 2 * ntn.common_delay_s(tc_us, td_us, tv_us, t) + 2 * look.range_m / ntn.C)
        return look, t_ta, ntn.doppler_hz(look.range_rate_mps, carrier_hz)

    _, ta_a, dop_a = at(dt - 0.5)
    _, ta_b, dop_b = at(dt + 0.5)
    ta_rate, dop_rate = (ta_b - ta_a) * 1e6, dop_b - dop_a
    d = b.derive("ta_rate", r"\dot{T}_{TA} \approx \frac{T_{TA}(t + 0.5\,\mathrm{s}) - T_{TA}(t - 0.5\,\mathrm{s})}{1\,\mathrm{s}}",
                 [inp("T_TA(t+0.5)", round(ta_b * 1e6, 3), "ntn.ta_total", "µs"), inp("T_TA(t−0.5)", round(ta_a * 1e6, 3), "ntn.ta_total", "µs")],
                 [f"{fmt(ta_b * 1e6, 10)} − {fmt(ta_a * 1e6, 10)} = {fmt(ta_rate, 5)} µs/s"], round(ta_rate, 3), "µs/s", "TS 38.213 4.2")
    b.derived("ta_rate", round(ta_rate, 3), d)
    d = b.derive("doppler_rate", r"\dot{f}_D \approx \frac{f_D(t + 0.5\,\mathrm{s}) - f_D(t - 0.5\,\mathrm{s})}{1\,\mathrm{s}}",
                 [inp("f_D(t+0.5)", round(dop_b, 2), "ntn.doppler_pred", "Hz"), inp("f_D(t−0.5)", round(dop_a, 2), "ntn.doppler_pred", "Hz")],
                 [f"{fmt(dop_b, 7)} − ({fmt(dop_a, 7)}) = {fmt(dop_rate, 5)} Hz/s"], round(dop_rate, 2), "Hz/s", "TR 38.821 6.1")
    b.derived("doppler_rate", round(dop_rate, 2), d)

    span = float(max(left or 0.0, 10.0) if validity else 20.0)
    ts = [span * i / (CURVE_POINTS - 1) for i in range(CURVE_POINTS)]
    pts = [at(dt + t) for t in ts]
    b.plot(Plot(id="sky", type="sky_geometry", title=b.plot_text("sky", "title"), caption=b.plot_text("sky", "caption"),
                sky=PlotSky(tracks=[SkyTrack(name=ann["track"], az_deg=[round(p[0].azimuth_deg, 2) for p in pts],
                                             el_deg=[round(p[0].elevation_deg, 2) for p in pts], t_s=[round(t, 2) for t in ts])],
                            markers=[SkyMarker(name=ann["satellite"], az_deg=round(lk.azimuth_deg, 2), el_deg=round(lk.elevation_deg, 2))]),
                annotations=[]))
    b.plot(Plot(id="delays", type="timeseries", title=b.plot_text("delays", "title"), caption=b.plot_text("delays", "caption"),
                x=PlotAxis(label=""), y=PlotAxis(label=b.plot_text("delays", "y"), unit="ms", min=0),
                series=[PlotSeries(name=ann["service"], x=[0], y=[round(delay * 1e3, 4)], role="accent", mode="bars"),
                        PlotSeries(name=ann["common"], x=[1], y=[round(cd * 1e3, 4)], role="primary", mode="bars")], annotations=[]))
    b.plot(Plot(id="ta_curve", type="timeseries", title=b.plot_text("ta_curve", "title"), caption=b.plot_text("ta_curve", "caption"),
                x=PlotAxis(label=b.plot_text("ta_curve", "x"), unit="s"), y=PlotAxis(label=b.plot_text("ta_curve", "y"), unit="ms"),
                series=[PlotSeries(name="T_TA", x=[round(t, 2) for t in ts], y=[round(p[1] * 1e3, 5) for p in pts], role="primary", mode="line")],
                annotations=[PlotAnnotation(kind="vline", x=0, label=ann["now"])]))
    marks = [PlotAnnotation(kind="point", x=0, y=round(cfo_hz, 1), label=ann["measured"], term="cfo")] if cfo_hz is not None else []
    b.plot(Plot(id="doppler_curve", type="timeseries", title=b.plot_text("doppler_curve", "title"), caption=b.plot_text("doppler_curve", "caption"),
                x=PlotAxis(label=b.plot_text("doppler_curve", "x"), unit="s"), y=PlotAxis(label=b.plot_text("doppler_curve", "y"), unit="Hz"),
                series=[PlotSeries(name="f_D", x=[round(t, 2) for t in ts], y=[round(p[2], 1) for p in pts], role="primary", mode="line")],
                annotations=marks))

    # --- 이상 징후 ---
    th = thresholds
    if residual is not None and abs(residual) > th.get("doppler_residual_hz", 5000):
        b.diag("DOPPLER_MISMATCH", default_level="warn", detail=f"residual {fmt(residual, 5)} Hz")
    if not th.get("altitude_min_km", 200) <= s_alt / 1e3 <= th.get("altitude_max_km", 40000) or \
            abs(speed - v_circ) / v_circ * 100 > th.get("speed_tolerance_pct", 10):
        b.diag("ORBIT_UNPHYSICAL", default_level="warn", detail=f"h {fmt(s_alt / 1e3, 5)} km, |v| {fmt(speed / 1e3, 4)} km/s, v_circ {fmt(v_circ / 1e3, 4)} km/s")
    if validity is not None and dt > validity:
        b.diag("EPOCH_OUT_OF_RANGE", default_level="warn", detail=f"Δt {fmt(dt, 5)} s > {validity} s")
    elif dt < 0:
        b.diag("EPOCH_IN_FUTURE", default_level="info")
    limit = ntn.horizon_range(radius) / ntn.C + th.get("ta_mismatch_us", 50) * 1e-6
    if cd < 0 or cd > limit:
        b.diag("TA_COMMON_IMPLAUSIBLE", default_level="warn", detail=f"{fmt(cd * 1e3, 5)} ms, limit {fmt(limit * 1e3, 5)} ms")
    if lk.elevation_deg < 0:
        b.diag("BELOW_HORIZON", default_level="warn", detail=f"el {fmt(lk.elevation_deg, 4)}°")
    if all(abs(location[k] - DEFAULT_LOCATION[k]) < 1e-9 for k in DEFAULT_LOCATION):
        b.diag("LOCATION_DEFAULT", default_level="info")

    warned = any(d.level in ("warn", "error") for d in b.diagnostics)
    b.next_inputs = {"dt_s": dt, "range_m": lk.range_m, "elevation_deg": lk.elevation_deg, "azimuth_deg": lk.azimuth_deg,
                     "ta_total_s": total, "doppler_hz": dop, "residual_hz": residual, "validity_left_s": left}
    return b.build("partial" if warned else "ok", elevation=fmt(lk.elevation_deg, 3), delay_ms=fmt(delay * 1e3, 3), range_km=fmt(lk.range_m / 1e3, 5),
                   azimuth=fmt(lk.azimuth_deg, 4), ta_ms=fmt(total * 1e3, 5), doppler=fmt(dop, 5),
                   cfo=fmt(cfo_hz, 5) if cfo_hz is not None else "-", residual=fmt(residual, 5) if residual is not None else "-")
