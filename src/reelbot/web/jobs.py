"""Background jobs for the dashboard.

Generating a reel takes tens of seconds and publishing talks to Instagram, so
neither can run inside a request. Jobs run on a worker thread and the UI polls
for status.

Deliberately single-slot: two concurrent generations would fight over the same
timestamped filenames, and two concurrent publishes would double-post.
"""
from __future__ import annotations

import logging
import threading
import traceback
from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Callable

log = logging.getLogger(__name__)

PENDING = "pending"
RUNNING = "running"
DONE = "done"
FAILED = "failed"


@dataclass
class Job:
    id: str
    kind: str
    status: str = PENDING
    started_at: str = ""
    finished_at: str = ""
    message: str = ""
    detail: str = ""
    result: dict = field(default_factory=dict)


class JobRunner:
    """Runs one job at a time and keeps a short history."""

    def __init__(self, history: int = 20) -> None:
        self._lock = threading.Lock()
        self._current: Job | None = None
        self._history: deque[Job] = deque(maxlen=history)
        self._counter = 0

    @property
    def busy(self) -> bool:
        with self._lock:
            return self._current is not None

    def submit(self, kind: str, work: Callable[[], dict], label: str = "") -> Job:
        """Start ``work`` on a worker thread.

        Raises:
            RuntimeError: if a job is already running.
        """
        with self._lock:
            if self._current is not None:
                raise RuntimeError(f"{self._current.kind} is already running")
            self._counter += 1
            job = Job(
                id=f"{kind}-{self._counter}",
                kind=kind,
                status=RUNNING,
                started_at=_now(),
                message=label or f"{kind} started",
            )
            self._current = job

        threading.Thread(target=self._run, args=(job, work), daemon=True).start()
        return job

    def _run(self, job: Job, work: Callable[[], dict]) -> None:
        try:
            job.result = work() or {}
            job.status = DONE
            job.message = job.result.get("message", f"{job.kind} finished")
        except Exception as exc:  # noqa: BLE001 - surfaced to the UI, not swallowed
            job.status = FAILED
            job.message = str(exc)
            job.detail = traceback.format_exc(limit=4)
            log.exception("Job %s failed", job.id)
        finally:
            job.finished_at = _now()
            with self._lock:
                self._history.appendleft(job)
                self._current = None

    def snapshot(self) -> dict:
        with self._lock:
            current = asdict(self._current) if self._current else None
            recent = [asdict(job) for job in self._history]
        return {"current": current, "recent": recent}


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


#: One runner per process.
runner = JobRunner()
