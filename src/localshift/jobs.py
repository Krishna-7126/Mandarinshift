"""
localshift.jobs — Backend job management and batch conversion API.

Responsibilities
----------------
- Define ``ConversionJob``, ``JobStatus``, ``JobResult``, and ``ProgressEvent``.
- Provide a ``JobQueue`` that accepts single and batch submissions.
- Execute conversion jobs on a bounded thread-pool.
- Track job lifecycle with thread-safe state transitions.
- Report coarse progress events via callbacks.
- Support honest cancellation (PENDING jobs only; RUNNING jobs complete).
- Enforce queue capacity to bound memory usage.
- Remain completely independent of PySide6 and any GUI layer.

Public API
----------
- ``JobStatus``        — Lifecycle states.
- ``ProgressEvent``    — Coarse lifecycle event delivered to callbacks.
- ``JobResult``        — Structured result for a single completed job.
- ``ConversionJob``    — Submitted job descriptor (immutable after creation).
- ``JobQueue``         — Thread-safe job queue and execution engine.
- ``BatchSubmission``  — Return type for batch submissions.

Concurrency Model
-----------------
A ``ThreadPoolExecutor`` with a configurable worker count (default: 2) processes
jobs.  All mutable state (status, result) lives in a single ``threading.Lock``-
protected dictionary keyed by job ID.  Workers never access the state dict
without holding the lock for write operations.

Cancellation Semantics
----------------------
- A **PENDING** job can be cancelled before a worker picks it up.  The job will
  be marked CANCELLED and will never execute.
- A **RUNNING** job cannot be interrupted: Pillow's decode/encode operations
  are synchronous C extensions with no cooperative cancellation point.
  Calling ``cancel()`` on a running job returns ``False`` and leaves the job to
  complete normally (SUCCEEDED or FAILED).
- A job is **never** marked CANCELLED after it has already completed.

Queue Capacity
--------------
``max_pending`` (default: 200) caps the number of PENDING jobs in the internal
queue.  Submission raises ``QueueFullError`` when the cap is reached.

Progress Callbacks
------------------
Callbacks receive a ``ProgressEvent`` namedtuple.  Exceptions raised inside a
callback are caught and logged; they do not affect job state.

Thread Safety
-------------
``submit()``, ``submit_batch()``, ``cancel()``, ``get_status()``,
``get_result()``, and ``all_jobs()`` are all safe to call from any thread.
"""
from __future__ import annotations

import logging
import threading
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum, auto
from pathlib import Path
from typing import Callable, Optional, Sequence

from .converter import ConversionError, ConversionResult, convert_image

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Default maximum number of PENDING jobs held in the queue.
DEFAULT_MAX_PENDING: int = 200

#: Default number of worker threads.
DEFAULT_WORKERS: int = 2


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class QueueFullError(RuntimeError):
    """Raised when the pending queue has reached ``max_pending`` capacity."""


class JobNotFoundError(KeyError):
    """Raised when a job ID is not found in the queue's registry."""


# ---------------------------------------------------------------------------
# Job lifecycle
# ---------------------------------------------------------------------------

class JobStatus(Enum):
    """Explicit lifecycle states for a conversion job.

    Valid transitions::

        PENDING ──► RUNNING ──► SUCCEEDED
                │            └─► FAILED
                └──────────────► CANCELLED
    """
    PENDING   = auto()  # Submitted, not yet started.
    RUNNING   = auto()  # Worker has started processing.
    SUCCEEDED = auto()  # Completed successfully.
    FAILED    = auto()  # Completed with an error.
    CANCELLED = auto()  # Cancelled before the worker started.


# Map each status to the set of statuses it may legally transition to.
_VALID_TRANSITIONS: dict[JobStatus, frozenset[JobStatus]] = {
    JobStatus.PENDING:   frozenset({JobStatus.RUNNING, JobStatus.CANCELLED}),
    JobStatus.RUNNING:   frozenset({JobStatus.SUCCEEDED, JobStatus.FAILED}),
    JobStatus.SUCCEEDED: frozenset(),
    JobStatus.FAILED:    frozenset(),
    JobStatus.CANCELLED: frozenset(),
}

_TERMINAL: frozenset[JobStatus] = frozenset({
    JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELLED,
})


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class JobResult:
    """Structured result for a completed conversion job.

    Attributes
    ----------
    job_id:         Unique job identifier.
    status:         Terminal job status.
    output_path:    Written output file (set on SUCCEEDED only).
    source_format:  Detected or declared source format key.
    target_format:  Requested target format key.
    input_bytes:    Size of the source file in bytes.
    output_bytes:   Size of the output file in bytes (0 on failure).
    started_at:     UTC timestamp when the worker started.
    finished_at:    UTC timestamp when the worker finished.
    error:          Error message string (set on FAILED only).
    warnings:       Non-fatal advisory messages (currently unused).
    """
    job_id:        str
    status:        JobStatus
    output_path:   Optional[Path]
    source_format: Optional[str]
    target_format: str
    input_bytes:   int
    output_bytes:  int
    started_at:    datetime
    finished_at:   datetime
    error:         Optional[str] = None
    warnings:      tuple[str, ...] = field(default_factory=tuple)


class ProgressEvent(str, Enum):
    """Coarse lifecycle events delivered to progress callbacks.

    Values correspond to the transition point that just occurred.
    """
    QUEUED    = "queued"     # Job accepted into queue.
    STARTED   = "started"    # Worker began processing.
    SUCCEEDED = "succeeded"  # Conversion completed successfully.
    FAILED    = "failed"     # Conversion failed with an error.
    CANCELLED = "cancelled"  # Job was cancelled before running.


@dataclass(frozen=True)
class ConversionJob:
    """Immutable descriptor for a submitted conversion job.

    Created internally by ``JobQueue.submit()``; callers receive a copy.

    Attributes
    ----------
    job_id:           Unique identifier (UUID4 hex).
    source:           Absolute path to the source file.
    target_format:    Canonical target format key.
    output_dir:       Target output directory (``None`` → same as source).
    jpeg_background:  RGB fill for transparent → JPEG conversions.
    max_input_bytes:  Per-job file size cap.
    submitted_at:     UTC timestamp of submission.
    """
    job_id:          str
    source:          Path
    target_format:   str
    output_dir:      Optional[Path]
    jpeg_background: tuple[int, int, int]
    max_input_bytes: int
    submitted_at:    datetime


@dataclass()
class BatchSubmission:
    """Return value of ``JobQueue.submit_batch()``.

    Attributes
    ----------
    jobs:      Ordered list of accepted ``ConversionJob`` descriptors.
    rejected:  List of ``(index, reason)`` tuples for items that failed
               *pre-submission* validation (e.g. unrecognised format).
               Items that *execute* and fail are not listed here; they
               appear as FAILED jobs in the queue.
    """
    jobs:     list[ConversionJob]
    rejected: list[tuple[int, str]]


# ---------------------------------------------------------------------------
# Internal mutable job state (never exposed directly)
# ---------------------------------------------------------------------------

@dataclass()
class _JobState:
    """Mutable per-job state, protected by ``JobQueue._lock``."""
    job:       ConversionJob
    status:    JobStatus = JobStatus.PENDING
    result:    Optional[JobResult] = None
    future:    Optional[Future] = None   # type: ignore[type-arg]
    cancelled: bool = False              # Cooperative flag set by cancel().


# ---------------------------------------------------------------------------
# Progress callback type alias
# ---------------------------------------------------------------------------

ProgressCallback = Callable[[str, ProgressEvent, Optional[JobResult]], None]
"""
Signature: ``callback(job_id: str, event: ProgressEvent, result: Optional[JobResult]) -> None``

The ``result`` argument is non-``None`` only for terminal events
(SUCCEEDED, FAILED, CANCELLED).
"""


# ---------------------------------------------------------------------------
# JobQueue
# ---------------------------------------------------------------------------

class JobQueue:
    """Thread-safe job queue and execution engine for LocalShift conversions.

    Parameters
    ----------
    max_workers:
        Maximum number of concurrent worker threads.  Default: 2.
    max_pending:
        Maximum number of PENDING jobs accepted into the queue.  When this
        limit is reached, new submissions raise ``QueueFullError``.
        Default: 200.
    progress_callback:
        Optional callable invoked on each job lifecycle event.  Must not
        raise or perform blocking I/O; exceptions inside it are caught and
        logged.

    Thread Safety
    -------------
    All public methods are safe to call concurrently.  The internal
    ``_lock`` serialises all state mutations.

    Shutdown
    --------
    Call ``shutdown(wait=True)`` (or use as a context manager) to stop
    accepting new jobs and wait for running workers to finish.  PENDING
    jobs that have not started will be cancelled.

    Examples
    --------
    Single job::

        from pathlib import Path
        from localshift.jobs import JobQueue

        q = JobQueue()
        job = q.submit(Path("photo.png"), "jpeg")
        q.shutdown(wait=True)
        result = q.get_result(job.job_id)
        print(result.output_path)

    Batch::

        batch = q.submit_batch([
            (Path("a.png"), "jpeg"),
            (Path("b.png"), "webp"),
        ])
        q.shutdown(wait=True)
        for j in batch.jobs:
            r = q.get_result(j.job_id)
            print(r.status, r.output_path)
    """

    def __init__(
        self,
        *,
        max_workers: int = DEFAULT_WORKERS,
        max_pending: int = DEFAULT_MAX_PENDING,
        progress_callback: Optional[ProgressCallback] = None,
    ) -> None:
        if max_workers < 1:
            raise ValueError("max_workers must be >= 1")
        if max_pending < 1:
            raise ValueError("max_pending must be >= 1")

        self._max_pending = max_pending
        self._callback = progress_callback
        self._lock = threading.Lock()
        self._states: dict[str, _JobState] = {}  # job_id → _JobState
        self._shutdown_flag = False
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="ls-worker")

    # ------------------------------------------------------------------
    # Context manager support
    # ------------------------------------------------------------------

    def __enter__(self) -> "JobQueue":
        return self

    def __exit__(self, *_: object) -> None:
        self.shutdown(wait=True)

    # ------------------------------------------------------------------
    # Submission
    # ------------------------------------------------------------------

    def submit(
        self,
        source: Path | str,
        target_format: str,
        *,
        output_dir: Optional[Path | str] = None,
        jpeg_background: tuple[int, int, int] = (255, 255, 255),
        max_input_bytes: int = 250 * 1024 * 1024,
    ) -> ConversionJob:
        """Submit a single conversion job.

        Parameters
        ----------
        source:
            Path to the source image file.
        target_format:
            Target format string (canonical key or alias).
        output_dir:
            Directory where the output file is written.  ``None`` → same
            directory as *source*.
        jpeg_background:
            RGB fill colour used when compositing transparent images onto
            JPEG (which does not support transparency).
        max_input_bytes:
            Per-job file size limit.

        Returns
        -------
        ConversionJob
            Immutable job descriptor.  The job is PENDING at the time of
            return.

        Raises
        ------
        QueueFullError
            If ``max_pending`` PENDING jobs are already in the queue.
        RuntimeError
            If ``shutdown()`` has been called.
        """
        source = Path(source)
        output_dir_path = Path(output_dir) if output_dir is not None else None

        # Validate target format before allocating a job ID or queue slot.
        from .formats import normalize_format
        try:
            target_format = normalize_format(target_format)
        except ValueError as exc:
            raise ValueError(f"Invalid target format {target_format!r}: {exc}") from exc

        job_id = uuid.uuid4().hex
        now = datetime.now(tz=timezone.utc)

        job = ConversionJob(
            job_id=job_id,
            source=source,
            target_format=target_format,
            output_dir=output_dir_path,
            jpeg_background=jpeg_background,
            max_input_bytes=max_input_bytes,
            submitted_at=now,
        )

        with self._lock:
            if self._shutdown_flag:
                raise RuntimeError("JobQueue has been shut down; cannot accept new jobs.")
            pending_count = sum(
                1 for s in self._states.values()
                if s.status is JobStatus.PENDING
            )
            if pending_count >= self._max_pending:
                raise QueueFullError(
                    f"Queue is full ({self._max_pending} pending jobs). "
                    "Wait for jobs to complete before submitting more."
                )
            state = _JobState(job=job)
            self._states[job_id] = state

        log.debug("Job %s submitted: %s → %s", job_id[:8], source.name, target_format)
        self._fire(job_id, ProgressEvent.QUEUED, None)

        future = self._executor.submit(self._run_job, job_id)
        with self._lock:
            # State may already be CANCELLED if cancel() was called between
            # the two lock acquisitions above — this is acceptable; the future
            # will be a no-op when _run_job checks the flag.
            state.future = future

        return job

    def submit_batch(
        self,
        items: Sequence[tuple[Path | str, str]],
        *,
        output_dir: Optional[Path | str] = None,
        jpeg_background: tuple[int, int, int] = (255, 255, 255),
        max_input_bytes: int = 250 * 1024 * 1024,
    ) -> BatchSubmission:
        """Submit multiple conversion jobs as a batch.

        Each ``(source, target_format)`` tuple is validated and submitted
        independently.  Items that fail *pre-submission* validation (e.g.
        unrecognised format string) are placed in ``BatchSubmission.rejected``
        and do not consume queue slots.  Items that pass validation become
        PENDING jobs; their runtime failures are reported through the normal
        job lifecycle (FAILED status).

        The order of ``BatchSubmission.jobs`` matches the input order of
        accepted items.

        A ``QueueFullError`` from any individual submission is treated as a
        rejection for that item (and all subsequent items) rather than aborting
        the entire batch partway through.

        Parameters
        ----------
        items:
            Sequence of ``(source_path, target_format)`` tuples.
        output_dir:
            Common output directory for all jobs in this batch.
        jpeg_background, max_input_bytes:
            Applied uniformly to all jobs in the batch.

        Returns
        -------
        BatchSubmission
            Contains the list of accepted jobs and any per-item rejections.
        """
        accepted: list[ConversionJob] = []
        rejected: list[tuple[int, str]] = []

        for idx, (src, tgt) in enumerate(items):
            try:
                job = self.submit(
                    src,
                    tgt,
                    output_dir=output_dir,
                    jpeg_background=jpeg_background,
                    max_input_bytes=max_input_bytes,
                )
                accepted.append(job)
            except QueueFullError as exc:
                reason = f"Queue full: {exc}"
                log.warning("Batch item %d rejected: %s", idx, reason)
                rejected.append((idx, reason))
            except (ValueError, RuntimeError) as exc:
                reason = str(exc)
                log.warning("Batch item %d rejected: %s", idx, reason)
                rejected.append((idx, reason))

        return BatchSubmission(jobs=accepted, rejected=rejected)

    # ------------------------------------------------------------------
    # Cancellation
    # ------------------------------------------------------------------

    def cancel(self, job_id: str) -> bool:
        """Request cancellation of the job with *job_id*.

        Cancellation is supported **only for PENDING jobs**.  A PENDING job
        that is cancelled will never be executed; it transitions immediately
        to CANCELLED.

        A RUNNING job **cannot** be cancelled: Pillow decode/encode operations
        are synchronous C extensions with no cooperative cancellation point.
        ``cancel()`` will return ``False`` without affecting the running job.

        Parameters
        ----------
        job_id:
            Job identifier string.

        Returns
        -------
        bool
            ``True`` if the job was successfully cancelled (was PENDING);
            ``False`` if cancellation was not possible (already running,
            already terminal, or not found).
        """
        with self._lock:
            state = self._states.get(job_id)
            if state is None:
                log.debug("cancel: job %s not found", job_id[:8])
                return False

            if state.status is not JobStatus.PENDING:
                log.debug(
                    "cancel: job %s is %s — cannot cancel",
                    job_id[:8], state.status.name,
                )
                return False

            # Set cooperative flag; _run_job checks this on startup.
            state.cancelled = True
            self._transition(state, JobStatus.CANCELLED)
            now = datetime.now(tz=timezone.utc)
            state.result = JobResult(
                job_id=job_id,
                status=JobStatus.CANCELLED,
                output_path=None,
                source_format=None,
                target_format=state.job.target_format,
                input_bytes=0,
                output_bytes=0,
                started_at=now,
                finished_at=now,
            )

        log.info("Job %s cancelled (was PENDING)", job_id[:8])
        self._fire(job_id, ProgressEvent.CANCELLED, state.result)
        return True

    # ------------------------------------------------------------------
    # Status and result queries
    # ------------------------------------------------------------------

    def get_status(self, job_id: str) -> JobStatus:
        """Return the current :class:`JobStatus` for *job_id*.

        Raises
        ------
        JobNotFoundError
            If *job_id* is not registered.
        """
        with self._lock:
            state = self._states.get(job_id)
            if state is None:
                raise JobNotFoundError(job_id)
            return state.status

    def get_result(self, job_id: str) -> Optional[JobResult]:
        """Return the :class:`JobResult` for *job_id*, or ``None`` if not yet finished.

        Raises
        ------
        JobNotFoundError
            If *job_id* is not registered.
        """
        with self._lock:
            state = self._states.get(job_id)
            if state is None:
                raise JobNotFoundError(job_id)
            return state.result

    def all_jobs(self) -> list[tuple[str, JobStatus]]:
        """Return a snapshot list of ``(job_id, status)`` for all registered jobs.

        The list is ordered by submission time (insertion order is preserved
        in Python dicts since 3.7).
        """
        with self._lock:
            return [(jid, s.status) for jid, s in self._states.items()]

    def pending_count(self) -> int:
        """Return the current number of PENDING jobs."""
        with self._lock:
            return sum(1 for s in self._states.values() if s.status is JobStatus.PENDING)

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------

    def shutdown(self, wait: bool = True) -> None:
        """Stop the queue and optionally wait for running workers.

        After calling ``shutdown()``:
        - No new jobs will be accepted.
        - PENDING jobs that have not yet started are cancelled.
        - RUNNING jobs are allowed to complete normally (Pillow cannot be
          interrupted mid-decode).

        Parameters
        ----------
        wait:
            If ``True`` (default), block until all running workers finish.
        """
        with self._lock:
            self._shutdown_flag = True
            # Cancel all pending jobs.
            for jid, state in self._states.items():
                if state.status is JobStatus.PENDING:
                    state.cancelled = True
                    self._transition(state, JobStatus.CANCELLED)
                    now = datetime.now(tz=timezone.utc)
                    state.result = JobResult(
                        job_id=jid,
                        status=JobStatus.CANCELLED,
                        output_path=None,
                        source_format=None,
                        target_format=state.job.target_format,
                        input_bytes=0,
                        output_bytes=0,
                        started_at=now,
                        finished_at=now,
                    )

        # Fire CANCELLED events outside the lock.
        with self._lock:
            cancelled_results = [
                (jid, s.result)
                for jid, s in self._states.items()
                if s.status is JobStatus.CANCELLED and s.result is not None
            ]
        for jid, result in cancelled_results:
            self._fire(jid, ProgressEvent.CANCELLED, result)

        self._executor.shutdown(wait=wait)
        log.info("JobQueue shut down (wait=%s)", wait)

    # ------------------------------------------------------------------
    # Internal worker
    # ------------------------------------------------------------------

    def _run_job(self, job_id: str) -> None:
        """Worker function executed by the thread pool.

        Checks the cooperative cancellation flag before starting I/O.
        If the job was cancelled before the worker started, does nothing.
        """
        with self._lock:
            state = self._states.get(job_id)
            if state is None:
                log.error("Worker: job %s not found in state registry", job_id[:8])
                return
            if state.cancelled or state.status is JobStatus.CANCELLED:
                log.debug("Worker: job %s is already cancelled — skipping", job_id[:8])
                return
            self._transition(state, JobStatus.RUNNING)
            job = state.job

        started_at = datetime.now(tz=timezone.utc)
        self._fire(job_id, ProgressEvent.STARTED, None)
        log.info("Job %s started: %s → %s", job_id[:8], job.source.name, job.target_format)

        source_fmt: Optional[str] = None
        output_path: Optional[Path] = None
        input_bytes = 0
        output_bytes = 0
        error_msg: Optional[str] = None
        terminal_status: JobStatus

        try:
            # Collect input size before conversion (may raise if file missing).
            if job.source.exists():
                input_bytes = job.source.stat().st_size

            output_path = convert_image(
                job.source,
                job.target_format,
                job.output_dir,
                jpeg_background=job.jpeg_background,
                max_input_bytes=job.max_input_bytes,
            )
            output_bytes = output_path.stat().st_size if output_path and output_path.exists() else 0

            # Best-effort source format detection for the result record.
            from .formats import sniff_format, input_format as _ext_fmt
            source_fmt = sniff_format(job.source) or _ext_fmt(job.source)

            terminal_status = JobStatus.SUCCEEDED
            log.info("Job %s succeeded: %s (%d bytes)", job_id[:8], output_path, output_bytes)

        except ConversionError as exc:
            error_msg = str(exc)
            terminal_status = JobStatus.FAILED
            log.error("Job %s failed: %s", job_id[:8], error_msg)

        except Exception as exc:  # pragma: no cover
            error_msg = f"Unexpected error: {exc}"
            terminal_status = JobStatus.FAILED
            log.exception("Job %s failed with unexpected exception", job_id[:8])

        finished_at = datetime.now(tz=timezone.utc)
        result = JobResult(
            job_id=job_id,
            status=terminal_status,
            output_path=output_path,
            source_format=source_fmt,
            target_format=job.target_format,
            input_bytes=input_bytes,
            output_bytes=output_bytes,
            started_at=started_at,
            finished_at=finished_at,
            error=error_msg,
        )

        with self._lock:
            state = self._states[job_id]
            self._transition(state, terminal_status)
            state.result = result

        event = (
            ProgressEvent.SUCCEEDED
            if terminal_status is JobStatus.SUCCEEDED
            else ProgressEvent.FAILED
        )
        self._fire(job_id, event, result)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _transition(self, state: _JobState, new_status: JobStatus) -> None:
        """Validate and apply a status transition.  Caller must hold ``_lock``."""
        allowed = _VALID_TRANSITIONS[state.status]
        if new_status not in allowed:
            raise RuntimeError(
                f"Illegal job state transition: {state.status.name} → {new_status.name} "
                f"for job {state.job.job_id[:8]}"
            )
        state.status = new_status

    def _fire(
        self,
        job_id: str,
        event: ProgressEvent,
        result: Optional[JobResult],
    ) -> None:
        """Invoke the progress callback safely (exceptions are swallowed)."""
        if self._callback is None:
            return
        try:
            self._callback(job_id, event, result)
        except Exception:
            log.exception(
                "Progress callback raised an exception for job %s / %s — ignoring",
                job_id[:8], event,
            )
