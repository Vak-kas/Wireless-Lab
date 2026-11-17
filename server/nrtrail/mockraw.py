"""연습 시나리오용 원시 결과(raw)를 지어낸다. MATLAB 없이 화면과 서버를 돌리기 위한 것이다.

모양은 docs/engine-contract.md 의 raw와 같다. MATLAB이 만든 정답(pipeline/golden/<시나리오>/<단계>.json)이
있으면 MockEngine은 그것을 먼저 쓰고, 없을 때만 여기서 만든 pipeline/mock/ 의 값을 쓴다.
숫자는 시드가 고정된 난수라 실행할 때마다 같다.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from .asn1 import samples
from .nr import bands, pdsch, raster, sched, type0
from .nr import ra as ra_math
from .nr import ssb as nrssb


def _cell(sc: dict[str, Any]) -> dict[str, Any]:
    g = raster.gscn_to_freq(sc["gscn"])
    band = bands.band_by_id(sc["band"])
    assert band is not None
    opt = band["ssb"][0]
    return bands.cell_info(g.ss_ref_hz, sc["gscn"], opt["scs_khz"], opt["pattern"], sc["band"])


def scan(sc: dict[str, Any]) -> dict[str, Any]:
    rng = np.random.default_rng(sc["gscn"])
    cell = _cell(sc)
    fc, fs = sc["center_freq_hz"], sc["sample_rate_hz"]
    freq = np.linspace(fc - fs / 2, fc + fs / 2, 1024, endpoint=False)
    noise = -60.0
    level = noise + max(sc["snr_db"], -3) + 6
    psd = noise + rng.normal(0, 0.9, freq.size)
    half = raster.ssb_bandwidth_hz(cell["ssb_scs_khz"]) / 2
    inside = np.abs(freq - cell["ss_ref_hz"]) <= half
    psd[inside] = np.maximum(psd[inside], level + rng.normal(0, 0.7, int(inside.sum())))
    edge = np.abs(freq - fc) > 0.46 * fs
    psd[edge] -= 12 * (np.abs(freq[edge] - fc) / fs - 0.46) / 0.04
    nid1, nid2 = divmod(sc["pci"], 3)
    pnr = float(np.clip(sc["snr_db"] + 9.5, 8.6, 30))
    return {
        "stage": "scan", "ok": True, "error_code": "", "error_detail": "",
        "measurements": {
            "cells": [{"gscn": sc["gscn"], "ss_ref_hz": cell["ss_ref_hz"], "ssb_scs_khz": cell["ssb_scs_khz"], "pattern": cell["pattern"],
                       "nid2": nid2, "nid1": nid1, "pci": sc["pci"], "peak_to_noise_db": round(pnr, 2),
                       "cfo_hz": round(sc["cfo_hz"] / 500) * 500.0, "rel_power_db": round(level - noise - 30, 1),
                       "n_ssb_detected": 2, "timing_offset_samples": sc["timing_offset_samples"]}],
            "n_candidates": len(bands.scan_candidates(fc, fs, sc["band"])), "noise_floor_db": noise,
        },
        "bits": {}, "soft": {},
        "plots": {"spectrum": {"freq_hz": [round(float(f)) for f in freq], "psd_db": [round(float(p), 2) for p in psd]}},
    }


def ssb(sc: dict[str, Any]) -> dict[str, Any]:
    rng = np.random.default_rng(sc["gscn"] + 1)
    cell = _cell(sc)
    fs = sc["sample_rate_hz"]
    nid1, nid2 = divmod(sc["pci"], 3)
    snr = sc["snr_db"]
    sigma = 10 ** (-snr / 20) / np.sqrt(2)
    t0 = sc["timing_offset_samples"]
    # 상관: 20 ms 주기로 SSB 두 개(번호 0, 1)가 보인다
    n = int(0.045 * fs)
    lags = np.arange(0, n, max(1, n // 900))
    mag = np.abs(rng.normal(0, 0.035 + 0.02 * sigma, (3, lags.size)))
    sym = nrssb.symbol_start_in_half_frame(8, cell["ssb_scs_khz"], fs) - nrssb.symbol_start_in_half_frame(2, cell["ssb_scs_khz"], fs)
    for k, peak in enumerate((t0, t0 + sym, t0 + 0.02 * fs, t0 + 0.02 * fs + sym)):
        i = int(np.argmin(np.abs(lags - peak)))
        mag[nid2, i] = 1.0 if k == 0 else 0.86 + 0.05 * rng.random()
        lags[i] = int(peak)
    mag = mag / mag.max()
    # SSB 격자
    grid = np.zeros((240, 4))
    for k in range(240):
        for s in range(4):
            cat = nrssb.ssb_category(k, s, sc["pci"])
            base = {0: 1.0, 1: 0.95, 2: 0.7, 3: 0.82, -1: 0.0}[cat]
            grid[k, s] = np.clip(base * (1 + rng.normal(0, 0.08)) + abs(rng.normal(0, 0.25 * sigma)), 0, 1)
    pts = (rng.choice([-1, 1], 432) + 1j * rng.choice([-1, 1], 432)) / np.sqrt(2) + rng.normal(0, sigma, 432) + 1j * rng.normal(0, sigma, 432)
    cfo = sc["cfo_hz"] + 0.6
    coarse = round(cfo / 500) * 500.0
    return {
        "stage": "ssb", "ok": True, "error_code": "", "error_detail": "",
        "warnings": ["LOW_SNR"] if snr < 0 else [],
        "measurements": {
            "nid2": nid2, "nid1": nid1, "pci": sc["pci"],
            "timing_offset_samples": t0, "timing_offset_us": round(t0 / fs * 1e6, 3), "proc_sample_rate_hz": fs,
            "cfo_coarse_hz": coarse, "cfo_fine_hz": round(cfo - coarse, 2), "cfo_hz": round(cfo, 2),
            "cfo_ppm": round(cfo / cell["ss_ref_hz"] * 1e6, 4), "cfo_search_hz": 50000 if cell["ntn"] else 15000,
            "ibar_ssb": 0, "half_frame_from_dmrs": 0 if cell["lmax"] == 4 else None,
            "rsrp_dbfs": round(-46.0 + snr, 1), "sinr_db": round(snr - 0.7, 1), "n_ssb_used": 1,
        },
        "bits": {}, "soft": {"pbch_llr": []},
        "plots": {
            "correlation": {"lag_samples": [int(x) for x in lags], "mag": [[round(float(v), 4) for v in row] for row in mag],
                            "peak": {"lag": t0, "nid2": nid2, "value": 1.0}},
            "ssb_grid": {"mag": [[round(float(v), 3) for v in row] for row in grid]},
            "constellation": {"re": [round(float(v), 3) for v in pts.real], "im": [round(float(v), 3) for v in pts.imag]},
        },
    }


def mib(sc: dict[str, Any]) -> dict[str, Any]:
    cell = _cell(sc)
    if sc["snr_db"] < -5:
        return {"stage": "mib", "ok": False, "error_code": "PBCH_CRC_FAIL", "error_detail": "",
                "measurements": {"crc_ok": False, "lmax": cell["lmax"]}, "bits": {}, "soft": {}, "plots": {}}
    m = sc["mib"]
    scs = "scs15or60" if cell["ssb_scs_khz"] == 15 else "scs30or120"
    value = samples.mib(m["sfn"] >> 4, scs, m["k_ssb"] & 0xF, f"pos{m['dmrs_typea_pos']}", m["pdcch_config_sib1"])
    return {
        "stage": "mib", "ok": True, "error_code": "", "error_detail": "",
        "measurements": {"crc_ok": True, "lmax": cell["lmax"], "sfn_4lsb": m["sfn"] & 0xF, "half_frame": 0,
                         "msb_idx_offset": m["k_ssb"] >> 4},
        "bits": {"bch_trblk_hex": samples.encode_hex("BCCH-BCH-Message", value), "bch_trblk_bits": 24},
        "soft": {}, "plots": {},
    }


def sib1_value(sc: dict[str, Any]) -> dict[str, Any]:
    cell = _cell(sc)
    scs_khz = cell["ssb_scs_khz"]
    n_rb = 25 if scs_khz == 15 else 51
    offset = 2 if scs_khz == 15 else 4
    ul = None
    if cell["paired"]:  # FDD: 상향 Point A를 하향보다 190 MHz 아래에 둔다 (n256의 듀플렉스 간격)
        m = sc["mib"]
        cs = type0.coreset0(m["pdcch_config_sib1"] >> 4, scs_khz, scs_khz, cell["min_bw_mhz"])
        low = type0.crb_grid_from_ssb(cell["ss_ref_hz"], scs_khz, m["k_ssb"], cs.offset_rb, scs_khz)["crb_ssb_low_hz"]
        ul = round((sched.point_a_hz(low, offset) - 190e6) / 5000)
    return samples.sib1(band=int(sc["band"][1:]), scs=f"kHz{scs_khz}", carrier_rbs=n_rb, offset_to_point_a=offset,
                        loc_and_bw=sched.riv_encode(0, n_rb, 275), ntn=sc["ntn"], ssb_positions=0b10000000, ul_point_a_arfcn=ul)


def _pdsch(rng: np.random.Generator, sc: dict[str, Any], payload_hex: str, n_rb: int, n_sym_coreset: int, si_indicator: int) -> dict[str, Any]:
    """PDCCH/PDSCH 복호 결과를 지어낸다. 자원 할당·DCI·TBS는 합성기 cfg와 같은 규칙(pdsch.allocate)으로 정해 서로 맞는다."""
    sigma = 10 ** (-sc["snr_db"] / 20) / np.sqrt(2)
    a = pdsch.allocate(payload_hex, n_rb, sc["mib"]["dmrs_typea_pos"], si_indicator)
    length, s0, ln = a["rb_len"], a["sym_start"], a["sym_len"]
    grid = np.abs(rng.normal(0, 0.05 + 0.1 * sigma, (n_rb, 14)))
    grid[:, :n_sym_coreset] = 0.8 + rng.normal(0, 0.05, (n_rb, n_sym_coreset))
    grid[:length, s0:s0 + ln] = 0.7 + rng.normal(0, 0.06, (length, ln))
    dmrs_syms = [s0, 7, 11] if s0 + ln > 12 else [s0]
    for sym in dmrs_syms:
        grid[:length, sym] = 0.9
    pts = (rng.choice([-1, 1], 300) + 1j * rng.choice([-1, 1], 300)) / np.sqrt(2) + rng.normal(0, sigma, 300) + 1j * rng.normal(0, sigma, 300)
    dci = {k: v for k, v in a["dci"].items() if k != "bits"} | {"n_bits": len(a["dci"]["bits"])}
    return {
        "tb_hex": a["tb_hex"], "dci_bits": a["dci"]["bits"],
        "measurements": {
            "crc_ok": True, "al": a["al"], "cce_start": 0, "n_rb_coreset0": n_rb, "dci": dci,
            "rb_start": 0, "rb_len": length, "sym_start": s0, "sym_len": ln, "qm": a["qm"], "rate_x1024": a["rate_x1024"],
            "n_dmrs_per_prb": a["n_dmrs_per_prb"], "tbs": a["tbs"], "sinr_db": round(sc["snr_db"] - 1.1, 1), "n_occasions_tried": 1,
        },
        "plots": {
            "coreset_grid": {"mag": [[round(float(np.clip(v, 0, 1)), 3) for v in row] for row in grid],
                             "regions": [{"name": "CORESET0", "rb0": 0, "rb1": n_rb - 1, "sym0": 0, "sym1": n_sym_coreset - 1},
                                         {"name": "PDCCH", "rb0": 0, "rb1": n_rb - 1, "sym0": 0, "sym1": n_sym_coreset - 1},
                                         {"name": "PDSCH", "rb0": 0, "rb1": length - 1, "sym0": s0, "sym1": s0 + ln - 1}]
                             + [{"name": "PDSCH DM-RS", "rb0": 0, "rb1": length - 1, "sym0": sym, "sym1": sym} for sym in dmrs_syms]},
            "constellation": {"re": [round(float(v), 3) for v in pts.real], "im": [round(float(v), 3) for v in pts.imag]},
        },
    }


def sib1(sc: dict[str, Any]) -> dict[str, Any]:
    rng = np.random.default_rng(sc["gscn"] + 3)
    payload = samples.encode_hex("BCCH-DL-SCH-Message", samples.bcch_dl_sch_sib1(sib1_value(sc)))
    body = _pdsch(rng, sc, payload, 24, 2, 0)
    tb = body.pop("tb_hex")
    body["measurements"] |= {"sfn": sc["mib"]["sfn"], "slot": 0}
    return {"stage": "sib1", "ok": True, "error_code": "", "error_detail": "",
            "bits": {"tb_hex": tb, "tb_bits": len(tb) * 4, "dci_bits": body.pop("dci_bits")}, "soft": {}, **body}


# 시험용 위성: 고도 600 km 원궤도, 한반도 상공. 위치는 1.3 m, 속도는 0.06 m/s 단위의 원시값.
SIB19_SAMPLE: dict[str, Any] = dict(epoch_sfn=420, epoch_subframe=0, position=(-2613462, 3468000, 3155077), velocity=(-72107, -93772, 43330),
                    ta_common=1964636, ta_drift=-12, ta_drift_variant=0, k_offset=16)


def si(sc: dict[str, Any]) -> dict[str, Any]:
    if not sc["ntn"]:
        return {"stage": "sib19", "ok": False, "error_code": "NOT_SCHEDULED", "error_detail": "", "measurements": {}, "bits": {},
                "soft": {}, "plots": {}}
    rng = np.random.default_rng(sc["gscn"] + 4)
    payload = samples.encode_hex("BCCH-DL-SCH-Message", samples.bcch_dl_sch_si([("sib19-v1700", samples.sib19(**SIB19_SAMPLE))]))
    body = _pdsch(rng, sc, payload, 24, 2, 1)
    tb = body.pop("tb_hex")
    meas = body["measurements"] | {"sfn": 418, "slot": 1}
    meas["messages"] = [{k: meas[k] for k in ("sfn", "slot", "crc_ok", "tbs", "al", "dci", "rb_start", "rb_len")}]
    return {"stage": "sib19", "ok": True, "error_code": "", "error_detail": "", "measurements": meas,
            "bits": {"tb_hex": tb, "tb_bits": len(tb) * 4, "dci_bits": body.pop("dci_bits"), "tb_hex_list": [tb]}, "soft": {},
            "plots": body["plots"]}


# 시험용 RA 응답: 프리앰블 23번, TA 명령 77, TC-RNTI 0x4601, 경쟁 해소 식별자 6바이트 + RRCReject(waitTime 5)
RA_SAMPLE: dict[str, Any] = {"rapid": 23, "ta_command": 77, "ul_grant": 0x0123456, "tc_rnti": 0x4601,
                             "contention_id": "a1b2c3d4e5f6", "ccch_hex": "0880"}


def ra_payloads() -> tuple[str, str]:
    r = RA_SAMPLE
    return (ra_math.build_rar_pdu(r["rapid"], r["ta_command"], r["ul_grant"], r["tc_rnti"]).hex(),
            ra_math.build_msg4_pdu(bytes.fromhex(r["contention_id"]), bytes.fromhex(r["ccch_hex"])).hex())


def ra(sc: dict[str, Any]) -> dict[str, Any]:
    """RA 관측의 지어낸 결과. Msg2와 Msg4를 한 파일에 담는다(runner.run_ra 참고)."""
    rng = np.random.default_rng(sc["gscn"] + 5)
    out: dict[str, Any] = {"stage": "ra", "ok": True, "error_code": "", "error_detail": ""}
    for key, payload in zip(("msg2", "msg4"), ra_payloads(), strict=True):
        body = _pdsch(rng, sc, payload, 24, 2, 0)
        tb = body.pop("tb_hex")
        out[key] = {"ok": True, "error_code": "", "measurements": body["measurements"],
                    "bits": {"tb_hex": tb, "dci_bits": body.pop("dci_bits"), "tb_hex_list": [tb]}, "plots": body["plots"]}
    return out


GENERATORS = {"scan": scan, "ssb": ssb, "mib": mib, "sib1": sib1, "sib19": si, "ra": ra}
