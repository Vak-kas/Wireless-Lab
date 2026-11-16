# SPDX-License-Identifier: GPL-3.0-or-later
from collections import deque

import pytest

from wls.core.state_machine import (
    Command,
    Pending,
    Signal,
    Snapshot,
    State,
    StopReason,
    Verdict,
    apply_signal,
    decide,
)


def run(snapshot: Snapshot, *steps: Command | Signal) -> Snapshot:
    """Apply steps that are all expected to take effect."""
    for step in steps:
        if isinstance(step, Command):
            decision = decide(snapshot, step)
            assert decision.verdict is Verdict.ACCEPTED, (step, decision)
            snapshot = decision.snapshot
        else:
            snapshot, applied = apply_signal(snapshot, step)
            assert applied, (step, snapshot)
    return snapshot


def measuring() -> Snapshot:
    return run(
        Snapshot(),
        Command.PREPARE,
        Signal.PREPARED,
        Command.START_MEASUREMENT,
        Signal.MEASUREMENT_STARTED,
    )


def running_test() -> Snapshot:
    return run(measuring(), Command.START_TEST, Signal.TEST_STARTED)


# --- the reference experiment -------------------------------------------------


def test_full_experiment_baseline_test_recovery():
    s = measuring()
    assert s.state is State.MEASURING  # baseline

    s = run(s, Command.MARK, Command.START_TEST, Signal.TEST_STARTED)
    assert s.state is State.TEST_RUNNING

    s = run(s, Command.STOP_TEST, Signal.TEST_ENDED)
    assert s.state is State.RECOVERING  # measurement kept running

    s = run(s, Signal.RECOVERY_DONE)
    assert s.state is State.MEASURING

    s = run(s, Command.STOP_MEASUREMENT, Signal.STOPPED)
    assert s == Snapshot(State.COMPLETED)


def test_second_test_can_start_during_recovery():
    s = run(running_test(), Command.STOP_TEST, Signal.TEST_ENDED)
    s = run(s, Command.START_TEST, Signal.TEST_STARTED)
    assert s.state is State.TEST_RUNNING


# --- request versus confirmation ----------------------------------------------


def test_start_measurement_is_not_measuring_until_confirmed():
    s = run(Snapshot(), Command.PREPARE, Signal.PREPARED, Command.START_MEASUREMENT)
    assert s == Snapshot(State.READY, Pending.STARTING_MEASUREMENT)


def test_start_test_is_not_running_until_confirmed():
    s = run(measuring(), Command.START_TEST)
    assert s == Snapshot(State.MEASURING, Pending.STARTING_TEST)


def test_stop_test_is_not_recovering_until_confirmed():
    s = run(running_test(), Command.STOP_TEST)
    assert s == Snapshot(State.TEST_RUNNING, Pending.STOPPING_TEST)


def test_stop_is_not_completed_until_confirmed():
    s = run(measuring(), Command.STOP)
    assert s == Snapshot(State.STOPPING, Pending.NONE, StopReason.USER_STOP)


# --- duplicate requests ---------------------------------------------------------


@pytest.mark.parametrize(
    ("snapshot", "command"),
    [
        (Snapshot(State.PREPARING), Command.PREPARE),
        (Snapshot(State.READY, Pending.STARTING_MEASUREMENT), Command.START_MEASUREMENT),
        (Snapshot(State.MEASURING), Command.START_MEASUREMENT),
        (Snapshot(State.MEASURING, Pending.STARTING_TEST), Command.START_TEST),
        (Snapshot(State.TEST_RUNNING), Command.START_TEST),
        (Snapshot(State.TEST_RUNNING, Pending.STOPPING_TEST), Command.STOP_TEST),
        (Snapshot(State.MEASURING), Command.STOP_TEST),
        (Snapshot(State.STOPPING, stop_reason=StopReason.USER_STOP), Command.STOP),
        (Snapshot(State.STOPPING, stop_reason=StopReason.USER_STOP), Command.ABORT),
        (Snapshot(State.STOPPING, stop_reason=StopReason.USER_STOP), Command.STOP_MEASUREMENT),
        (Snapshot(State.COMPLETED), Command.STOP),
        (Snapshot(State.IDLE), Command.RESET),
    ],
)
def test_duplicate_requests_are_noops(snapshot, command):
    decision = decide(snapshot, command)
    assert decision.verdict is Verdict.NOOP
    assert decision.snapshot == snapshot
    assert decision.reason


# --- independence of measurement and test ---------------------------------------


@pytest.mark.parametrize(
    "snapshot",
    [
        Snapshot(State.TEST_RUNNING),
        Snapshot(State.TEST_RUNNING, Pending.STOPPING_TEST),
        Snapshot(State.MEASURING, Pending.STARTING_TEST),
        Snapshot(State.RECOVERING, Pending.STOPPING_TEST),
    ],
)
def test_stop_measurement_is_rejected_while_a_test_is_in_flight(snapshot):
    decision = decide(snapshot, Command.STOP_MEASUREMENT)
    assert decision.verdict is Verdict.REJECTED
    assert decision.snapshot == snapshot


def test_stop_brings_everything_down_even_during_a_test():
    s = run(running_test(), Command.STOP, Signal.STOPPED)
    assert s == Snapshot(State.COMPLETED)


def test_test_cannot_start_without_measurement():
    for state in (State.IDLE, State.PREPARING, State.READY, State.COMPLETED):
        assert decide(Snapshot(state), Command.START_TEST).verdict is Verdict.REJECTED


def test_cancelling_a_test_before_it_confirmed_still_enters_recovery():
    s = run(measuring(), Command.START_TEST, Command.STOP_TEST)
    assert s == Snapshot(State.MEASURING, Pending.STOPPING_TEST)
    s = run(s, Signal.TEST_ENDED)
    assert s == Snapshot(State.RECOVERING)


def test_failed_test_with_successful_revert_keeps_measuring():
    s = run(running_test(), Signal.TEST_FAILED)
    assert s == Snapshot(State.RECOVERING)


# --- errors ---------------------------------------------------------------------


def test_revert_failure_ends_in_failed():
    s = run(running_test(), Signal.REVERT_FAILED)
    assert s == Snapshot(State.STOPPING, Pending.NONE, StopReason.ERROR)
    assert run(s, Signal.STOPPED) == Snapshot(State.FAILED)


def test_fatal_error_while_measuring_ends_in_failed():
    assert run(measuring(), Signal.FATAL_ERROR, Signal.STOPPED) == Snapshot(State.FAILED)


def test_fatal_error_during_a_user_stop_turns_the_outcome_into_failed():
    s = run(measuring(), Command.STOP, Signal.FATAL_ERROR, Signal.STOPPED)
    assert s == Snapshot(State.FAILED)


def test_measurement_start_timeout_cleans_up_then_fails():
    s = run(
        Snapshot(),
        Command.PREPARE,
        Signal.PREPARED,
        Command.START_MEASUREMENT,
        Signal.MEASUREMENT_START_FAILED,
        Signal.STOPPED,
    )
    assert s == Snapshot(State.FAILED)


def test_prepare_failure_and_stop_failure_end_in_failed():
    assert run(Snapshot(), Command.PREPARE, Signal.PREPARE_FAILED) == Snapshot(State.FAILED)
    assert run(measuring(), Command.STOP, Signal.STOP_FAILED) == Snapshot(State.FAILED)


def test_abort_closes_cleanly():
    assert run(measuring(), Command.ABORT, Signal.STOPPED) == Snapshot(State.COMPLETED)


# --- late signals ----------------------------------------------------------------


def test_start_confirmation_after_stop_is_ignored():
    s = run(Snapshot(), Command.PREPARE, Signal.PREPARED, Command.START_MEASUREMENT, Command.STOP)
    after, applied = apply_signal(s, Signal.MEASUREMENT_STARTED)
    assert not applied
    assert after == s


def test_test_started_after_stop_test_request_is_ignored():
    s = run(measuring(), Command.START_TEST, Command.STOP_TEST)
    after, applied = apply_signal(s, Signal.TEST_STARTED)
    assert not applied
    assert after == s


def test_recovery_done_is_ignored_while_next_test_is_starting():
    s = run(running_test(), Command.STOP_TEST, Signal.TEST_ENDED, Command.START_TEST)
    after, applied = apply_signal(s, Signal.RECOVERY_DONE)
    assert not applied
    assert after == s


# --- repeat and reset ------------------------------------------------------------


@pytest.mark.parametrize("terminal", [State.COMPLETED, State.FAILED])
def test_finished_run_can_be_reset_or_repeated(terminal):
    assert run(Snapshot(terminal), Command.RESET) == Snapshot(State.IDLE)
    assert run(Snapshot(terminal), Command.REPEAT) == Snapshot(State.PREPARING)


def test_reset_is_rejected_while_running():
    assert decide(measuring(), Command.RESET).verdict is Verdict.REJECTED


# --- illegal snapshots cannot be built --------------------------------------------


def test_invalid_snapshots_are_rejected_at_construction():
    with pytest.raises(ValueError):
        Snapshot(State.IDLE, Pending.STARTING_TEST)
    with pytest.raises(ValueError):
        Snapshot(State.TEST_RUNNING, Pending.STARTING_TEST)
    with pytest.raises(ValueError):
        Snapshot(State.STOPPING)
    with pytest.raises(ValueError):
        Snapshot(State.MEASURING, stop_reason=StopReason.ERROR)


# --- whole-graph properties -------------------------------------------------------


def _successors(s: Snapshot) -> set[Snapshot]:
    out = {decide(s, c).snapshot for c in Command}
    out |= {apply_signal(s, sig)[0] for sig in Signal}
    return out


def _reachable(start: Snapshot) -> set[Snapshot]:
    seen = {start}
    queue = deque([start])
    while queue:
        for nxt in _successors(queue.popleft()):
            if nxt not in seen:
                seen.add(nxt)
                queue.append(nxt)
    return seen


def test_every_state_is_reachable_and_no_step_ever_raises():
    reachable = _reachable(Snapshot())
    assert {s.state for s in reachable} == set(State)


def test_noop_and_rejected_never_change_the_snapshot():
    for s in _reachable(Snapshot()):
        for command in Command:
            decision = decide(s, command)
            if decision.verdict is not Verdict.ACCEPTED:
                assert decision.snapshot == s
                assert decision.reason


def test_no_dead_ends_every_snapshot_can_get_back_to_idle():
    for s in _reachable(Snapshot()):
        assert Snapshot(State.IDLE) in _reachable(s), s


def test_stop_always_leads_out_of_any_active_snapshot():
    for s in _reachable(Snapshot()):
        if s.state in (State.IDLE, State.COMPLETED, State.FAILED, State.STOPPING):
            continue
        assert decide(s, Command.STOP).snapshot.state is State.STOPPING, s
