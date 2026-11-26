"""+ 로 추가한 "볼 곳"을 서버 파일에 두는 것(places)."""
from nrtrail import places


def test_places_are_kept_in_a_file_and_bad_entries_are_dropped(tmp_path, monkeypatch):
    monkeypatch.setenv("NRTRAIL_SESSIONS", str(tmp_path))
    assert places.load() == []
    kept = places.save([{"id": "1", "name": " KEYLESS ", "center_mhz": 433.92, "width_mhz": 2},
                        {"name": "", "center_mhz": 100, "width_mhz": 1}, {"name": "x", "center_mhz": -1, "width_mhz": 1}, {"name": "y"}])
    assert kept == [{"id": "1", "name": "KEYLESS", "center_mhz": 433.92, "width_mhz": 2.0}]
    assert places.load() == kept                                   # 다시 켜도(다시 읽어도) 그대로다
    (tmp_path / "view-bands.json").write_text("{깨진 파일")
    assert places.load() == []
