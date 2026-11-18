"""The scheduler thread calls run_due until stopped and survives a failing round."""

from __future__ import annotations

import threading
from typing import Any

import pytest

from server import scheduler as scheduler_module
from server.scheduler import Scheduler


def test_runs_rounds_and_stops(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []
    second = threading.Event()

    def fake_run_due(svc: Any) -> int:
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("a bad round")  # logged, and the thread keeps going
        second.set()
        return 0

    monkeypatch.setattr(scheduler_module, "run_due", fake_run_due)
    sched = Scheduler(svc=object(), interval_s=0.01)
    sched.start()
    assert second.wait(5)
    sched.stop()
    assert sched._thread is not None and not sched._thread.is_alive()


def test_no_new_round_starts_after_stop(monkeypatch: pytest.MonkeyPatch) -> None:
    entered, release = threading.Event(), threading.Event()
    calls: list[int] = []

    def busy_run_due(svc: Any) -> int:
        calls.append(1)
        entered.set()
        release.wait(5)
        return 1  # "more work is due", which would normally start another batch

    monkeypatch.setattr(scheduler_module, "run_due", busy_run_due)
    sched = Scheduler(svc=object(), interval_s=0.01)
    sched.start()
    assert entered.wait(5)
    sched.stop(timeout=0.05)  # stop while a round is still running
    release.set()
    assert sched._thread is not None
    sched._thread.join(5)
    assert not sched._thread.is_alive()
    assert len(calls) == 1


def test_stop_before_start_is_harmless() -> None:
    Scheduler(svc=object()).stop()
