"""휴대폰 연동(M9): adb로 Android 휴대폰이 잡고 있는 셀 정보를 읽는다. (SPEC 10절)

원칙
- **읽기 전용**이다. 휴대폰 상태를 바꾸는 adb 명령은 쓰지 않는다. 허용 명령은 `ALLOWED_ADB_COMMANDS`에
  고정되어 있고, 그 밖의 명령은 `_run_adb`가 거부한다.
- 출력 형식은 Android 버전·제조사마다 다르다. 해석기는 정규식 기반으로 관대하게 만들었고, 해석에
  실패하면 원문을 돌려주어 화면이 계속 진행할 수 있게 한다. (SPEC 16절)
- 루팅 없이는 SIB 원문을 얻을 수 없다. 모뎀 진단 포트 연동은 범위 밖이며 `read_modem_diag`에 자리만 둔다.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from collections.abc import Callable, Sequence
from typing import Any

# (종료 코드, 표준출력+표준오류). 실행 파일 없음은 127, 시간 초과는 124로 통일한다.
Runner = Callable[[Sequence[str], float], tuple[int, str]]

RC_NOT_FOUND = 127
RC_TIMEOUT = 124

# 허용하는 adb 인자 목록(기기 지정 `-s <serial>` 제외). 전부 읽기 전용 조회다.
ALLOWED_ADB_COMMANDS: tuple[tuple[str, ...], ...] = (
    ("devices",),
    ("shell", "getprop", "ro.product.model"),
    ("shell", "dumpsys", "telephony.registry"),
)

TIMEOUT_DEVICES_S = 10.0
TIMEOUT_GETPROP_S = 5.0
TIMEOUT_DUMPSYS_S = 15.0

RAW_MAX_CHARS = 16000

LIMITS: tuple[str, ...] = (
    "루팅 없이는 SIB 원문(SIB1, SIB19 등)을 휴대폰에서 읽을 수 없습니다. 셀 식별 정보와 신호 세기만 가져옵니다.",
    "출력 형식이 Android 버전과 제조사마다 달라 일부 항목이 비어 있을 수 있습니다. 해석하지 못하면 원문을 보여줍니다.",
    "휴대폰이 알려주는 NR-ARFCN은 모뎀이 보고한 값이며, SDR이 찾은 SSB 중심 주파수와 정확히 같지 않을 수 있습니다.",
    "위치 권한이나 제조사 정책에 따라 셀 ID, TAC, 이웃 셀 목록이 가려질 수 있습니다.",
    "iPhone은 지원하지 않습니다.",
)

LIMIT_UNAUTHORIZED = "휴대폰 화면에서 'USB 디버깅 허용'을 눌러야 읽을 수 있습니다."
LIMIT_OFFLINE = "휴대폰이 offline 상태입니다. 케이블을 다시 연결해 보세요."


# ---------------------------------------------------------------------------
# NR-ARFCN → 주파수
# ---------------------------------------------------------------------------

# TS 38.104 5.4.2.1절, Table 5.4.2.1-1 (NR-ARFCN parameters for the global frequency raster).
# specs/38104-j60.txt 원문에서 확인한 값:
#   주파수 범위(MHz)   ΔF_Global(kHz)  F_REF-Offs(MHz)  N_REF-Offs  N_REF 범위
#   0 – 3000           5               0                0           0 – 599999
#   3000 – 24250       15              3000             600000      600000 – 2016666
#   24250 – 100000     60              24250.08         2016667     2016667 – 3279165
# 식: F_REF = F_REF-Offs + ΔF_Global (N_REF – N_REF-Offs)
# 부동소수 오차를 피하려고 kHz 정수로 계산한다. (N_REF 하한, N_REF 상한, ΔF kHz, F_REF-Offs kHz, N_REF-Offs)
_NR_RASTER: tuple[tuple[int, int, int, int, int], ...] = (
    (0, 599999, 5, 0, 0),
    (600000, 2016666, 15, 3_000_000, 600000),
    (2016667, 3279165, 60, 24_250_080, 2016667),
)

NR_ARFCN_MAX = 3279165
NR_ARFCN_SPEC_REF = "TS 38.104 5.4.2.1, Table 5.4.2.1-1"


def nr_arfcn_to_freq_mhz(arfcn: int) -> float:
    """NR-ARFCN(N_REF)을 RF 기준 주파수 F_REF(MHz)로 바꾼다. (TS 38.104 5.4.2.1절, Table 5.4.2.1-1)

    범위 [0, 3279165] 밖이면 ValueError.
    """
    if isinstance(arfcn, bool) or not isinstance(arfcn, int):
        raise ValueError(f"NR-ARFCN은 정수여야 합니다: {arfcn!r}")
    for n_lo, n_hi, delta_khz, f_offs_khz, n_offs in _NR_RASTER:
        if n_lo <= arfcn <= n_hi:
            return (f_offs_khz + delta_khz * (arfcn - n_offs)) / 1000.0
    raise ValueError(f"NR-ARFCN 범위(0…{NR_ARFCN_MAX}) 밖입니다: {arfcn}")


# ---------------------------------------------------------------------------
# dumpsys telephony.registry 해석
# ---------------------------------------------------------------------------

_RATS: dict[str, str] = {
    "nr": "NR",
    "lte": "LTE",
    "wcdma": "WCDMA",
    "gsm": "GSM",
    "tdscdma": "TDSCDMA",
    "cdma": "CDMA",
}
_RAT_ALT = "Nr|Lte|Wcdma|Gsm|Tdscdma|Cdma"

_CELL_INFO_RE = re.compile(rf"CellInfo({_RAT_ALT})\b\s*:?\s*\{{")
_CELL_IDENTITY_RE = re.compile(rf"CellIdentity({_RAT_ALT})\b\s*:?\s*\{{")
_CELL_SIGNAL_RE = re.compile(rf"CellSignalStrength({_RAT_ALT})\b\s*:?")
_REGISTERED_RE = re.compile(r"(?<![A-Za-z])(?:mRegistered|isRegistered|registered)\s*[=:]\s*(\w+)")
_REG_STATE_RE = re.compile(r"registrationState\s*=\s*(\w+)")
_BANDS_RE = re.compile(r"(?<![A-Za-z])mBands\s*=\s*\[([^\]]*)\]")

# "값 없음"을 뜻하는 표식. Android는 Integer.MAX_VALUE(2147483647), Long.MAX_VALUE를 주로 쓴다.
_INT_SENTINELS: frozenset[int] = frozenset({2147483647, -2147483648, 9223372036854775807})
# 셀 ID 전용: LTE CI 28비트 전부 1(268435455), NR NCI 36비트 전부 1(68719476735).
_CELL_ID_SENTINELS: frozenset[int] = frozenset({268435455, 68719476735})
_WORD_SENTINELS: frozenset[str] = frozenset({"", "null", "none", "unknown", "unavailable", "n/a", "nan"})


def _field(segment: str, *keys: str) -> str | None:
    """`key = value` 또는 `key=value` 꼴에서 처음 나오는 값을 문자열로 돌려준다.

    값 뒤에 구분 문자가 있어야 한다. 출력이 값 중간에서 잘렸을 때 잘린 숫자를 값으로 읽지 않기 위해서다.
    """
    for key in keys:
        m = re.search(
            rf"(?<![A-Za-z0-9_]){re.escape(key)}\s*=\s*([^\s,;{{}}\[\]]+)(?=[\s,;{{}}\[\]])", segment
        )
        if m:
            return m.group(1)
    return None


def _to_int(value: str | None, *, extra_sentinels: frozenset[int] = frozenset()) -> int | None:
    """정수로 바꾼다. 숫자가 아니거나 "값 없음" 표식이면 None."""
    if value is None or not re.fullmatch(r"[-+]?\d{1,19}", value):
        return None
    number = int(value)
    if number in _INT_SENTINELS or number in extra_sentinels:
        return None
    return number


def _non_negative(value: str | None, *, extra_sentinels: frozenset[int] = frozenset()) -> int | None:
    number = _to_int(value, extra_sentinels=extra_sentinels)
    return number if number is not None and number >= 0 else None


def _plmn_part(value: str | None, lengths: tuple[int, ...]) -> str | None:
    """MCC/MNC. 자릿수가 맞는 숫자열만 받아들인다(가려진 값, null은 버린다)."""
    if value is None:
        return None
    value = value.strip("\"'")
    if value.lower() in _WORD_SENTINELS or not value.isdigit() or len(value) not in lengths:
        return None
    return value


def _block_end(text: str, open_idx: int, hard_end: int) -> int:
    """`open_idx`의 여는 중괄호와 짝이 맞는 닫는 중괄호 다음 위치. 짝이 없으면(잘린 출력) 줄 끝까지."""
    depth = 0
    for i in range(open_idx, hard_end):
        ch = text[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return i + 1
    newline = text.find("\n", open_idx, hard_end)
    return newline if newline != -1 else hard_end


def _parse_registered(segment: str) -> bool:
    m = _REGISTERED_RE.search(segment)
    return m is not None and m.group(1).lower() in {"yes", "true", "1"}


def _parse_band(segment: str, rat: str) -> str | None:
    m = _BANDS_RE.search(segment)
    if not m:
        return None
    for token in re.findall(r"\d+", m.group(1)):
        number = int(token)
        if 0 < number < 2147483647:
            # 여러 개가 있으면 첫 번째만 쓴다. NR은 "n78", LTE는 "B3" 표기.
            return f"n{number}" if rat == "NR" else f"B{number}"
    return None


def _parse_identity(segment: str, rat: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    pci: int | None
    if rat == "NR":
        arfcn = _non_negative(_field(segment, "mNrArfcn", "mNrarfcn", "nrArfcn", "nrarfcn"))
        pci = _non_negative(_field(segment, "mPci", "pci"))
        cell_id = _non_negative(_field(segment, "mNci", "nci"), extra_sentinels=_CELL_ID_SENTINELS)
        tac = _non_negative(_field(segment, "mTac", "tac"))
    elif rat == "LTE":
        arfcn = _non_negative(_field(segment, "mEarfcn", "earfcn"))
        pci = _non_negative(_field(segment, "mPci", "pci"))
        cell_id = _non_negative(_field(segment, "mCi", "ci"), extra_sentinels=_CELL_ID_SENTINELS)
        tac = _non_negative(_field(segment, "mTac", "tac"))
    else:
        # 2G/3G는 참고용으로 최소한만 읽는다. (PSC/BSIC은 PCI가 아니므로 pci에 넣지 않는다.)
        arfcn = _non_negative(_field(segment, "mUarfcn", "mArfcn", "mBcch"))
        pci = None
        cell_id = _non_negative(_field(segment, "mCid", "mBasestationId"), extra_sentinels=_CELL_ID_SENTINELS)
        tac = _non_negative(_field(segment, "mLac"))
    if arfcn is not None:
        out["arfcn"] = arfcn
    band = _parse_band(segment, rat)
    if band is not None:
        out["band"] = band
    if pci is not None and pci <= 1007:  # NR PCI 0…1007, LTE PCI 0…503
        out["pci"] = pci
    if tac is not None:
        out["tac"] = str(tac)
    mcc = _plmn_part(_field(segment, "mMcc", "mcc"), (3,))
    mnc = _plmn_part(_field(segment, "mMnc", "mnc"), (2, 3))
    if mcc is not None:
        out["mcc"] = mcc
    if mnc is not None:
        out["mnc"] = mnc
    if cell_id is not None:
        out["cell_id"] = str(cell_id)
    return out


def _parse_signal(segment: str, rat: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if rat == "NR":
        rsrp = _to_int(_field(segment, "ssRsrp", "mSsRsrp"))
        rsrq = _to_int(_field(segment, "ssRsrq", "mSsRsrq"))
        sinr = _to_int(_field(segment, "ssSinr", "mSsSinr"))
        ta = _non_negative(_field(segment, "timingAdvance", "mTimingAdvance", "timingAdvanceMicros"))
    elif rat == "LTE":
        rsrp = _to_int(_field(segment, "rsrp", "mRsrp"))
        rsrq = _to_int(_field(segment, "rsrq", "mRsrq"))
        sinr = _to_int(_field(segment, "rssnr", "mRssnr"))
        ta = _non_negative(_field(segment, "ta", "mTa", "mTimingAdvance", "timingAdvance"))
    else:
        return out
    if rsrp is not None:
        # 일부 구형 기기는 RSRP를 양수(부호 뒤집힌 값)로 내보낸다. 44…140이면 음수로 바로잡는다.
        if 44 <= rsrp <= 140:
            rsrp = -rsrp
        if -156 <= rsrp <= -20:
            out["rsrp_dbm"] = float(rsrp)
    if rsrq is not None and -50 <= rsrq <= 30:
        out["rsrq_db"] = float(rsrq)
    if sinr is not None:
        value = float(sinr)
        # LTE rssnr은 구형 Android에서 0.1 dB 단위였다. dB 범위(-20…30)를 벗어나면 0.1 dB 단위로 본다.
        # 범위 안의 값은 어느 단위인지 구별할 수 없어 그대로 dB로 둔다.
        if rat == "LTE" and not -20 <= value <= 30:
            value = value / 10.0
        if -40 <= value <= 60:
            out["sinr_db"] = value
    if ta is not None:
        out["timing_advance"] = ta
    return out


def _finish_cell(cell: dict[str, Any]) -> dict[str, Any] | None:
    """식별 정보가 하나도 없으면 버리고, NR이면 주파수를 채운다."""
    if not any(key in cell for key in ("arfcn", "pci", "cell_id")):
        return None
    if cell["rat"] == "NR" and "arfcn" in cell:
        try:
            cell["freq_mhz"] = nr_arfcn_to_freq_mhz(cell["arfcn"])
        except ValueError:
            pass
    # LTE EARFCN → 주파수(TS 36.101 5.7.3절)는 specs/에 원문이 없어 확인할 수 없으므로 넣지 않는다.
    return cell


def _cells_from_cell_info(text: str) -> list[dict[str, Any]]:
    cells: list[dict[str, Any]] = []
    matches = list(_CELL_INFO_RE.finditer(text))
    for i, m in enumerate(matches):
        hard_end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        segment = text[m.start() : _block_end(text, m.end() - 1, hard_end)]
        rat = _RATS[m.group(1).lower()]
        cell: dict[str, Any] = {"registered": _parse_registered(segment), "rat": rat}
        cell.update(_parse_identity(segment, rat))
        cell.update(_parse_signal(segment, rat))
        finished = _finish_cell(cell)
        if finished is not None:
            cells.append(finished)
    return cells


def _cells_from_service_state(text: str) -> list[dict[str, Any]]:
    """mCellInfo가 비어 있을 때의 대안: ServiceState의 CellIdentity와 mSignalStrength를 짝짓는다."""
    signals: dict[str, dict[str, Any]] = {}
    for m in _CELL_SIGNAL_RE.finditer(text):
        rat = _RATS[m.group(1).lower()]
        if rat in signals:
            continue
        rest = text[m.end() : m.end() + 600]
        nxt = _CELL_SIGNAL_RE.search(rest)
        if nxt:
            rest = rest[: nxt.start()]
        signal = _parse_signal(rest.split("\n", 1)[0], rat)
        if signal:
            signals[rat] = signal

    cells: list[dict[str, Any]] = []
    for m in _CELL_IDENTITY_RE.finditer(text):
        rat = _RATS[m.group(1).lower()]
        segment = text[m.start() : _block_end(text, m.end() - 1, len(text))]
        # 같은 NetworkRegistrationInfo 안의 registrationState가 HOME/ROAMING이면 등록된 셀로 본다.
        states = _REG_STATE_RE.findall(text[max(0, m.start() - 600) : m.start()])
        registered = bool(states) and states[-1].upper() in {"HOME", "ROAMING"}
        cell: dict[str, Any] = {"registered": registered, "rat": rat}
        cell.update(_parse_identity(segment, rat))
        if registered:
            cell.update(signals.get(rat, {}))
        finished = _finish_cell(cell)
        if finished is not None:
            cells.append(finished)
    return cells


def _dedupe(cells: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """같은 셀(RAT·ARFCN·PCI·셀 ID)을 하나로 합친다. 등록된 셀을 앞에 둔다."""
    merged: dict[tuple[Any, ...], dict[str, Any]] = {}
    for cell in cells:
        key = (cell["rat"], cell.get("arfcn"), cell.get("pci"), cell.get("cell_id"))
        prev = merged.get(key)
        if prev is None:
            merged[key] = cell
            continue
        prev["registered"] = prev["registered"] or cell["registered"]
        for name, value in cell.items():
            prev.setdefault(name, value)
    return sorted(merged.values(), key=lambda c: not c["registered"])  # 안정 정렬


def parse_telephony_registry(text: str) -> list[dict[str, Any]]:
    """`dumpsys telephony.registry` 출력에서 셀 목록을 뽑는다.

    - `CellInfoNr`/`CellInfoLte`(및 2G/3G) 블록을 찾고, 없으면 ServiceState의 `CellIdentity*`로 대신한다.
    - "값 없음" 표식(2147483647, 268435455 등)인 항목은 결과에서 뺀다.
    - 잘렸거나 이상한 입력에도 예외를 내지 않고 읽을 수 있는 만큼만 돌려준다.
    """
    if not isinstance(text, str) or not text:
        return []
    try:
        cells = _cells_from_cell_info(text)
        if not cells:
            cells = _cells_from_service_state(text)
        return _dedupe(cells)
    except Exception:  # 해석기는 어떤 입력에도 죽지 않아야 한다 (SPEC 16절)
        return []


# ---------------------------------------------------------------------------
# adb 실행
# ---------------------------------------------------------------------------


def _subprocess_runner(cmd: Sequence[str], timeout: float) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            list(cmd), capture_output=True, text=True, timeout=timeout, errors="replace", check=False
        )
    except FileNotFoundError:
        return RC_NOT_FOUND, ""
    except subprocess.TimeoutExpired:
        return RC_TIMEOUT, ""
    except OSError as exc:
        return RC_NOT_FOUND, str(exc)
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def _run_adb(
    runner: Runner, adb: str, serial: str | None, args: tuple[str, ...], timeout: float
) -> tuple[int, str]:
    """허용 목록에 있는 읽기 전용 명령만 실행한다."""
    if args not in ALLOWED_ADB_COMMANDS:
        raise ValueError(f"허용되지 않은 adb 명령입니다: {' '.join(args)}")
    cmd = [adb, *(["-s", serial] if serial else []), *args]
    try:
        rc, out = runner(cmd, timeout)
    except FileNotFoundError:
        return RC_NOT_FOUND, ""
    except subprocess.TimeoutExpired:
        return RC_TIMEOUT, ""
    return rc, out if isinstance(out, str) else ""


def _parse_devices(text: str) -> list[tuple[str, str]]:
    """`adb devices` 출력 → [(serial, 상태)]. 상태는 device / unauthorized / offline 등."""
    devices: list[tuple[str, str]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith(("List of devices", "*")):
            continue
        parts = line.split()
        if len(parts) >= 2:
            devices.append((parts[0], parts[1]))
    return devices


_RAW_KEYWORDS = ("Cell", "SignalStrength", "ServiceState")


def _raw_excerpt(text: str) -> str:
    """화면에 보여줄 원문. 셀 관련 줄을 우선 고르고 길이를 제한한다."""
    lines = [line for line in text.splitlines() if any(k in line for k in _RAW_KEYWORDS)]
    excerpt = "\n".join(lines) if lines else text
    if len(excerpt) > RAW_MAX_CHARS:
        excerpt = excerpt[:RAW_MAX_CHARS] + "\n…(잘림)"
    return excerpt


def read_phone(adb_path: str | None = None, runner: Runner = _subprocess_runner) -> dict[str, Any]:
    """adb로 연결된 Android 휴대폰의 셀 정보를 읽는다. 읽기 전용 명령만 쓴다.

    status: "ok"(셀 해석됨) / "no_adb"(adb 없음) / "no_device"(승인된 기기 없음) / "unparsed"(원문만 있음)
    """
    limits = list(LIMITS)
    adb = adb_path or shutil.which("adb")
    if not adb:
        return {"status": "no_adb", "cells": [], "limits": limits}

    rc, out = _run_adb(runner, adb, None, ("devices",), TIMEOUT_DEVICES_S)
    if rc == RC_NOT_FOUND:
        return {"status": "no_adb", "cells": [], "limits": limits}
    devices = _parse_devices(out) if rc == 0 else []
    ready = [serial for serial, state in devices if state == "device"]
    if not ready:
        states = {state for _, state in devices}
        if "unauthorized" in states:
            limits.insert(0, LIMIT_UNAUTHORIZED)
        elif "offline" in states:
            limits.insert(0, LIMIT_OFFLINE)
        return {"status": "no_device", "cells": [], "limits": limits}

    serial = ready[0]  # 여러 대면 첫 번째 기기를 쓴다
    rc, model_out = _run_adb(runner, adb, serial, ("shell", "getprop", "ro.product.model"), TIMEOUT_GETPROP_S)
    model = model_out.strip().splitlines()[0].strip() if rc == 0 and model_out.strip() else ""
    device = f"{model} ({serial})" if model else serial

    rc, dump = _run_adb(runner, adb, serial, ("shell", "dumpsys", "telephony.registry"), TIMEOUT_DUMPSYS_S)
    cells = parse_telephony_registry(dump) if rc == 0 else []
    if cells:
        return {"status": "ok", "device": device, "cells": cells, "limits": limits}
    return {"status": "unparsed", "device": device, "cells": [], "raw": _raw_excerpt(dump), "limits": limits}


def read_modem_diag() -> dict[str, Any]:
    """모뎀 진단 포트(루팅 필요) 연동 자리. 이번 범위 밖이라 구현하지 않는다. (SPEC 10절)"""
    raise NotImplementedError("모뎀 진단 포트 연동은 이번 범위에 포함되지 않습니다.")


# ---------------------------------------------------------------------------
# SDR 결과와 대조, 스캔 출발점
# ---------------------------------------------------------------------------


def _phone_freq_mhz(phone_cell: dict[str, Any]) -> float | None:
    freq = phone_cell.get("freq_mhz")
    if isinstance(freq, (int, float)) and not isinstance(freq, bool):
        return float(freq)
    arfcn = phone_cell.get("arfcn")
    if phone_cell.get("rat") == "NR" and isinstance(arfcn, int):
        try:
            return nr_arfcn_to_freq_mhz(arfcn)
        except ValueError:
            return None
    return None


def compare_with_sdr(phone_cell: dict[str, Any], sdr: dict[str, Any]) -> dict[str, Any]:
    """휴대폰이 보고한 셀과 SDR 복호 결과(`{"pci", "ss_ref_hz"}`)를 대조한다.

    PCI가 같은지와 주파수 거리(SDR − 휴대폰, MHz)만 알려준다. 휴대폰의 NR-ARFCN은 모뎀이 보고한
    값이라 SDR이 찾은 SSB 중심과 같다는 보장이 없으므로 "정확히 일치"라고 판정하지 않는다.
    """
    phone_pci = phone_cell.get("pci")
    sdr_pci = sdr.get("pci")
    pci_match = isinstance(phone_pci, int) and isinstance(sdr_pci, int) and phone_pci == sdr_pci

    phone_freq = _phone_freq_mhz(phone_cell)
    sdr_hz = sdr.get("ss_ref_hz")
    delta: float | None = None
    if phone_freq is not None and isinstance(sdr_hz, (int, float)) and not isinstance(sdr_hz, bool):
        delta = round(float(sdr_hz) / 1e6 - phone_freq, 6)

    if phone_pci is None:
        note = "휴대폰이 PCI를 알려주지 않아 PCI를 대조할 수 없습니다."
    elif pci_match:
        note = "PCI가 같습니다."
    else:
        note = f"PCI가 다릅니다(휴대폰 {phone_pci}, SDR {sdr_pci}). 다른 셀을 보고 있을 수 있습니다."
    if delta is None:
        note += " 주파수는 비교할 수 없습니다(휴대폰 쪽 주파수를 알 수 없음)."
    else:
        note += (
            f" 주파수 차이는 {delta:+.3f} MHz(SDR − 휴대폰)입니다. 휴대폰의 NR-ARFCN은 모뎀이 보고한 값으로,"
            " SDR이 찾은 SSB 중심 주파수와 같지 않을 수 있어 차이가 있어도 같은 셀일 수 있습니다."
        )
    return {"pci_match": pci_match, "freq_delta_mhz": delta, "note": note}


def scan_hint(phone_cell: dict[str, Any]) -> dict[str, Any]:
    """ "이 셀을 SDR로 따라가기"용 출발점: 중심 주파수(Hz)와 대역.

    NR 셀의 ARFCN에서 주파수를 구한다(TS 38.104 5.4.2.1절). 주파수를 알 수 없으면 ValueError.
    """
    freq = _phone_freq_mhz(phone_cell)
    if freq is None:
        raise ValueError("이 셀은 주파수를 알 수 없어 SDR 스캔 출발점을 만들 수 없습니다.")
    band = phone_cell.get("band")
    return {"center_freq_hz": round(freq * 1e6, 3), "band": band if isinstance(band, str) else None}
