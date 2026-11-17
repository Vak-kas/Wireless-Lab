"""NTN 계산을 손으로 검증할 수 있는 단순 사례의 해석해와 비교한다 (SPEC 13절, M6 완료 기준)."""

from math import cos, pi, radians, sin, sqrt

import pytest
from nrtrail.nr import ntn
from nrtrail.pipeline import load_pipeline
from nrtrail.stages import ntn as ntn_stage
from nrtrail.stages.sib19 import POS_UNIT_M, TA_COMMON_UNIT_US, VEL_UNIT_MPS

FC = 2_184_150_000.0
GEO_RADIUS = (ntn.MU / ntn.OMEGA_E ** 2) ** (1 / 3)   # 정지 궤도 반지름: 공전 각속도 = 지구 자전 각속도


def test_constants():
    assert ntn.TC == pytest.approx(1 / (480e3 * 4096))
    assert GEO_RADIUS == pytest.approx(42_164_000, rel=1e-4)


@pytest.mark.parametrize("lat,lon,alt", [(0, 0, 0), (36.35, 127.38, 60), (-33.9, 151.2, 500), (89.9, -45, 0), (10, -170, 600e3)])
def test_geodetic_roundtrip(lat, lon, alt):
    back = ntn.ecef_to_geodetic(ntn.geodetic_to_ecef(lat, lon, alt))
    assert back[0] == pytest.approx(lat, abs=1e-7) and back[1] == pytest.approx(lon, abs=1e-7) and back[2] == pytest.approx(alt, abs=1e-3)


def test_geostationary_satellite_directly_overhead():
    """적도 위 단말 바로 위의 정지 위성: 거리 = 고도, 고도각 90도, 도플러 0, 시간이 지나도 그대로."""
    pos, vel = (GEO_RADIUS, 0.0, 0.0), (0.0, 0.0, 0.0)   # ECEF에서 정지
    lk = ntn.look(0, 0, 0, pos, vel)
    assert lk.range_m == pytest.approx(GEO_RADIUS - ntn.WGS84_A, abs=1e-3)
    assert lk.elevation_deg == pytest.approx(90, abs=1e-6) and lk.range_rate_mps == 0
    assert ntn.doppler_hz(lk.range_rate_mps, FC) == 0
    # 지연과 단말별 TA: d/c, 2d/c/Tc
    d = GEO_RADIUS - ntn.WGS84_A
    assert d / ntn.C == pytest.approx(0.11936, abs=2e-4)                      # 약 119.4 ms
    # 관성계에서는 원운동이지만 ECEF에서는 제자리에 머문다
    p, v = ntn.propagate(pos, vel, 600.0)
    assert ntn.norm(tuple(a - b for a, b in zip(p, pos, strict=True))) < 1.0 and ntn.norm(v) < 1e-3


def test_circular_orbit_keeps_radius_and_speed_and_period():
    r0 = ntn.EARTH_MEAN_RADIUS + 600e3
    v_inertial = ntn.circular_speed(r0)
    assert v_inertial == pytest.approx(sqrt(ntn.MU / r0)) and v_inertial == pytest.approx(7558, abs=5)
    # 극궤도: 관성 속도가 z 방향이면 ECEF 속도는 (0, -ω r, v)
    pos, vel = (r0, 0.0, 0.0), (0.0, -ntn.OMEGA_E * r0, v_inertial)
    period = ntn.orbital_period_s(r0)
    assert period == pytest.approx(2 * pi * r0 / v_inertial) and 5700 < period < 5900
    for dt in (10.0, 300.0, period / 4):
        p, v = ntn.propagate(pos, vel, dt)
        assert ntn.norm(p) == pytest.approx(r0, rel=1e-7)
        # 해석해: 관성계에서 각도 n·dt 만큼 돈 위치를 지구 자전만큼 되돌린다
        ang, rot = v_inertial / r0 * dt, -ntn.OMEGA_E * dt
        xi, zi = r0 * cos(ang), r0 * sin(ang)
        expect = (xi * cos(rot), xi * sin(rot), zi)
        assert ntn.norm(tuple(a - b for a, b in zip(p, expect, strict=True))) < 0.5
    back, _ = ntn.propagate(*ntn.propagate(pos, vel, 37.0), -37.0)
    assert ntn.norm(tuple(a - b for a, b in zip(back, pos, strict=True))) < 1e-3


def test_doppler_sign_and_size_for_a_radial_approach():
    """단말을 향해 곧장 v로 다가오면 도플러 = +v/c·fc."""
    ue = ntn.geodetic_to_ecef(0, 0, 0)
    pos = (ue[0] + 1_000_000.0, ue[1], ue[2])
    lk = ntn.look(0, 0, 0, pos, (-7000.0, 0.0, 0.0))
    assert lk.range_rate_mps == pytest.approx(-7000) and ntn.doppler_hz(lk.range_rate_mps, FC) == pytest.approx(7000 / ntn.C * FC)
    assert ntn.look(0, 0, 0, pos, (0.0, 7000.0, 0.0)).range_rate_mps == pytest.approx(0, abs=1e-9)   # 시선에 수직이면 0


def test_azimuth_convention():
    assert ntn.look(0, 0, 0, ntn.geodetic_to_ecef(1, 0, 500e3), (0, 0, 0)).azimuth_deg == pytest.approx(0, abs=0.01)     # 북
    assert ntn.look(0, 0, 0, ntn.geodetic_to_ecef(0, 1, 500e3), (0, 0, 0)).azimuth_deg == pytest.approx(90, abs=0.01)    # 동
    assert ntn.look(0, 0, 0, ntn.geodetic_to_ecef(0, 60, 500e3), (0, 0, 0)).elevation_deg < 0                             # 지평선 아래


def test_common_delay_polynomial_and_epoch_wrap():
    # TS 38.213 4.2: TA_Common/2 + TA_CommonDrift/2·Δt + TA_CommonDriftVariant/2·Δt²
    assert ntn.common_delay_s(8000.0, -0.4, 0.02, 10.0) == pytest.approx((4000 - 2 + 1) * 1e-6)
    assert ntn.epoch_delta_s(412, 420, 0) == pytest.approx(-0.08)
    assert ntn.epoch_delta_s(5, 1020, 3) == pytest.approx(0.09 - 0.003)      # SFN이 1024에서 되돌아간 경우
    assert ntn.epoch_delta_s(412, 400, 0, 0.005) == pytest.approx(0.125)


def scenario(**over):
    """정지 위성 바로 아래의 단말. 모든 값을 손으로 구할 수 있다."""
    base = dict(
        sib19={"ephemeris": {"format": "positionVelocity", "pos_m": [GEO_RADIUS, 0.0, 0.0], "vel_mps": [0.0, 0.0, 0.0]},
               "ta_info": {"ta_common": round(250_000 / TA_COMMON_UNIT_US), "ta_drift": 0, "ta_drift_variant": 0},
               "epoch": {"sfn-r17": 100, "subFrameNR-r17": 0}, "validity_s": 240, "k_offset": 600},
        n_ta_offset=25600, mib={"sfn": 100, "half_frame": 0}, cfo_hz=40.0, carrier_hz=FC,
        location={"lat": 0.0, "lon": 0.0, "alt_m": 0.0}, t_offset_s=0.0,
        thresholds={"doppler_residual_hz": 5000, "ta_mismatch_us": 50, "altitude_min_km": 200, "altitude_max_km": 40000,
                    "speed_tolerance_pct": 10, "jump_position_km": 5})
    return ntn_stage.assemble(load_pipeline().stage("ntn"), **(base | over))


def values(result):
    return {v.key: getattr(v.value, "root", v.value) for v in result.values}


def test_total_ta_matches_hand_calculation():
    r = scenario()
    v = values(r)
    d = GEO_RADIUS - ntn.WGS84_A
    n_ue = 2 * d / ntn.C / ntn.TC
    n_common = round(250_000 / TA_COMMON_UNIT_US) * TA_COMMON_UNIT_US * 1e-6 / ntn.TC
    assert v["range"] == pytest.approx(d / 1e3, abs=0.01) and v["elevation"] == 90.0
    assert v["service_delay"] == pytest.approx(d / ntn.C * 1e3, abs=1e-3)
    assert v["ta_ue"] == pytest.approx(n_ue, abs=1) and v["ta_common"] == pytest.approx(n_common, abs=1)
    assert v["ta_total"] == pytest.approx((25600 + n_common + n_ue) * ntn.TC * 1e3, abs=1e-3)      # 약 488.7 ms
    assert v["k_offset_ok"] is True and v["doppler_pred"] == 0 and v["doppler_residual"] == 40.0
    assert v["ta_rate"] == pytest.approx(0, abs=1e-3) and v["doppler_rate"] == pytest.approx(0, abs=1e-2)
    assert v["validity_left"] == 240 and v["dt"] == 0
    # 정지 위성은 ECEF 속도가 0이지만 관성계 속력(약 3.07 km/s)이 원궤도 속력과 같으므로 이상 징후가 아니다
    assert v["speed"] == pytest.approx(3.075, abs=0.005)
    assert r.status == "ok" and not [d.code for d in r.diagnostics if d.level == "warn"]
    assert all(d.spec_ref for d in r.derivations) and {x.derivation_id for x in r.values if x.kind == "derived"} <= {d.id for d in r.derivations}


def leo(**over):
    r0 = ntn.EARTH_MEAN_RADIUS + 600e3
    pos, vel = (r0, 0.0, 0.0), (0.0, -ntn.OMEGA_E * r0, ntn.circular_speed(r0))
    sib19 = {"ephemeris": {"format": "positionVelocity", "pos_m": list(pos), "vel_mps": list(vel)},
             "ta_info": {"ta_common": round(8000 / TA_COMMON_UNIT_US), "ta_drift": 0, "ta_drift_variant": 0},
             "epoch": {"sfn-r17": 100, "subFrameNR-r17": 0}, "validity_s": 20, "k_offset": 20}
    return scenario(**({"sib19": sib19, "cfo_hz": 0.0, "n_ta_offset": 0} | over))


def test_clean_leo_pass_has_no_anomaly():
    r = leo()
    assert r.status == "ok" and not [d for d in r.diagnostics if d.level != "info"]
    v = values(r)
    assert v["elevation"] == pytest.approx(90, abs=0.2) and abs(v["doppler_pred"]) < 200 and v["doppler_rate"] < 0
    assert any(p.type == "sky_geometry" for p in r.plots)


def codes(result):
    return {d.code for d in result.diagnostics if d.level == "warn"}


def test_anomaly_detection():
    assert "DOPPLER_MISMATCH" in codes(leo(cfo_hz=30_000.0))
    low = leo()
    r0 = ntn.EARTH_MEAN_RADIUS + 50e3
    bad_orbit = {"ephemeris": {"format": "positionVelocity", "pos_m": [r0, 0.0, 0.0], "vel_mps": [0.0, 0.0, 7900.0]},
                 "ta_info": {"ta_common": 0, "ta_drift": 0, "ta_drift_variant": 0}, "epoch": {"sfn-r17": 100, "subFrameNR-r17": 0},
                 "validity_s": 20, "k_offset": 20}
    assert "ORBIT_UNPHYSICAL" in codes(leo(sib19=bad_orbit))                       # 고도 50 km
    assert "EPOCH_OUT_OF_RANGE" in codes(leo(t_offset_s=25.0))                      # 유효 시간 20 s를 넘김
    assert "BELOW_HORIZON" in codes(leo(location={"lat": 0.0, "lon": 120.0, "alt_m": 0.0}))
    far = low.next_inputs and leo(sib19={"ephemeris": {"format": "positionVelocity",
                                                       "pos_m": [ntn.EARTH_MEAN_RADIUS + 600e3, 0.0, 0.0],
                                                       "vel_mps": [0.0, -ntn.OMEGA_E * (ntn.EARTH_MEAN_RADIUS + 600e3), 7558.0]},
                                         "ta_info": {"ta_common": 60_000_000, "ta_drift": 0, "ta_drift_variant": 0},
                                         "epoch": {"sfn-r17": 100, "subFrameNR-r17": 0}, "validity_s": 20, "k_offset": 20})
    assert {"TA_COMMON_IMPLAUSIBLE", "K_OFFSET_TOO_SMALL"} <= codes(far)             # 공통 지연 122 ms는 600 km 궤도에서 불가능


def test_unsupported_ephemeris_format_fails_cleanly():
    r = scenario(sib19={"ephemeris": {"format": "orbital", "raw": {}}})
    assert r.status == "fail" and r.diagnostics[0].code == "NO_EPHEMERIS"


def test_unit_constants_used_by_sib19():
    assert POS_UNIT_M == 1.3 and VEL_UNIT_MPS == 0.06 and TA_COMMON_UNIT_US == pytest.approx(4.072e-3)
    assert radians(180) == pytest.approx(pi)


def test_kepler_elements_reproduce_a_known_state():
    """원궤도: 경사 90도, 승교점 경도 0, 평균 근점 이각 0 -> (a, 0, 0)에서 +z로 출발. 4분의 1 주기 뒤는 전파 결과와 같다."""
    a = ntn.EARTH_MEAN_RADIUS + 600e3
    pos, vel = ntn.kepler_to_ecef(a, 0.0, 0.0, 0.0, pi / 2, 0.0)
    assert pos == pytest.approx((a, 0, 0), abs=1e-3)
    assert vel == pytest.approx((0, -ntn.OMEGA_E * a, ntn.circular_speed(a)), abs=1e-6)
    quarter = ntn.orbital_period_s(a) / 4
    p_kepler, _ = ntn.kepler_to_ecef(a, 0.0, 0.0, 0.0, pi / 2, pi / 2)      # 평균 근점 이각 90도 = 4분의 1 주기 뒤(관성계)
    p_prop, _ = ntn.propagate(pos, vel, quarter)
    back = (p_prop[0] * cos(ntn.OMEGA_E * quarter) - p_prop[1] * sin(ntn.OMEGA_E * quarter),
            p_prop[0] * sin(ntn.OMEGA_E * quarter) + p_prop[1] * cos(ntn.OMEGA_E * quarter), p_prop[2])
    assert ntn.norm(tuple(x - y for x, y in zip(back, p_kepler, strict=True))) < 1.0
    # 타원 궤도의 근지점: r = a(1-e), 속력은 vis-viva
    pos, vel = ntn.kepler_to_ecef(a, 0.01, 0.0, 0.0, 0.3, 0.0)
    assert ntn.norm(pos) == pytest.approx(a * 0.99) and ntn.inertial_speed(pos, vel) == pytest.approx(sqrt(ntn.MU * (2 / (a * 0.99) - 1 / a)))


def test_sib19_with_orbital_elements_goes_through_decode_and_ntn():
    from nrtrail.asn1 import rrc, samples
    from nrtrail.stages import sib19 as sib19_stage
    from nrtrail.stages.base import Ctx

    a = ntn.EARTH_MEAN_RADIUS + 600e3
    msg = samples.sib19(epoch_sfn=100, epoch_subframe=0, position=(0, 0, 0), velocity=(0, 0, 0), ta_common=1964636, ta_drift=0,
                        ta_drift_variant=0, k_offset=20)
    msg["ntn-Config-r17"]["ephemerisInfo-r17"] = ("orbital-r17", {
        "semiMajorAxis-r17": round((a - 6_500_000) / 4.249e-3), "eccentricity-r17": 0, "periapsis-r17": 0, "longitude-r17": 0,
        "inclination-r17": round((pi / 2 - 1e-6) / 2.341e-8), "meanAnomaly-r17": 0})
    tb = rrc.encode("BCCH-DL-SCH-Message", samples.bcch_dl_sch_si([("sib19-v1700", msg)])).hex()
    raw = {"ok": True, "bits": {"tb_hex_list": [tb]}, "measurements": {}}
    result = sib19_stage.assemble(load_pipeline().stage("sib19"), raw, Ctx(capture={}))
    assert result.status == "ok"
    v = values(result)
    assert v["altitude"] == pytest.approx(600, abs=0.5) and v["speed"] == pytest.approx(7.558, abs=0.01)
    eph = result.next_inputs["ephemeris"]
    assert eph["format"] == "positionVelocity" and eph["pos_m"][0] == pytest.approx(a, abs=10)
    r = scenario(sib19=result.next_inputs | {"validity_s": 20}, cfo_hz=0.0, n_ta_offset=0)
    assert r.status == "ok" and values(r)["elevation"] == pytest.approx(90, abs=0.2)
