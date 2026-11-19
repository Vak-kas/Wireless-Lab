"""꽂힌 SDR 을 USB 번호로 알아보기(usb_sdr). 운영체제 명령은 부르지 않고 견본으로 시험한다."""
from pathlib import Path

import pytest
from nrtrail import devices, usb_sdr

IOREG = """+-o Root  <class IORegistryEntry, id 0x100000100, retain 30>
  +-o AppleT8122USBXHCI@00000000  <class AppleT8122USBXHCI, id 0x1000004a1, registered, matched, active, busy 0, retain 60>
    +-o USB3.0 Hub@00100000  <class IOUSBHostDevice, id 0x100003a01, registered, matched, active, busy 0, retain 30>
    |   {
    |     "idProduct" = 1558
    |     "idVendor" = 3034
    |     "USB Product Name" = "USB3.0 Hub"
    |   }
    +-o B200-mini@00110000  <class IOUSBHostDevice, id 0x100003a22, registered, matched, active, busy 0, retain 30>
        {
          "idProduct" = 33
          "kUSBSerialNumberString" = "TESTSER1"
          "idVendor" = 9472
          "kUSBProductString" = "USRP B200-mini"
        }
"""


def test_ioreg_devices_are_read_with_ids_and_serial() -> None:
    found = usb_sdr.parse_ioreg(IOREG)
    assert {"vid": 0x2500, "pid": 0x0021, "serial": "TESTSER1", "product": "USRP B200-mini"} in found
    assert {"vid": 3034, "pid": 1558, "serial": "", "product": "USB3.0 Hub"} in found


def test_windows_device_ids() -> None:
    text = "USB\\\\VID_2500&PID_0020\\\\30F1234\\r\\nUSB\\\\VID_046D&PID_C52B\\\\5&1A2B3C\\r\\n".replace("\\\\", "\\").replace("\\r\\n", "\r\n")
    assert usb_sdr.parse_pnp(text)[0] == {"vid": 0x2500, "pid": 0x0020, "serial": "30F1234", "product": ""}


def test_linux_sysfs(tmp_path: Path) -> None:
    dev = tmp_path / "1-2"
    dev.mkdir()
    for name, value in (("idVendor", "2500"), ("idProduct", "0022"), ("serial", "ABC"), ("product", "B205-mini")):
        (dev / name).write_text(value + "\n", encoding="utf-8")
    (tmp_path / "usb1").mkdir()
    (tmp_path / "usb1" / "idVendor").write_text("zzzz", encoding="utf-8")      # 못 읽는 장치는 건너뛴다
    assert usb_sdr.read_sysfs(tmp_path) == [{"vid": 0x2500, "pid": 0x0022, "serial": "ABC", "product": "B205-mini"}]


def test_only_known_sdrs_are_listed_and_marked_as_needing_pro() -> None:
    out = usb_sdr.recognise(usb_sdr.parse_ioreg(IOREG))
    assert out == [{"id": "locked:usrp:TESTSER1", "label": "USRP B200mini (TESTSER1)", "driver": "uhd", "serial": "TESTSER1", "needs": "pro"}]
    assert usb_sdr.recognise([{"vid": 0x3923, "pid": 0x7814, "serial": "", "product": ""}])[0]["id"] == "locked:usrp:3923-7814"


def test_a_locked_device_shows_in_the_list_but_cannot_receive(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(usb_sdr, "usb_devices", lambda: usb_sdr.parse_ioreg(IOREG))
    monkeypatch.setattr(usb_sdr, "_cache", None)
    monkeypatch.setattr(devices, "BACKENDS", {usb_sdr.PREFIX: usb_sdr})
    listed = [d for d in devices.list_devices() if d["id"].startswith("locked:")]
    assert len(listed) == 1 and listed[0]["needs"] == "pro" and listed[0]["serial"] == "TESTSER1"
    with pytest.raises(devices.DeviceError, match="Pro"):
        devices.capture(listed[0]["id"], devices.CaptureRequest(2.4e9, 1e6, 0.01), tmp_path / "x.sigmf-meta")


def test_devices_that_can_be_used_carry_no_lock() -> None:
    assert all("needs" not in d for d in devices.list_devices() if not d["id"].startswith("locked:"))
