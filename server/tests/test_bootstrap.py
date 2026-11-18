"""처음 실행 설치 도우미: 무엇을 할지(프로젝트 폴더 안에서만)와 점검 문구."""
import subprocess
import sys

from nrtrail import doctor
from nrtrail.paths import ROOT


def test_bootstrap_plans_only_project_local_steps():
    out = subprocess.run([sys.executable, str(ROOT / "tools" / "bootstrap.py"), "--dry-run"], capture_output=True, text=True, check=True).stdout
    assert "pip" in out and ".[app]" in out
    assert "sudo" not in out and "brew" not in out                      # 시스템에 까는 것은 없다
    for line in out.splitlines():
        assert str(ROOT) in line                                         # 모든 단계가 프로젝트 폴더 안에서 돈다


def test_soapysdr_is_optional_when_usrp_goes_through_matlab(monkeypatch):
    monkeypatch.setattr(doctor.importlib.util, "find_spec", lambda name: None if name == "SoapySDR" else object())
    monkeypatch.setattr(doctor, "usrp_via_matlab", lambda: True)
    checks = {c.id: c for c in doctor.check_soapy()}
    assert checks["soapysdr"].status == "ok" and "없어도" in checks["soapysdr"].detail and checks["usrp_matlab"].status == "ok"
    monkeypatch.setattr(doctor, "usrp_via_matlab", lambda: False)
    only = doctor.check_soapy()[0]
    assert only.status == "warn" and "pip 로는 설치할 수 없" in only.fix    # 없다고 "오류"는 아니다. pip 로 못 깐다는 것을 알려 준다
