# SPDX-License-Identifier: GPL-3.0-or-later
import asyncio
from dataclasses import replace
from itertools import groupby
from types import SimpleNamespace

from wls.core.controller import Controller, ExperimentConfig, Timeouts
from wls.core.devices import Capability, DeviceManager
from wls.core.interfaces import MemoryRecorder
from wls.core.state_machine import Command, Pending, State, Verdict
from wls.providers.sim import SimProbe, SimProvider, SimTestAction, sim_host, sim_wifi_nic

FAST = Timeouts(
    prepare=0.3, start_measurement=0.3, start_test=0.3, stop_test=0.3, revert=0.3, stop=1.0
)


def make(*, probe=None, test=None, with_test=True, devices=None, **config):
    provider = SimProvider(devices or [sim_host()])
    probe_obj = SimProbe(provider, **(probe or {}))
    test_obj = SimTestAction(provider, **(test or {})) if with_test else None
    recorder = MemoryRecorder()
    controller = Controller(DeviceManager([provider]), recorder)
    settings = {"recovery_window": 0.05, "stall_timeout": 0.2, "timeouts": FAST} | config
    cfg = ExperimentConfig((probe_obj,), test_obj, **settings)
    return SimpleNamespace(
        provider=provider, probe=probe_obj, test=test_obj, rec=recorder, ctl=controller, cfg=cfg
    )


async def to_measuring(env):
    assert env.ctl.submit(Command.PREPARE, config=env.cfg).verdict is Verdict.ACCEPTED
    await env.ctl.wait_state(State.READY)
    assert env.ctl.submit(Command.START_MEASUREMENT).verdict is Verdict.ACCEPTED
    await env.ctl.wait_state(State.MEASURING)


async def to_test_running(env):
    await to_measuring(env)
    assert env.ctl.submit(Command.START_TEST).verdict is Verdict.ACCEPTED
    await env.ctl.wait_state(State.TEST_RUNNING)


async def finished(env, expected: State):
    snapshot = await env.ctl.wait_state(State.COMPLETED, State.FAILED)
    assert snapshot.state is expected, env.rec.events
    await asyncio.sleep(0)  # let done-callbacks run
    assert not env.ctl.busy


def states(env) -> list[str]:
    seq = [e.data["state"] for e in env.rec.of_kind("state")]
    return [key for key, _ in groupby(seq)]


def signals(env) -> list[str]:
    return [e.data["signal"] for e in env.rec.of_kind("signal") if e.data["applied"]]


def rtt_phases(env) -> list[float]:
    return [key for key, _ in groupby(s.values["rtt_ms"] for s in env.rec.samples)]


# --- the reference experiment ---------------------------------------------------


async def test_full_experiment_records_baseline_test_and_recovery():
    env = make()
    await to_measuring(env)
    await asyncio.sleep(0.03)  # baseline

    env.ctl.submit(Command.START_TEST)
    await env.ctl.wait_state(State.TEST_RUNNING)
    await asyncio.sleep(0.03)

    env.ctl.submit(Command.STOP_TEST)
    await env.ctl.wait_state(State.RECOVERING)
    await env.ctl.wait_state(State.MEASURING)  # recovery window elapsed

    env.ctl.submit(Command.STOP_MEASUREMENT)
    await finished(env, State.COMPLETED)

    assert states(env) == [
        "preparing",
        "ready",
        "measuring",
        "test_running",
        "recovering",
        "measuring",
        "stopping",
        "completed",
    ]
    # One uninterrupted measurement shows normal, impaired, normal again.
    assert rtt_phases(env) == [20.0, 200.0, 20.0]
    assert env.probe.runs == 1
    assert (env.test.start_calls, env.test.stop_calls, env.test.revert_calls) == (1, 1, 1)


async def test_request_is_logged_before_its_confirmation():
    env = make()
    await to_measuring(env)
    env.ctl.submit(Command.STOP)
    await finished(env, State.COMPLETED)

    def index(kind, **match):
        return next(
            i
            for i, e in enumerate(env.rec.events)
            if e.kind == kind and all(e.data.get(k) == v for k, v in match.items())
        )

    requested = index("command", command="start_measurement")
    confirmed = index("state", state="measuring")
    assert requested < confirmed
    stamps = [e.t_ns for e in env.rec.events]
    assert stamps == sorted(stamps)


async def test_start_is_pending_until_the_first_sample_arrives():
    env = make()
    env.ctl.submit(Command.PREPARE, config=env.cfg)
    await env.ctl.wait_state(State.READY)
    env.ctl.submit(Command.START_MEASUREMENT)
    assert env.ctl.snapshot.state is State.READY
    assert env.ctl.snapshot.pending is Pending.STARTING_MEASUREMENT
    assert not env.rec.samples
    await env.ctl.wait_state(State.MEASURING)
    assert env.rec.samples
    env.ctl.submit(Command.STOP)
    await finished(env, State.COMPLETED)


# --- duplicate and invalid requests -----------------------------------------------


async def test_duplicate_start_does_not_start_a_second_measurement():
    env = make()
    await to_measuring(env)
    assert env.ctl.submit(Command.START_MEASUREMENT).verdict is Verdict.NOOP
    await asyncio.sleep(0.02)
    assert env.probe.runs == 1
    env.ctl.submit(Command.STOP)
    assert env.ctl.submit(Command.STOP).verdict is Verdict.NOOP
    await finished(env, State.COMPLETED)


async def test_start_test_is_rejected_when_no_test_is_configured():
    env = make(with_test=False)
    await to_measuring(env)
    decision = env.ctl.submit(Command.START_TEST)
    assert decision.verdict is Verdict.REJECTED
    assert "no test" in decision.reason
    env.ctl.submit(Command.STOP)
    await finished(env, State.COMPLETED)


async def test_stop_measurement_is_rejected_during_a_test():
    env = make()
    await to_test_running(env)
    assert env.ctl.submit(Command.STOP_MEASUREMENT).verdict is Verdict.REJECTED
    assert env.ctl.state is State.TEST_RUNNING
    env.ctl.submit(Command.STOP)
    await finished(env, State.COMPLETED)


async def test_marks_are_recorded_only_while_measuring():
    env = make()
    assert env.ctl.submit(Command.MARK, label="too early").verdict is Verdict.REJECTED
    await to_measuring(env)
    assert env.ctl.submit(Command.MARK, label="door opened").verdict is Verdict.ACCEPTED
    assert [e.data["label"] for e in env.rec.of_kind("mark")] == ["door opened"]
    env.ctl.submit(Command.STOP)
    await finished(env, State.COMPLETED)


# --- preparation checks -------------------------------------------------------------


async def test_prepare_fails_when_the_device_is_not_connected():
    env = make(probe={"device_id": "usb-nic-that-is-gone"})
    env.ctl.submit(Command.PREPARE, config=env.cfg)
    await finished(env, State.FAILED)
    problems = env.rec.of_kind("signal")[-1].data["problems"]
    assert "not connected" in problems[0]


async def test_prepare_fails_with_the_reason_when_a_capability_is_missing():
    env = make(
        devices=[sim_wifi_nic(inject=False)],
        probe={"device_id": "sim-wlan0", "requires": frozenset({Capability.WIFI_INJECT})},
        with_test=False,
    )
    env.ctl.submit(Command.PREPARE, config=env.cfg)
    await finished(env, State.FAILED)
    problems = env.rec.of_kind("signal")[-1].data["problems"]
    assert "frame injection" in problems[0]


async def test_prepare_times_out_when_discovery_hangs():
    env = make()
    env.provider.discover_delay = 5.0
    env.ctl.submit(Command.PREPARE, config=env.cfg)
    await finished(env, State.FAILED)


async def test_abort_during_prepare_closes_cleanly():
    env = make()
    env.provider.discover_delay = 0.2
    env.ctl.submit(Command.PREPARE, config=env.cfg)
    assert env.ctl.submit(Command.ABORT).verdict is Verdict.ACCEPTED
    await finished(env, State.COMPLETED)
    assert "ready" not in states(env)


# --- measurement failures -------------------------------------------------------------


async def test_measurement_that_never_produces_a_sample_fails_to_start():
    env = make(probe={"never_start": True})
    env.ctl.submit(Command.PREPARE, config=env.cfg)
    await env.ctl.wait_state(State.READY)
    env.ctl.submit(Command.START_MEASUREMENT)
    await finished(env, State.FAILED)
    assert "measuring" not in states(env)
    failed = [e for e in env.rec.of_kind("signal") if "waiting_for" in e.data]
    assert failed[0].data["waiting_for"] == ["sim-link"]


async def test_probe_crash_is_detected_and_fails_the_run():
    env = make(probe={"crash_after": 3})
    await to_measuring(env)
    await finished(env, State.FAILED)
    assert "simulated probe crash" in env.rec.of_kind("probe_error")[0].data["error"]
    assert len(env.rec.samples) == 3  # data collected before the crash is kept


async def test_probe_that_silently_stops_producing_is_detected():
    env = make(probe={"stall_after": 3}, stall_timeout=0.05)
    await to_measuring(env)
    await finished(env, State.FAILED)
    assert env.rec.of_kind("probe_stalled")


async def test_device_unplugged_while_measuring_fails_the_run():
    env = make()
    await to_measuring(env)
    env.provider.unplug("sim-host")
    await finished(env, State.FAILED)
    assert "disconnected" in env.rec.of_kind("probe_error")[0].data["error"]


async def test_probe_that_will_not_stop_ends_in_failed_after_the_stop_timeout():
    env = make(probe={"ignore_cancel": True}, timeouts=replace(FAST, stop=0.1))
    await to_measuring(env)
    env.ctl.submit(Command.STOP)
    snapshot = await env.ctl.wait_state(State.COMPLETED, State.FAILED)
    assert snapshot.state is State.FAILED
    assert env.rec.of_kind("stop_timeout")


# --- test failures: the device is always reverted ---------------------------------------


async def test_failed_test_start_is_reverted_and_measurement_continues():
    env = make(test={"fail_start": True})
    await to_measuring(env)
    env.ctl.submit(Command.START_TEST)
    await env.ctl.wait_state(State.RECOVERING)
    assert env.test.revert_calls == 1
    assert env.provider.impaired is False

    await env.ctl.wait_state(State.MEASURING)
    before = len(env.rec.samples)
    await asyncio.sleep(0.03)
    assert len(env.rec.samples) > before
    assert "test_running" not in states(env)
    env.ctl.submit(Command.STOP)
    await finished(env, State.COMPLETED)


async def test_test_start_that_hangs_times_out_and_is_reverted():
    env = make(test={"hang_start": True}, timeouts=replace(FAST, start_test=0.05))
    await to_measuring(env)
    env.ctl.submit(Command.START_TEST)
    await env.ctl.wait_state(State.RECOVERING)
    assert env.test.revert_calls == 1
    env.ctl.submit(Command.STOP)
    await finished(env, State.COMPLETED)


async def test_cancelling_a_test_before_it_confirmed_reverts_it():
    env = make(test={"hang_start": True})
    await to_measuring(env)
    env.ctl.submit(Command.START_TEST)
    await asyncio.sleep(0.01)
    assert env.ctl.submit(Command.STOP_TEST).verdict is Verdict.ACCEPTED
    await env.ctl.wait_state(State.RECOVERING)
    assert env.test.revert_calls == 1
    assert "test_started" not in signals(env)
    env.ctl.submit(Command.STOP)
    await finished(env, State.COMPLETED)


async def test_failing_test_stop_still_reverts():
    env = make(test={"fail_stop": True})
    await to_test_running(env)
    env.ctl.submit(Command.STOP_TEST)
    await env.ctl.wait_state(State.RECOVERING)
    assert env.provider.impaired is False
    env.ctl.submit(Command.STOP)
    await finished(env, State.COMPLETED)


async def test_revert_failure_fails_the_run():
    env = make(test={"fail_revert": True})
    await to_test_running(env)
    env.ctl.submit(Command.STOP_TEST)
    await finished(env, State.FAILED)
    assert "revert_failed" in signals(env)


async def test_revert_that_hangs_is_cut_off_and_fails_the_run():
    env = make(test={"hang_revert": True}, timeouts=replace(FAST, revert=0.05))
    await to_test_running(env)
    env.ctl.submit(Command.STOP_TEST)
    await finished(env, State.FAILED)


async def test_stop_during_a_test_reverts_before_ending():
    env = make()
    await to_test_running(env)
    env.ctl.submit(Command.STOP)
    await finished(env, State.COMPLETED)
    assert (env.test.stop_calls, env.test.revert_calls) == (1, 1)
    assert env.provider.impaired is False


async def test_abort_during_a_test_skips_the_graceful_stop_but_still_reverts():
    env = make()
    await to_test_running(env)
    env.ctl.submit(Command.ABORT)
    await finished(env, State.COMPLETED)
    assert (env.test.stop_calls, env.test.revert_calls) == (0, 1)
    assert env.provider.impaired is False


async def test_device_unplugged_during_a_test_reverts_and_fails():
    env = make()
    await to_test_running(env)
    env.provider.unplug("sim-host")
    await finished(env, State.FAILED)
    assert env.test.revert_calls == 1
    assert env.provider.impaired is False


# --- repeat ---------------------------------------------------------------------------


async def test_finished_run_can_be_repeated_with_the_same_config():
    env = make()
    await to_measuring(env)
    env.ctl.submit(Command.STOP)
    await finished(env, State.COMPLETED)

    assert env.ctl.submit(Command.REPEAT).verdict is Verdict.ACCEPTED
    await env.ctl.wait_state(State.READY)
    env.ctl.submit(Command.START_MEASUREMENT)
    await env.ctl.wait_state(State.MEASURING)
    env.ctl.submit(Command.STOP)
    await finished(env, State.COMPLETED)
    assert env.probe.runs == 2


async def test_failed_run_can_be_reset_and_prepared_again():
    env = make(probe={"crash_after": 1})
    await to_measuring(env)
    await finished(env, State.FAILED)
    assert env.ctl.submit(Command.RESET).verdict is Verdict.ACCEPTED
    assert env.ctl.state is State.IDLE

    env.probe.crash_after = None
    await to_measuring(env)
    env.ctl.submit(Command.STOP)
    await finished(env, State.COMPLETED)
