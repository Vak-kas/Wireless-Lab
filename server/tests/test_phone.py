"""휴대폰 연동(M9) 테스트. fixture는 모두 테스트용으로 직접 쓴 합성 예시다(실제 기기 출력 아님)."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest
from nrtrail import phone

FIXTURES = Path(__file__).parent / "fixtures" / "phone"
ALL_FIXTURES = sorted(p.name for p in FIXTURES.glob("*.txt"))

ALLOWED_KEYS = {
    "registered", "rat", "arfcn", "band", "pci", "tac", "mcc", "mnc", "cell_id",
    "rsrp_dbm", "rsrq_db", "sinr_db", "timing_advance", "freq_mhz",
}  # fmt: skip
SENTINELS = {2147483647, 268435455, 9223372036854775807, 68719476735}


def load(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def parse(name: str) -> list[dict[str, Any]]:
    return phone.parse_telephony_registry(load(name))


# --- fixture 자체 ----------------------------------------------------------


def test_fixture_set_is_complete_and_marked_synthetic() -> None:
    assert {
        "pixel_a14_nr_sa.txt", "samsung_a13_nr_nsa.txt", "android11_nr_old.txt", "lte_only.txt",
        "truncated.txt", "garbage.txt", "samsung_servicestate_only.txt",
    } <= set(ALL_FIXTURES)  # fmt: skip
    for name in ALL_FIXTURES:
        assert load(name).startswith("# 합성 예시"), name


# --- 해석기: 형식별 ---------------------------------------------------------


def test_pixel_android14_nr_sa() -> None:
    cells = parse("pixel_a14_nr_sa.txt")
    # Phone Id 0/1에 같은 목록이 두 번 나오지만 중복은 제거된다.
    assert len(cells) == 2
    assert cells[0] == {
        "registered": True, "rat": "NR", "arfcn": 632628, "band": "n78", "pci": 301, "tac": "4660",
        "mcc": "001", "mnc": "01", "cell_id": "4660000001", "rsrp_dbm": -88.0, "rsrq_db": -11.0,
        "sinr_db": 18.0, "timing_advance": 3, "freq_mhz": 3489.42,
    }  # fmt: skip
    neighbour = cells[1]
    assert neighbour["registered"] is False
    assert neighbour["pci"] == 302
    assert neighbour["rsrp_dbm"] == -101.0
    # 이웃 셀의 "값 없음" 항목은 빠진다.
    for key in ("tac", "mcc", "mnc", "cell_id", "sinr_db", "timing_advance"):
        assert key not in neighbour


def test_samsung_android13_nr_nsa_with_lte_anchor() -> None:
    cells = parse("samsung_a13_nr_nsa.txt")
    assert [(c["rat"], c["registered"], c["pci"]) for c in cells] == [
        ("LTE", True, 211), ("NR", False, 77), ("LTE", False, 212),
    ]  # fmt: skip
    anchor, nr, lte_neighbour = cells
    assert anchor == {
        "registered": True, "rat": "LTE", "arfcn": 1350, "band": "B3", "pci": 211, "tac": "4321",
        "mcc": "450", "mnc": "05", "cell_id": "1234567", "rsrp_dbm": -93.0, "rsrq_db": -9.0,
        "sinr_db": 14.0, "timing_advance": 4,
    }  # fmt: skip
    assert "freq_mhz" not in anchor  # LTE는 주파수를 채우지 않는다
    assert nr["arfcn"] == 620000 and nr["freq_mhz"] == 3300.0 and nr["band"] == "n78"
    assert (nr["rsrp_dbm"], nr["rsrq_db"], nr["sinr_db"]) == (-97.0, -12.0, 11.0)
    assert "tac" not in nr and "cell_id" not in nr and "mcc" not in nr
    assert "cell_id" not in lte_neighbour and "timing_advance" not in lte_neighbour


def test_android11_older_nr_layout() -> None:
    cells = parse("android11_nr_old.txt")
    assert len(cells) == 1
    cell = cells[0]
    assert cell["registered"] is True  # mRegistered=true 표기
    assert cell["rat"] == "NR" and cell["arfcn"] == 436830 and cell["pci"] == 45
    assert cell["freq_mhz"] == 2184.15
    assert "band" not in cell  # mBands 없는 구형 형식
    assert cell["rsrp_dbm"] == -92.0  # 양수로 나온 RSRP(92)는 부호를 바로잡는다
    assert cell["cell_id"] == "123456789" and cell["tac"] == "100"


def test_lte_only_with_neighbours() -> None:
    cells = parse("lte_only.txt")
    assert [c["rat"] for c in cells] == ["LTE", "LTE", "LTE", "WCDMA"]
    serving = cells[0]
    assert serving["registered"] is True
    assert serving["arfcn"] == 2850 and serving["pci"] == 12 and serving["tac"] == "9001"
    assert serving["sinr_db"] == 12.4  # 구형 rssnr 0.1 dB 단위(124)
    assert serving["timing_advance"] == 1
    assert all(c["registered"] is False for c in cells[1:])
    assert "cell_id" not in cells[2]  # 268435455는 "값 없음"
    assert cells[3] == {"registered": False, "rat": "WCDMA", "arfcn": 10713}
    assert all("freq_mhz" not in c for c in cells)


def test_truncated_output_gives_partial_cell() -> None:
    cells = parse("truncated.txt")
    # 값 중간에서 잘린 mNrArfcn(6326…)은 읽지 않는다.
    assert cells == [{"registered": True, "rat": "NR", "pci": 5, "tac": "7"}]


def test_garbage_gives_nothing() -> None:
    assert parse("garbage.txt") == []


def test_service_state_fallback_when_cell_info_is_empty() -> None:
    cells = parse("samsung_servicestate_only.txt")
    assert cells == [{
        "registered": True, "rat": "NR", "arfcn": 640000, "band": "n78", "pci": 410, "tac": "2000",
        "mcc": "450", "mnc": "05", "cell_id": "55555", "rsrp_dbm": -90.0, "rsrq_db": -10.0,
        "sinr_db": 21.0, "freq_mhz": 3600.0,
    }]  # fmt: skip


# --- 해석기: 공통 성질 -------------------------------------------------------


@pytest.mark.parametrize("name", ALL_FIXTURES)
def test_cells_follow_contract(name: str) -> None:
    for cell in parse(name):
        assert set(cell) <= ALLOWED_KEYS
        assert isinstance(cell["registered"], bool) and isinstance(cell["rat"], str)
        for key in ("arfcn", "pci", "timing_advance"):
            assert key not in cell or (type(cell[key]) is int and cell[key] not in SENTINELS)
        for key in ("band", "tac", "mcc", "mnc", "cell_id"):
            assert key not in cell or isinstance(cell[key], str)
        for key in ("tac", "cell_id"):
            assert key not in cell or int(cell[key]) not in SENTINELS
        for key in ("rsrp_dbm", "rsrq_db", "sinr_db", "freq_mhz"):
            assert key not in cell or (type(cell[key]) is float and abs(cell[key]) < 1e6)


@pytest.mark.parametrize("name", ALL_FIXTURES)
def test_parser_survives_any_truncation(name: str) -> None:
    text = load(name)
    for cut in range(0, len(text), 7):
        assert isinstance(phone.parse_telephony_registry(text[:cut]), list)
        assert isinstance(phone.parse_telephony_registry(text[cut:]), list)


@pytest.mark.parametrize("text", ["", "   ", "{", "}}}}", "CellInfoNr:{", "CellInfoNr:{}", "mCellInfo=null", "\x00\xff"])
def test_parser_odd_inputs(text: str) -> None:
    assert phone.parse_telephony_registry(text) == []


def test_parser_rejects_non_string() -> None:
    assert phone.parse_telephony_registry(None) == []  # type: ignore[arg-type]


def test_all_sentinels_are_omitted() -> None:
    text = (
        "CellInfoNr:{mRegistered=YES CellIdentityNr:{ mPci = 9 mTac = 2147483647 mNrArfcn = 2147483647 "
        "mBands = [2147483647] mMcc = null mMnc = null mNci = 68719476735 } "
        "CellSignalStrengthNr:{ ssRsrp = 2147483647 ssRsrq = 2147483647 ssSinr = 2147483647 "
        "timingAdvance = 2147483647 }}, "
        "CellInfoLte:{mRegistered=NO CellIdentityLte:{ mCi=268435455 mPci=8 mTac=2147483647 "
        "mEarfcn=2147483647 mMcc=2147483647 mMnc=2147483647} "
        "CellSignalStrengthLte: rssi=2147483647 rsrp=2147483647 rsrq=2147483647 rssnr=2147483647 ta=2147483647 }"
    )
    assert phone.parse_telephony_registry(text) == [
        {"registered": True, "rat": "NR", "pci": 9},
        {"registered": False, "rat": "LTE", "pci": 8},
    ]


def test_lte_timing_advance_key_variants() -> None:
    for key in ("ta", "mTa", "timingAdvance"):
        text = f"CellInfoLte:{{mRegistered=YES CellIdentityLte:{{ mPci=1 mEarfcn=300}} CellSignalStrengthLte: rsrp=-90 {key}=6 }}"
        assert phone.parse_telephony_registry(text)[0]["timing_advance"] == 6, key


def test_duplicates_merge_and_registered_first() -> None:
    nr = "CellInfoNr:{{mRegistered={reg} CellIdentityNr:{{ mPci = {pci} mNrArfcn = 620000 }} {sig}}}"
    text = ", ".join([
        nr.format(reg="NO", pci=2, sig=""),
        nr.format(reg="NO", pci=1, sig=""),
        nr.format(reg="YES", pci=1, sig="CellSignalStrengthNr:{ ssRsrp = -80 }"),
    ])  # fmt: skip
    cells = phone.parse_telephony_registry(text)
    assert [(c["pci"], c["registered"]) for c in cells] == [(1, True), (2, False)]
    assert cells[0]["rsrp_dbm"] == -80.0


# --- NR-ARFCN → 주파수 (TS 38.104 5.4.2.1, Table 5.4.2.1-1) ------------------


@pytest.mark.parametrize(
    ("arfcn", "freq_mhz"),
    [
        (0, 0.0),
        (436830, 2184.15),  # 5 kHz × 436830
        (599999, 2999.995),
        (600000, 3000.0),
        (620000, 3300.0),  # 3000 + 0.015 × 20000
        (632628, 3489.42),  # 3000 + 0.015 × 32628
        (2016666, 24249.99),  # 3000 + 0.015 × 1416666
        (2016667, 24250.08),
        (2079167, 28000.08),  # 24250.08 + 0.06 × 62500
        (3279165, 99999.96),  # 24250.08 + 0.06 × 1262498
    ],
)
def test_nr_arfcn_to_freq(arfcn: int, freq_mhz: float) -> None:
    assert phone.nr_arfcn_to_freq_mhz(arfcn) == pytest.approx(freq_mhz, abs=1e-9)


@pytest.mark.parametrize("bad", [-1, 3279166, 10**9, 1.5, "620000", True, None])
def test_nr_arfcn_out_of_range(bad: Any) -> None:
    with pytest.raises(ValueError):
        phone.nr_arfcn_to_freq_mhz(bad)


# --- read_phone (가짜 실행기) ------------------------------------------------

SERIAL = "TESTSERIAL0001"
DEVICES_OK = f"List of devices attached\n{SERIAL}\tdevice\n\n"


class FakeRunner:
    """adb 대신 정해진 출력을 돌려주고, 받은 명령을 기록한다."""

    def __init__(self, devices: tuple[int, str], dump: tuple[int, str] = (0, ""), model: str = "Test Phone 1\n"):
        self.devices = devices
        self.dump = dump
        self.model = model
        self.calls: list[tuple[list[str], float]] = []

    def __call__(self, cmd: Sequence[str], timeout: float) -> tuple[int, str]:
        self.calls.append((list(cmd), timeout))
        if "devices" in cmd:
            return self.devices
        if "getprop" in cmd:
            return 0, self.model
        return self.dump


def test_read_phone_ok() -> None:
    runner = FakeRunner((0, DEVICES_OK), (0, load("pixel_a14_nr_sa.txt")))
    result = phone.read_phone("adb", runner)
    assert result["status"] == "ok"
    assert result["device"] == f"Test Phone 1 ({SERIAL})"
    assert len(result["cells"]) == 2 and result["cells"][0]["pci"] == 301
    assert "raw" not in result
    assert set(result) <= {"status", "device", "cells", "raw", "limits"}
    limits = " ".join(result["limits"])
    assert all(isinstance(line, str) and "\n" not in line for line in result["limits"])
    assert "SIB" in limits and "iPhone" in limits and "제조사" in limits


def test_read_phone_issues_only_allowed_read_only_commands() -> None:
    runner = FakeRunner((0, DEVICES_OK), (0, load("samsung_a13_nr_nsa.txt")))
    phone.read_phone("/opt/platform-tools/adb", runner)
    assert [cmd for cmd, _ in runner.calls] == [
        ["/opt/platform-tools/adb", "devices"],
        ["/opt/platform-tools/adb", "-s", SERIAL, "shell", "getprop", "ro.product.model"],
        ["/opt/platform-tools/adb", "-s", SERIAL, "shell", "dumpsys", "telephony.registry"],
    ]
    assert all(0 < timeout <= 30 for _, timeout in runner.calls)
    assert phone.ALLOWED_ADB_COMMANDS == (
        ("devices",),
        ("shell", "getprop", "ro.product.model"),
        ("shell", "dumpsys", "telephony.registry"),
    )
    forbidden = {
        "setprop", "settings", "put", "svc", "am", "pm", "input", "reboot", "root", "remount", "push",
        "install", "uninstall", "rm", "su", "tcpip", "kill-server", "start-server", "call", "cmd", "wm",
    }  # fmt: skip
    for cmd, _ in runner.calls:
        assert not forbidden & set(cmd), cmd


def test_run_adb_refuses_commands_outside_allow_list() -> None:
    runner = FakeRunner((0, DEVICES_OK))
    with pytest.raises(ValueError):
        phone._run_adb(runner, "adb", SERIAL, ("shell", "svc", "data", "disable"), 5.0)
    assert runner.calls == []


def test_read_phone_no_adb(monkeypatch: pytest.MonkeyPatch) -> None:
    # adb를 찾지 못한 경우: 실행기를 아예 부르지 않는다.
    monkeypatch.setattr(phone.shutil, "which", lambda _name: None)
    runner = FakeRunner((0, DEVICES_OK))
    result = phone.read_phone(None, runner)
    assert result["status"] == "no_adb" and result["cells"] == [] and result["limits"]
    assert runner.calls == []
    # 경로는 있지만 실행 파일이 없는 경우(종료 코드 127 또는 FileNotFoundError).
    assert phone.read_phone("adb", FakeRunner((phone.RC_NOT_FOUND, "")))["status"] == "no_adb"

    def missing(cmd: Sequence[str], timeout: float) -> tuple[int, str]:
        raise FileNotFoundError(cmd[0])

    assert phone.read_phone("adb", missing)["status"] == "no_adb"


@pytest.mark.parametrize(
    ("devices_out", "hint"),
    [
        ("List of devices attached\n\n", None),
        (f"List of devices attached\n{SERIAL}\tunauthorized\n", phone.LIMIT_UNAUTHORIZED),
        (f"List of devices attached\n{SERIAL}\toffline\n", phone.LIMIT_OFFLINE),
        ("* daemon not running; starting now at tcp:5037\n* daemon started successfully\nList of devices attached\n", None),
    ],
)
def test_read_phone_no_device(devices_out: str, hint: str | None) -> None:
    runner = FakeRunner((0, devices_out))
    result = phone.read_phone("adb", runner)
    assert result["status"] == "no_device" and result["cells"] == []
    assert "device" not in result
    assert len(runner.calls) == 1  # 기기가 없으면 shell 명령을 보내지 않는다
    assert (hint in result["limits"]) if hint else (len(result["limits"]) == len(phone.LIMITS))


def test_read_phone_devices_timeout_is_no_device() -> None:
    assert phone.read_phone("adb", FakeRunner((phone.RC_TIMEOUT, "")))["status"] == "no_device"


def test_read_phone_unparsed_keeps_raw() -> None:
    runner = FakeRunner((0, DEVICES_OK), (0, load("garbage.txt")))
    result = phone.read_phone("adb", runner)
    assert result["status"] == "unparsed" and result["cells"] == []
    assert result["device"].endswith(f"({SERIAL})")
    assert "mCellInfo=null" in result["raw"]


def test_read_phone_unparsed_raw_is_truncated() -> None:
    huge = "no cell lines here\n" * 5000 + "mCellInfo=null " + "x" * 200_000
    result = phone.read_phone("adb", FakeRunner((0, DEVICES_OK), (0, huge)))
    assert result["status"] == "unparsed"
    assert len(result["raw"]) <= phone.RAW_MAX_CHARS + 20
    assert result["raw"].startswith("mCellInfo=null")  # 셀 관련 줄을 우선 보여준다


def test_read_phone_dumpsys_failure_is_unparsed() -> None:
    result = phone.read_phone("adb", FakeRunner((0, DEVICES_OK), (phone.RC_TIMEOUT, ""), model=""))
    assert result["status"] == "unparsed" and result["raw"] == ""
    assert result["device"] == SERIAL  # 모델명을 못 읽으면 일련번호만


def test_read_phone_picks_first_authorized_device() -> None:
    devices = f"List of devices attached\nOTHER0000\tunauthorized\n{SERIAL}\tdevice\nTHIRD0000\tdevice\n"
    runner = FakeRunner((0, devices), (0, load("lte_only.txt")))
    assert phone.read_phone("adb", runner)["status"] == "ok"
    assert all(cmd[1:3] == ["-s", SERIAL] for cmd, _ in runner.calls[1:])


# --- SDR 대조, 스캔 출발점 ---------------------------------------------------


def test_compare_with_sdr_same_pci_and_offset() -> None:
    cell = parse("pixel_a14_nr_sa.txt")[0]  # PCI 301, 3489.42 MHz
    result = phone.compare_with_sdr(cell, {"pci": 301, "ss_ref_hz": 3_490_560_000.0})
    assert result["pci_match"] is True
    assert result["freq_delta_mhz"] == pytest.approx(1.14)
    assert "SSB" in result["note"]
    assert "정확히 일치" not in result["note"]  # 같은 셀이라고 단정하지 않는다


def test_compare_with_sdr_different_pci() -> None:
    cell = parse("pixel_a14_nr_sa.txt")[0]
    result = phone.compare_with_sdr(cell, {"pci": 12, "ss_ref_hz": 3_489_420_000.0})
    assert result["pci_match"] is False and result["freq_delta_mhz"] == 0.0
    assert "다릅니다" in result["note"]


def test_compare_with_sdr_without_phone_frequency_or_pci() -> None:
    lte = parse("lte_only.txt")[0]
    result = phone.compare_with_sdr(lte, {"pci": 12, "ss_ref_hz": 1_850_000_000.0})
    assert result["pci_match"] is True and result["freq_delta_mhz"] is None
    result = phone.compare_with_sdr({"rat": "NR", "arfcn": 620000}, {"pci": 1, "ss_ref_hz": 3.3e9})
    assert result["pci_match"] is False and result["freq_delta_mhz"] == 0.0
    assert set(result) == {"pci_match", "freq_delta_mhz", "note"}
    assert phone.compare_with_sdr({}, {})["freq_delta_mhz"] is None


def test_scan_hint() -> None:
    cell = parse("samsung_a13_nr_nsa.txt")[1]
    assert phone.scan_hint(cell) == {"center_freq_hz": 3_300_000_000.0, "band": "n78"}
    # freq_mhz가 없어도 NR-ARFCN에서 구한다. 대역을 모르면 None.
    assert phone.scan_hint({"rat": "NR", "arfcn": 436830}) == {"center_freq_hz": 2_184_150_000.0, "band": None}


def test_scan_hint_needs_frequency() -> None:
    with pytest.raises(ValueError):
        phone.scan_hint(parse("lte_only.txt")[0])
    with pytest.raises(ValueError):
        phone.scan_hint({"rat": "NR"})


def test_modem_diag_is_placeholder_only() -> None:
    with pytest.raises(NotImplementedError):
        phone.read_modem_diag()
