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
