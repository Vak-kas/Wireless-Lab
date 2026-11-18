"""채널 모니터: 표시값 다듬기, 자동 기준값, 증가량."""
import pytest
from nrtrail import monitor, survey


class Rig:
    """시계와 측정값을 손으로 움직이는 시험대."""

    def __init__(self, **kw):
        self.now = 0.0
        self.values = {"a": -70.0, "b": -60.0}
        self.calls = []
        self.m = monitor.Monitor("dev", "wifi-5g", ["a", "b"], clock=lambda: self.now, sweep=self.fake, **kw)

    def fake(self, device, plan, **kw):
        self.calls.append((device, plan, kw))
        return {"channels": [{"name": n, "center_hz": 5e9, "width_hz": 20e6, "measured": v is not None,
                              **({"mean_dbfs": v + 1, "median_dbfs": v, "peak_dbfs": -20.0, "clipped": False} if v is not None else {})}
                             for n, v in self.values.items()]}

    def step(self, dt=2.0, **values):
        self.now += dt
        self.values |= values
        return {r["name"]: r for r in self.m.sweep()["channels"]}


def test_shown_level_is_the_median_of_the_last_five_sweeps():
    rig = Rig(auto=False)
    for v in (-70, -70, -40, -70, -70):          # 한 바퀴 튄 값은 표시값을 움직이지 못한다
        rows = rig.step(a=v)
    assert rows["a"]["median_dbfs"] == -70 and rows["a"]["samples"] == 5
    for _ in range(3):                             # 세 바퀴 이어지면 표시값이 따라간다
        rows = rig.step(a=-40)
    assert rows["a"]["median_dbfs"] == -40
    assert rig.calls[0][2]["only"] == ["a", "b"]


def test_baseline_is_saved_automatically_once_the_channel_is_steady():
    rig = Rig()
    for _ in range(4):
        rows = rig.step()
    assert "rise_db" not in rows["a"] and rows["a"]["settle_s"] > 0     # 8초가 안 됐다(첫 측정 뒤 6초)
    rows = rig.step()
    assert rows["a"]["rise_db"] == 0 and rig.m.baseline_note == "auto" and not rig.m.forced
    for _ in range(5):
        rows = rig.step(a=-58.0)
    assert rows["a"]["rise_db"] == 12 and rows["a"]["raised"] and rows["b"]["rise_db"] == 0 and not rows["b"]["raised"]
    assert rig.m.state()["raised"] == ["a"]


def test_a_shaky_channel_waits_then_is_saved_anyway_and_marked():
    rig = Rig()
    flip = [-70.0, -60.0]
    for i in range(6):                             # 12초: 흔들려서 아직 저장하지 않는다 (b 는 가만히 있어 저장됨)
        rows = rig.step(a=flip[i % 2])
    assert "rise_db" not in rows["a"] and "rise_db" in rows["b"]
    for i in range(3):                             # 15초를 넘기면 그대로 저장
        rows = rig.step(a=flip[i % 2])
    assert "rise_db" in rows["a"] and rows["a"]["forced"] and rig.m.state()["forced"] == ["a"]


def test_manual_baseline_and_clearing():
    rig = Rig(auto=False)
    rows = rig.step()
    assert "rise_db" not in rows["a"] and "settle_s" not in rows["a"]
    rig.m.save_baseline()
    assert rig.m.baseline_note == "manual" and rig.step(a=-65.0)["a"]["rise_db"] == 2.5   # 두 바퀴(−70, −65)의 중앙값 −67.5
    rig.m.clear_baseline()
    assert not rig.m.state()["has_baseline"]
    rig.m.configure(auto=True)
    for _ in range(5):
        rows = rig.step()
    assert rig.m.baseline_note == "auto" and rows["a"]["baseline_dbfs"] == -65


def test_unmeasured_channels_are_kept_but_have_no_level():
    rig = Rig()
    rows = rig.step(b=None)
    assert not rows["b"]["measured"] and "median_dbfs" not in rows["b"]


def test_registry_and_bad_input():
    with pytest.raises(survey.SurveyError):
        monitor.Monitor("d", "wifi-5g", stat="nope")
    reg = monitor.Registry()
    ids = [reg.add(monitor.Monitor("d", "wifi-5g")).id for _ in range(monitor.MAX_MONITORS + 1)]
    with pytest.raises(survey.SurveyError):
        reg.get(ids[0])
    assert reg.get(ids[-1]).id == ids[-1]
    reg.remove(ids[-1])
    with pytest.raises(survey.SurveyError):
        reg.get(ids[-1])
