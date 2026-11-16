from nrtrail import doctor


def test_quick_report_has_core_checks():
    report = doctor.run_checks(quick=True)
    ids = {c["id"] for c in report["checks"]}
    assert {"os", "python", "python_packages", "matlab", "node", "adb", "disk"} <= ids
    assert report["engines"]["mock"] is True
    assert all(c["status"] in {"ok", "warn", "missing"} for c in report["checks"])
    assert "nrtrail 환경 점검" in doctor.format_text(report)
