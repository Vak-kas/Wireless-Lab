"""NTN 계산: 위성 궤도 전파, 단말-위성 기하, 지연·TA·도플러.

근거
- 공통 지연 다항식: TS 38.213 4.2 (원문 대조함, specs/38213-j50)
    Delay_common(t) = TA_Common/2 + TA_CommonDrift/2*(t - t_epoch) + TA_CommonDriftVariant/2*(t - t_epoch)^2
- 전체 TA: T_TA = (N_TA + N_TA,offset + N_TA,adj^common + N_TA,adj^UE) * Tc — TS 38.211 4.3.1 (원문 미대조)
- Tc = 1/(480000*4096) s — TS 38.211 4.1
- 좌표와 상수: WGS-84, 지구 중력 상수와 자전 각속도는 IERS/WGS-84 값.
궤도 전파는 짧은 구간(수십 초)용 이체 문제 수치 적분(RK4)이다. J2 등 섭동은 넣지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import asin, atan2, cos, degrees, hypot, pi, radians, sin, sqrt

C = 299_792_458.0                 # m/s
TC = 1.0 / (480_000 * 4096)       # s
MU = 3.986004418e14               # m^3/s^2
OMEGA_E = 7.2921150e-5            # rad/s
WGS84_A = 6_378_137.0
WGS84_F = 1 / 298.257223563
WGS84_E2 = WGS84_F * (2 - WGS84_F)
EARTH_MEAN_RADIUS = 6_371_000.0

Vec = tuple[float, float, float]


def _add(a: Vec, b: Vec) -> Vec:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _sub(a: Vec, b: Vec) -> Vec:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _mul(a: Vec, k: float) -> Vec:
    return (a[0] * k, a[1] * k, a[2] * k)


def dot(a: Vec, b: Vec) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def norm(a: Vec) -> float:
    return sqrt(dot(a, a))


def _omega_cross(r: Vec) -> Vec:
    return (-OMEGA_E * r[1], OMEGA_E * r[0], 0.0)


def _rot_z(v: Vec, angle: float) -> Vec:
    c, s = cos(angle), sin(angle)
    return (c * v[0] - s * v[1], s * v[0] + c * v[1], v[2])


def geodetic_to_ecef(lat_deg: float, lon_deg: float, alt_m: float) -> Vec:
    lat, lon = radians(lat_deg), radians(lon_deg)
    n = WGS84_A / sqrt(1 - WGS84_E2 * sin(lat) ** 2)
    return ((n + alt_m) * cos(lat) * cos(lon), (n + alt_m) * cos(lat) * sin(lon), (n * (1 - WGS84_E2) + alt_m) * sin(lat))


def ecef_to_geodetic(r: Vec) -> tuple[float, float, float]:
    """(위도 deg, 경도 deg, 타원체 고도 m). 반복법."""
    x, y, z = r
    lon = atan2(y, x)
    p = hypot(x, y)
    lat = atan2(z, p * (1 - WGS84_E2))
    alt = 0.0
    for _ in range(8):
        n = WGS84_A / sqrt(1 - WGS84_E2 * sin(lat) ** 2)
        alt = p / cos(lat) - n if abs(cos(lat)) > 1e-9 else abs(z) - n * (1 - WGS84_E2)
        lat = atan2(z, p * (1 - WGS84_E2 * n / (n + alt)))
    return degrees(lat), degrees(lon), alt


def propagate(pos: Vec, vel: Vec, dt: float, step: float = 1.0) -> tuple[Vec, Vec]:
    """ECEF 위치·속도를 dt초 뒤로 전파한다(dt는 음수도 됨).

    기준 시각에 ECEF와 겹치는 관성계로 옮겨(v_i = v_e + ω×r) 이체 문제를 RK4로 적분하고,
    지구가 그동안 돈 각도만큼 되돌려 ECEF로 가져온다.
    """
    if dt == 0:
        return pos, vel
    r, v = pos, _add(vel, _omega_cross(pos))

    def acc(x: Vec) -> Vec:
        d = norm(x)
        return _mul(x, -MU / d ** 3)

    n = max(1, int(abs(dt) / step + 0.999999))
    h = dt / n
    for _ in range(n):
        k1r, k1v = v, acc(r)
        k2r, k2v = _add(v, _mul(k1v, h / 2)), acc(_add(r, _mul(k1r, h / 2)))
        k3r, k3v = _add(v, _mul(k2v, h / 2)), acc(_add(r, _mul(k2r, h / 2)))
        k4r, k4v = _add(v, _mul(k3v, h)), acc(_add(r, _mul(k3r, h)))
        r = _add(r, _mul(_add(_add(k1r, _mul(k2r, 2)), _add(_mul(k3r, 2), k4r)), h / 6))
        v = _add(v, _mul(_add(_add(k1v, _mul(k2v, 2)), _add(_mul(k3v, 2), k4v)), h / 6))
    r_e = _rot_z(r, -OMEGA_E * dt)
    v_e = _sub(_rot_z(v, -OMEGA_E * dt), _omega_cross(r_e))
    return r_e, v_e


@dataclass(frozen=True)
class Look:
    range_m: float
    elevation_deg: float
    azimuth_deg: float
    range_rate_mps: float   # 양수 = 멀어짐


def look(ue_lat: float, ue_lon: float, ue_alt: float, sat_pos: Vec, sat_vel: Vec) -> Look:
    """단말에서 본 위성. 단말은 지구에 고정되어 있다고 본다(ECEF에서 정지)."""
    ue = geodetic_to_ecef(ue_lat, ue_lon, ue_alt)
    d = _sub(sat_pos, ue)
    rng = norm(d)
    lat, lon = radians(ue_lat), radians(ue_lon)
    east = -sin(lon) * d[0] + cos(lon) * d[1]
    north = -sin(lat) * cos(lon) * d[0] - sin(lat) * sin(lon) * d[1] + cos(lat) * d[2]
    up = cos(lat) * cos(lon) * d[0] + cos(lat) * sin(lon) * d[1] + sin(lat) * d[2]
    return Look(rng, degrees(asin(up / rng)), degrees(atan2(east, north)) % 360, dot(d, sat_vel) / rng)


def doppler_hz(range_rate_mps: float, carrier_hz: float) -> float:
    """서비스 링크 하향 도플러. 다가오면(+), 멀어지면(-)."""
    return -range_rate_mps / C * carrier_hz


def common_delay_s(ta_common_us: float, drift_us_s: float, variant_us_s2: float, dt: float) -> float:
    """편도 공통 지연 Delay_common(t). TS 38.213 4.2. 입력은 물리 단위(µs, µs/s, µs/s²)."""
    return (ta_common_us / 2 + drift_us_s / 2 * dt + variant_us_s2 / 2 * dt * dt) * 1e-6


def epoch_delta_s(sfn_now: int, sfn_epoch: int, subframe_epoch: int, sfn_frac_s: float = 0.0) -> float:
    """지금(수신 프레임의 시작)과 epochTime의 차 t - t_epoch.

    SFN은 1024에서 되돌아가므로 ±512 프레임(±5.12 s) 안에서 가장 가까운 쪽으로 해석한다.
    epochTime이 미래(음수)일 수도 있다.
    """
    frames = (sfn_now - sfn_epoch + 512) % 1024 - 512
    return frames * 0.010 - subframe_epoch * 0.001 + sfn_frac_s


def circular_speed(radius_m: float) -> float:
    return sqrt(MU / radius_m)


def horizon_range(radius_m: float) -> float:
    """지평선에 걸린 위성까지의 거리(고도각 0도). 서비스·피더 링크 거리의 상한 어림."""
    return sqrt(max(radius_m ** 2 - EARTH_MEAN_RADIUS ** 2, 0.0))


def orbital_period_s(radius_m: float) -> float:
    return 2 * pi * sqrt(radius_m ** 3 / MU)
