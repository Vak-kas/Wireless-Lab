"""화면 개발용 임시 데이터(추적)를 만든다. NTN 결과는 서버가 fixtures/ 로 내보내므로 여기서 쓰지 않는다. 서버가 같은 이름의 파일을 fixtures/ 로 내보내면 그쪽이 우선한다.

사용: python3 web/src/mock/local/make_local.py   (표준 라이브러리만 사용)
계산은 실제 식을 쓰지만(ECEF 기하, d/c, 2d/c, 시선 속도 도플러) 서버의 NTN 모듈(M6)이 정본이다.
"""
import json
import math
from pathlib import Path

HERE = Path(__file__).parent
C = 299792458.0
TC = 1 / (480000 * 4096)
F_DL = 2184.15e6
POS = (-3397500.6, 4508400.0, 4101600.1)
VEL = (-4326.42, -5626.32, 2599.8)
USER = (36.35, 127.38, 60.0)
TA_COMMON_US = 1964636 * 4.072e-3
CFO_MEAS = 2311.1


def lla_to_ecef(lat, lon, alt):
    a, f = 6378137.0, 1 / 298.257223563
    e2 = f * (2 - f)
    la, lo = math.radians(lat), math.radians(lon)
    n = a / math.sqrt(1 - e2 * math.sin(la) ** 2)
    return ((n + alt) * math.cos(la) * math.cos(lo), (n + alt) * math.cos(la) * math.sin(lo), (n * (1 - e2) + alt) * math.sin(la))


def look(sat, user_lla):
    u = lla_to_ecef(*user_lla)
    d = [s - x for s, x in zip(sat, u)]
    rng = math.sqrt(sum(x * x for x in d))
    la, lo = math.radians(user_lla[0]), math.radians(user_lla[1])
    e = -math.sin(lo) * d[0] + math.cos(lo) * d[1]
    n = -math.sin(la) * math.cos(lo) * d[0] - math.sin(la) * math.sin(lo) * d[1] + math.cos(la) * d[2]
    up = math.cos(la) * math.cos(lo) * d[0] + math.cos(la) * math.sin(lo) * d[1] + math.sin(la) * d[2]
    return rng, math.degrees(math.asin(up / rng)), math.degrees(math.atan2(e, n)) % 360, d


def sat_at(t):
    """짧은 구간 근사: 원궤도로 보고 속도 방향으로 각속도만큼 돌린다."""
    r = math.sqrt(sum(x * x for x in POS))
    v = math.sqrt(sum(x * x for x in VEL))
    w = v / r
    ur = [x / r for x in POS]
    uv = [x / v for x in VEL]
    p = [r * (math.cos(w * t) * a + math.sin(w * t) * b) for a, b in zip(ur, uv)]
    vel = [v * (-math.sin(w * t) * a + math.cos(w * t) * b) for a, b in zip(ur, uv)]
    return p, vel


def state(t):
    p, v = sat_at(t)
    rng, el, az, d = look(p, USER)
    vr = sum(a * b for a, b in zip(v, d)) / rng
    return {"range": rng, "el": el, "az": az, "vr": vr, "doppler": -vr / C * F_DL, "delay_us": rng / C * 1e6, "ta_ue_us": 2 * rng / C * 1e6}


def r(x, n=3):
    return round(x, n)


def ntn():
    s = state(0)
    s1 = state(1)
    ta_ue_tc = 2 * s["range"] / C / TC
    total_us = TA_COMMON_US + s["ta_ue_us"]
    resid = CFO_MEAS - s["doppler"]
    ts = list(range(-60, 61, 5))
    st = [state(t) for t in ts]
    values = [
        {"key": "elevation", "label": "고도각", "value": r(s["el"], 2), "unit": "°", "kind": "derived", "derivation_id": "geometry", "primary": True, "group": "기하"},
        {"key": "azimuth", "label": "방위각", "value": r(s["az"], 2), "unit": "°", "kind": "derived", "derivation_id": "geometry", "group": "기하"},
        {"key": "range", "label": "위성까지 거리", "value": r(s["range"] / 1e3, 3), "unit": "km", "kind": "derived", "derivation_id": "geometry", "primary": True, "group": "기하"},
        {"key": "delay", "label": "서비스 링크 지연", "value": r(s["delay_us"], 3), "unit": "µs", "kind": "derived", "derivation_id": "delay", "primary": True, "group": "타이밍", "term": "service_link"},
        {"key": "ta_ue", "label": "단말별 TA", "value": r(s["ta_ue_us"], 3), "unit": "µs", "kind": "derived", "derivation_id": "ta_ue", "group": "타이밍", "term": "ta"},
        {"key": "ta_common", "label": "공통 TA", "value": r(TA_COMMON_US, 3), "unit": "µs", "kind": "decoded", "raw": 1964636, "source": "SIB19.ntn-Config-r17.ta-Info-r17.ta-Common-r17", "group": "타이밍", "term": "ta_common"},
        {"key": "ta_total", "label": "전체 TA (N_TA,offset 제외)", "value": r(total_us, 3), "unit": "µs", "kind": "derived", "derivation_id": "ta_total", "primary": True, "group": "타이밍", "term": "ta"},
        {"key": "ta_rate", "label": "TA 변화율", "value": r(s1["ta_ue_us"] - s["ta_ue_us"], 3), "unit": "µs/s", "kind": "derived", "derivation_id": "rates", "group": "변화율"},
        {"key": "doppler", "label": "예상 도플러", "value": r(s["doppler"], 1), "unit": "Hz", "kind": "derived", "derivation_id": "doppler", "primary": True, "group": "도플러", "term": "doppler"},
        {"key": "cfo_measured", "label": "측정한 주파수 오차", "value": CFO_MEAS, "unit": "Hz", "kind": "measured", "group": "도플러", "term": "cfo"},
        {"key": "doppler_residual", "label": "도플러 잔차 (측정 − 예상)", "value": r(resid, 1), "unit": "Hz", "kind": "derived", "derivation_id": "doppler_residual", "primary": True, "group": "도플러"},
        {"key": "doppler_rate", "label": "도플러 변화율", "value": r(s1["doppler"] - s["doppler"], 2), "unit": "Hz/s", "kind": "derived", "derivation_id": "rates", "group": "변화율"},
        {"key": "validity_left", "label": "남은 유효 시간", "value": 20, "unit": "s", "kind": "decoded", "raw": "s20", "source": "SIB19.ntn-Config-r17.ntn-UlSyncValidityDuration-r17", "group": "시각", "term": "validity"},
        {"key": "k_offset_ok", "label": "K_offset이 TA를 덮는가", "value": True, "unit": "", "kind": "derived", "derivation_id": "k_offset", "group": "타이밍", "term": "k_offset"},
    ]
    derivations = [
        {"id": "geometry", "title": "단말에서 본 위성의 거리·고도각·방위각", "formula_tex": "d = \\lVert \\mathbf{r}_{sat} - \\mathbf{r}_{ue} \\rVert,\\quad el = \\arcsin\\frac{u}{d},\\quad az = \\operatorname{atan2}(e, n)",
         "inputs": [{"symbol": "r_sat", "value": "(-3397.501, 4508.400, 4101.600) km", "source": "SIB19 ephemerisInfo-r17 (ECEF)"}, {"symbol": "r_ue", "value": "36.35°N, 127.38°E, 60 m", "source": "설정의 내 위치 (WGS84 → ECEF)"}],
         "steps": [f"d = {r(s['range'] / 1e3, 3)} km", f"(e, n, u) → el = {r(s['el'], 2)}°, az = {r(s['az'], 2)}°"], "result": {"value": r(s["range"] / 1e3, 3), "unit": "km"}, "spec_ref": "TS 38.213 4.2 (위성 위치로 단말별 TA를 구함)"},
        {"id": "delay", "title": "서비스 링크 지연", "formula_tex": "\\tau = \\frac{d}{c}", "inputs": [{"symbol": "d", "value": r(s["range"], 1), "unit": "m", "source": "위 계산"}, {"symbol": "c", "value": 299792458, "unit": "m/s", "source": "빛의 속도"}],
         "steps": [f"{r(s['range'], 1)} / 299792458 = {r(s['delay_us'], 3)} µs"], "result": {"value": r(s["delay_us"], 3), "unit": "µs"}, "spec_ref": "TS 38.213 4.2"},
        {"id": "ta_ue", "title": "단말별 TA", "formula_tex": "N_{TA,adj}^{UE} = \\frac{2d}{c \\cdot T_c}", "inputs": [{"symbol": "d", "value": r(s["range"], 1), "unit": "m", "source": "위 계산"}, {"symbol": "T_c", "value": "1/(480000·4096)", "unit": "s", "source": "TS 38.211 4.1"}],
         "steps": [f"2 × {r(s['range'], 1)} / 299792458 = {r(s['ta_ue_us'], 3)} µs", f"÷ T_c = {round(ta_ue_tc)} T_c"], "result": {"value": r(s["ta_ue_us"], 3), "unit": "µs"}, "spec_ref": "TS 38.213 4.2"},
        {"id": "ta_total", "title": "전체 TA", "formula_tex": "T_{TA} = (N_{TA} + N_{TA,offset} + N_{TA,adj}^{common} + N_{TA,adj}^{UE})\\,T_c",
         "inputs": [{"symbol": "N_TA,adj^common", "value": r(TA_COMMON_US, 3), "unit": "µs", "source": "SIB19 ta-Common-r17"}, {"symbol": "N_TA,adj^UE", "value": r(s["ta_ue_us"], 3), "unit": "µs", "source": "위 계산"}, {"symbol": "N_TA", "value": 0, "source": "초기 접속 전이므로 0"}],
         "steps": [f"{r(TA_COMMON_US, 3)} + {r(s['ta_ue_us'], 3)} = {r(total_us, 3)} µs (N_TA,offset은 더하지 않음)"], "result": {"value": r(total_us, 3), "unit": "µs"}, "spec_ref": "TS 38.211 4.3.1"},
        {"id": "doppler", "title": "서비스 링크 도플러", "formula_tex": "f_D = -\\frac{v_r}{c} f_c,\\quad v_r = \\frac{\\mathbf{v}_{sat} \\cdot (\\mathbf{r}_{sat} - \\mathbf{r}_{ue})}{d}",
         "inputs": [{"symbol": "v_sat", "value": "(-4.326, -5.626, 2.600) km/s", "source": "SIB19 ephemerisInfo-r17 (ECEF)"}, {"symbol": "f_c", "value": 2184.15, "unit": "MHz", "source": "SSB 중심 주파수"}],
         "steps": [f"v_r = {r(s['vr'], 2)} m/s", f"f_D = -({r(s['vr'], 2)}) / 299792458 × 2184150000 = {r(s['doppler'], 1)} Hz"], "result": {"value": r(s["doppler"], 1), "unit": "Hz"}, "spec_ref": "TR 38.821 6.1 (도플러)"},
        {"id": "doppler_residual", "title": "도플러 잔차", "formula_tex": "\\Delta f = f_{CFO,meas} - f_D", "inputs": [{"symbol": "f_CFO,meas", "value": CFO_MEAS, "unit": "Hz", "source": "SSB 단계 측정"}, {"symbol": "f_D", "value": r(s["doppler"], 1), "unit": "Hz", "source": "위 계산"}],
         "steps": [f"{CFO_MEAS} − ({r(s['doppler'], 1)}) = {r(resid, 1)} Hz"], "result": {"value": r(resid, 1), "unit": "Hz"}, "spec_ref": "SPEC 7절 (관측용 비교)"},
        {"id": "rates", "title": "1초 뒤와의 차이로 구한 변화율", "formula_tex": "\\dot{x} \\approx x(t + 1\\,\\mathrm{s}) - x(t)", "inputs": [{"symbol": "t", "value": 0, "unit": "s", "source": "epochTime 기준"}],
         "steps": [f"TA: {r(s1['ta_ue_us'] - s['ta_ue_us'], 3)} µs/s", f"도플러: {r(s1['doppler'] - s['doppler'], 2)} Hz/s"], "result": {"value": r(s1["doppler"] - s["doppler"], 2), "unit": "Hz/s"}, "spec_ref": "SPEC 7절"},
        {"id": "k_offset", "title": "K_offset이 전체 TA를 덮는지", "formula_tex": "K_{offset} \\cdot T_{slot} \\ge T_{TA}", "inputs": [{"symbol": "K_offset", "value": 12, "unit": "ms", "source": "SIB19 cellSpecificKoffset-r17 (15 kHz 슬롯 = 1 ms)"}, {"symbol": "T_TA", "value": r(total_us / 1e3, 3), "unit": "ms", "source": "위 계산"}],
         "steps": [f"12 ms ≥ {r(total_us / 1e3, 3)} ms → 덮음"], "result": {"value": True, "unit": ""}, "spec_ref": "TS 38.213 4.2"},
    ]
    plots = [
        {"id": "sky", "type": "sky_geometry", "title": "하늘 지도", "caption": "가운데가 머리 위, 바깥 원이 지평선입니다. 선은 앞뒤 2분 동안 위성이 지나가는 길입니다.",
         "sky": {"tracks": [{"name": "위성 경로", "az_deg": [r(state(t)["az"], 2) for t in range(-120, 121, 10)], "el_deg": [r(state(t)["el"], 2) for t in range(-120, 121, 10)]}],
                 "markers": [{"name": "지금", "az_deg": r(s["az"], 2), "el_deg": r(s["el"], 2)}]}, "annotations": []},
        {"id": "delay_parts", "type": "timeseries", "title": "지연 구성", "caption": "전체 TA가 어떤 지연으로 이루어지는지입니다.", "x": {"label": "1 = 공통 TA, 2 = 단말별 TA, 3 = 합"}, "y": {"label": "지연", "unit": "µs"},
         "series": [{"name": "지연", "x": [1, 2, 3], "y": [r(TA_COMMON_US, 1), r(s["ta_ue_us"], 1), r(total_us, 1)], "mode": "bars", "role": "accent"}], "annotations": []},
        {"id": "ta_pred", "type": "timeseries", "title": "TA 예측", "caption": "앞뒤 1분 동안 단말별 TA가 어떻게 변하는지입니다.", "x": {"label": "시간", "unit": "s"}, "y": {"label": "단말별 TA", "unit": "µs"},
         "series": [{"name": "단말별 TA", "x": ts, "y": [r(x["ta_ue_us"], 2) for x in st], "role": "accent"}], "annotations": [{"kind": "vline", "x": 0, "label": "지금", "description": "epochTime 기준 시각"}]},
        {"id": "doppler_pred", "type": "timeseries", "title": "도플러 예측", "caption": "위성이 다가올 때는 +, 멀어질 때는 −입니다.", "x": {"label": "시간", "unit": "s"}, "y": {"label": "도플러", "unit": "Hz"},
         "series": [{"name": "도플러", "x": ts, "y": [r(x["doppler"], 1) for x in st], "role": "accent"}], "annotations": [{"kind": "vline", "x": 0, "label": "지금", "description": "epochTime 기준 시각"}]},
    ]
    diagnostics = [{"level": "info", "code": "CFO_INCLUDES_LO", "message_easy": "측정한 주파수 오차에는 수신기 자체의 오차도 섞여 있습니다.", "fix": "잔차가 크다고 바로 이상은 아닙니다. 기준값은 설정에서 바꿀 수 있습니다."}]
    if abs(resid) > 20000:
        diagnostics.insert(0, {"level": "warn", "code": "DOPPLER_MISMATCH", "message_easy": "궤도 정보가 말하는 도플러와 측정값이 크게 다릅니다.", "fix": "수신기 클럭 오차인지, 궤도 정보가 맞는지 확인하세요."})
    return {"stage": "ntn", "status": "ok", "summary_easy": f"위성은 지금 고도각 {r(s['el'], 1)}°, 거리 {r(s['range'] / 1e3)} km에 있고, 신호는 {r(s['delay_us'] / 1e3, 2)} ms 늦게 도착합니다.",
            "summary_expert": f"d={r(s['range'] / 1e3, 3)} km el={r(s['el'], 2)} az={r(s['az'], 2)} TA_ue={r(s['ta_ue_us'], 3)}us TA_common={r(TA_COMMON_US, 3)}us fD={r(s['doppler'], 1)}Hz",
            "values": values, "derivations": derivations, "plots": plots, "diagnostics": diagnostics, "next_inputs": {}, "spec_refs": ["TS 38.213 4.2", "TS 38.211 4.3.1", "TR 38.821"],
            "meta": {"engine": "local-example"}}


def track():
    pts = []
    for i in range(14):
        t = i * 5
        s = state(t)
        wob = math.sin(i * 1.7)
        pts.append({"t_s": t, "cfo_hz": r(CFO_MEAS + (s["doppler"] - state(0)["doppler"]) + 6 * wob, 1), "rsrp_dbfs": r(-31 + 0.4 * wob, 2), "sinr_db": r(14.3 + 0.5 * math.cos(i), 2),
                    "ta_us": r(TA_COMMON_US + s["ta_ue_us"], 2), "doppler_hz": r(s["doppler"], 1)})
    series = [{"key": "cfo_hz", "label": "주파수 오차 (CFO)", "unit": "Hz"}, {"key": "doppler_hz", "label": "예상 도플러", "unit": "Hz"}, {"key": "ta_us", "label": "전체 TA", "unit": "µs"},
              {"key": "rsrp_dbfs", "label": "신호 세기 (SS-RSRP)", "unit": "dBFS"}, {"key": "sinr_db", "label": "신호 품질 (SS-SINR)", "unit": "dB"}]
    changes = [{"t_s": 20, "field": "epochTime-r17.sfn-r17", "label": "기준 시각 (SFN)", "before": "420", "after": "372"},
               {"t_s": 20, "field": "ta-Common-r17", "label": "공통 TA", "before": "1964636", "after": "1964624"},
               {"t_s": 40, "field": "epochTime-r17.sfn-r17", "label": "기준 시각 (SFN)", "before": "372", "after": "324"}]
    return {"running": False, "interval_s": 5, "series": series, "points": pts}, changes


def write(name, data):
    (HERE / name).write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


if __name__ == "__main__":
    t, ch = track()
    write("ntn-leo-n256/track.json", t)
    write("ntn-leo-n256/track-changes.json", ch)
    s = state(0)
    print({k: round(v, 3) if isinstance(v, float) else v for k, v in s.items() if k != "d"})
