"""Background thread that runs scheduled link refreshes.

Prism serves with one worker per process, so a thread is enough. Each round
claims due links with a lease in the database (``server.services.links.run_due``),
so several processes sharing a database never refresh the same link twice.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from server.services.links import run_due

log = logging.getLogger("prism.scheduler")


class Scheduler:
    def __init__(self, svc: Any, interval_s: float = 30.0) -> None:
        self.svc = svc
        self.interval_s = interval_s
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="prism-scheduler", daemon=True)
        self._thread.start()
        log.info("Scheduled refresh is on (checks every %.0f s)", self.interval_s)

    def stop(self, timeout: float = 10.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout)

    def _run(self) -> None:
        while not self._stop.wait(self.interval_s):
            try:
                # Work through a backlog in batches, but stop promptly on shutdown.
                for _ in range(20):
                    if not run_due(self.svc) or self._stop.is_set():
                        break
            except Exception:
                log.exception("Scheduled refresh round failed")
