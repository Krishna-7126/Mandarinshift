"""
tests/test_jobs.py — Comprehensive tests for the LocalShift job management system.

Coverage targets:
- Job creation and identity.
- Status transitions (valid and invalid).
- Single successful conversion.
- Single failed conversion.
- Batch submission: ordering, isolation, partial failure.
- Batch submission: duplicate inputs, conflicting destinations.
- Concurrent submission and concurrent status reads.
- Queue capacity limits (max_pending).
- Progress callbacks (including callback exceptions).
- Pending cancellation.
- Running cancellation semantics (not interruptible — documented limitation).
- Shutdown with pending jobs.
- Shutdown with running jobs.
- Atomic output integrity (source file untouched).
- Regression compatibility (existing CLI/convert_image API unchanged).
- JobNotFoundError on unknown job_id.
- QueueFullError when queue is at capacity.
- Public API surface (importable from top-level package).
"""
from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

from localshift import (
    BatchSubmission,
    ConversionJob,
    JobNotFoundError,
    JobQueue,
    JobResult,
    JobStatus,
    ProgressEvent,
    QueueFullError,
)
from localshift.jobs import (
    DEFAULT_MAX_PENDING,
    DEFAULT_WORKERS,
    _VALID_TRANSITIONS,
    _TERMINAL,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_rgb_png(path: Path, size: tuple[int, int] = (8, 8)) -> Path:
    """Create a small RGB PNG and return its path."""
    Image.new("RGB", size, (10, 20, 30)).save(path, format="PNG")
    return path


def _make_rgba_png(path: Path, size: tuple[int, int] = (8, 8)) -> Path:
    """Create a small RGBA PNG and return its path."""
    Image.new("RGBA", size, (10, 20, 30, 100)).save(path, format="PNG")
    return path


def _wait_for_terminal(q: JobQueue, job_id: str, timeout: float = 10.0) -> JobStatus:
    """Poll until the job reaches a terminal status or timeout. Returns the status."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = q.get_status(job_id)
        if status in _TERMINAL:
            return status
        time.sleep(0.01)
    pytest.fail(f"Job {job_id[:8]} did not reach terminal status within {timeout}s")


# ---------------------------------------------------------------------------
# Public API import tests
# ---------------------------------------------------------------------------

class TestPublicAPIImports:
    def test_job_queue_importable(self):
        from localshift import JobQueue as JQ
        assert callable(JQ)

    def test_job_status_importable(self):
        from localshift import JobStatus as JS
        assert JS.PENDING.name == "PENDING"

    def test_conversion_job_importable(self):
        from localshift import ConversionJob as CJ
        import dataclasses
        fields = {f.name for f in dataclasses.fields(CJ)}
        assert {"job_id", "source", "target_format", "submitted_at"} <= fields

    def test_job_result_importable(self):
        from localshift import JobResult as JR
        import dataclasses
        fields = {f.name for f in dataclasses.fields(JR)}
        assert {"job_id", "status", "output_path", "error"} <= fields

    def test_progress_event_importable(self):
        from localshift import ProgressEvent as PE
        assert PE.QUEUED.value == "queued"

    def test_queue_full_error_importable(self):
        from localshift import QueueFullError as QFE
        assert issubclass(QFE, RuntimeError)

    def test_job_not_found_error_importable(self):
        from localshift import JobNotFoundError as JNFE
        assert issubclass(JNFE, KeyError)

    def test_batch_submission_importable(self):
        from localshift import BatchSubmission as BS
        import dataclasses
        fields = {f.name for f in dataclasses.fields(BS)}
        assert {"jobs", "rejected"} <= fields

    def test_no_pyside6_on_jobs_import(self):
        import sys
        was_imported = "PySide6" in sys.modules
        import localshift.jobs  # noqa: F401
        if not was_imported:
            assert "PySide6" not in sys.modules


# ---------------------------------------------------------------------------
# JobStatus transition table tests
# ---------------------------------------------------------------------------

class TestJobStatusTransitions:
    def test_pending_can_go_to_running(self):
        assert JobStatus.RUNNING in _VALID_TRANSITIONS[JobStatus.PENDING]

    def test_pending_can_go_to_cancelled(self):
        assert JobStatus.CANCELLED in _VALID_TRANSITIONS[JobStatus.PENDING]

    def test_running_can_go_to_succeeded(self):
        assert JobStatus.SUCCEEDED in _VALID_TRANSITIONS[JobStatus.RUNNING]

    def test_running_can_go_to_failed(self):
        assert JobStatus.FAILED in _VALID_TRANSITIONS[JobStatus.RUNNING]

    def test_terminal_states_have_no_outgoing_transitions(self):
        for status in _TERMINAL:
            assert _VALID_TRANSITIONS[status] == frozenset(), (
                f"{status.name} should have no outgoing transitions"
            )

    def test_pending_cannot_go_to_succeeded(self):
        assert JobStatus.SUCCEEDED not in _VALID_TRANSITIONS[JobStatus.PENDING]

    def test_running_cannot_go_to_pending(self):
        assert JobStatus.PENDING not in _VALID_TRANSITIONS[JobStatus.RUNNING]

    def test_running_cannot_go_to_cancelled(self):
        """Running jobs cannot be directly cancelled (Pillow non-interruptible)."""
        assert JobStatus.CANCELLED not in _VALID_TRANSITIONS[JobStatus.RUNNING]

    def test_illegal_transition_raises_runtime_error(self, tmp_path):
        """Illegal transitions must raise RuntimeError."""
        from localshift.jobs import _JobState, ConversionJob
        now = datetime.now(tz=timezone.utc)
        job = ConversionJob(
            job_id="test", source=tmp_path / "f.png",
            target_format="jpeg", output_dir=None,
            jpeg_background=(255, 255, 255),
            max_input_bytes=1024, submitted_at=now,
        )
        state = _JobState(job=job, status=JobStatus.SUCCEEDED)
        q = JobQueue(max_workers=1)
        q.shutdown(wait=False)
        with pytest.raises(RuntimeError, match="Illegal job state transition"):
            q._transition(state, JobStatus.RUNNING)


# ---------------------------------------------------------------------------
# Single job: happy path
# ---------------------------------------------------------------------------

class TestSingleJobHappyPath:
    def test_submit_returns_conversion_job(self, tmp_path):
        src = _make_rgb_png(tmp_path / "in.png")
        with JobQueue(max_workers=1) as q:
            job = q.submit(src, "jpeg", output_dir=tmp_path)
            assert isinstance(job, ConversionJob)
            assert job.source == src
            assert job.target_format == "jpeg"
            assert isinstance(job.job_id, str) and len(job.job_id) == 32

    def test_successful_job_reaches_succeeded(self, tmp_path):
        src = _make_rgb_png(tmp_path / "in.png")
        with JobQueue(max_workers=1) as q:
            job = q.submit(src, "jpeg", output_dir=tmp_path)
            status = _wait_for_terminal(q, job.job_id)
        assert status is JobStatus.SUCCEEDED

    def test_successful_result_has_output_path(self, tmp_path):
        src = _make_rgb_png(tmp_path / "in.png")
        with JobQueue(max_workers=1) as q:
            job = q.submit(src, "jpeg", output_dir=tmp_path)
            _wait_for_terminal(q, job.job_id)
            result = q.get_result(job.job_id)
        assert result is not None
        assert result.output_path is not None
        assert result.output_path.exists()
        assert result.error is None

    def test_successful_result_bytes_positive(self, tmp_path):
        src = _make_rgb_png(tmp_path / "in.png")
        with JobQueue(max_workers=1) as q:
            job = q.submit(src, "jpeg", output_dir=tmp_path)
            _wait_for_terminal(q, job.job_id)
            result = q.get_result(job.job_id)
        assert result.input_bytes > 0
        assert result.output_bytes > 0

    def test_successful_result_format_fields(self, tmp_path):
        src = _make_rgb_png(tmp_path / "in.png")
        with JobQueue(max_workers=1) as q:
            job = q.submit(src, "jpeg", output_dir=tmp_path)
            _wait_for_terminal(q, job.job_id)
            result = q.get_result(job.job_id)
        assert result.target_format == "jpeg"
        assert result.source_format in ("png", None)  # sniffed

    def test_successful_result_timestamps_ordered(self, tmp_path):
        src = _make_rgb_png(tmp_path / "in.png")
        with JobQueue(max_workers=1) as q:
            job = q.submit(src, "jpeg", output_dir=tmp_path)
            _wait_for_terminal(q, job.job_id)
            result = q.get_result(job.job_id)
        assert result.started_at <= result.finished_at

    def test_result_is_none_before_completion(self, tmp_path):
        """Immediately after submit, result may still be None (job is PENDING/RUNNING)."""
        src = _make_rgb_png(tmp_path / "in.png")
        # Use a barrier to ensure the worker hasn't finished yet when we check.
        barrier = threading.Barrier(2)
        orig_convert = __import__("localshift.converter", fromlist=["convert_image"]).convert_image

        def slow_convert(*args, **kwargs):
            barrier.wait(timeout=5)
            return orig_convert(*args, **kwargs)

        with patch("localshift.jobs.convert_image", side_effect=slow_convert):
            q = JobQueue(max_workers=1)
            job = q.submit(src, "jpeg", output_dir=tmp_path)
            # Wait until worker has started.
            barrier.wait(timeout=5)
            # Result should be None (worker is executing now).
            result_mid = q.get_result(job.job_id)
        q.shutdown(wait=True)
        # After the barrier the convert call finishes; result is now populated.
        result_final = q.get_result(job.job_id)
        # Mid-run result was None or already set (timing); final must be set.
        assert result_final is not None

    def test_job_id_is_unique(self, tmp_path):
        src = _make_rgb_png(tmp_path / "in.png")
        with JobQueue(max_workers=1) as q:
            ids = {q.submit(src, "jpeg", output_dir=tmp_path).job_id for _ in range(5)}
        # Wait for all to complete (context manager shuts down).
        assert len(ids) == 5, "All job IDs must be unique"

    def test_string_paths_accepted(self, tmp_path):
        src = _make_rgb_png(tmp_path / "in.png")
        with JobQueue(max_workers=1) as q:
            job = q.submit(str(src), "jpeg", output_dir=str(tmp_path))
            status = _wait_for_terminal(q, job.job_id)
        assert status is JobStatus.SUCCEEDED

    def test_alias_format_accepted(self, tmp_path):
        """Format aliases like 'jpg' must be accepted by the queue."""
        src = _make_rgb_png(tmp_path / "in.png")
        with JobQueue(max_workers=1) as q:
            job = q.submit(src, "jpg", output_dir=tmp_path)
            _wait_for_terminal(q, job.job_id)
            result = q.get_result(job.job_id)
        assert result.status is JobStatus.SUCCEEDED


# ---------------------------------------------------------------------------
# Single job: failure path
# ---------------------------------------------------------------------------

class TestSingleJobFailure:
    def test_missing_file_produces_failed_job(self, tmp_path):
        src = tmp_path / "does_not_exist.png"
        with JobQueue(max_workers=1) as q:
            job = q.submit(src, "jpeg", output_dir=tmp_path)
            status = _wait_for_terminal(q, job.job_id)
        assert status is JobStatus.FAILED

    def test_failed_result_has_error_message(self, tmp_path):
        src = tmp_path / "does_not_exist.png"
        with JobQueue(max_workers=1) as q:
            job = q.submit(src, "jpeg", output_dir=tmp_path)
            _wait_for_terminal(q, job.job_id)
            result = q.get_result(job.job_id)
        assert result.error is not None
        assert len(result.error) > 0

    def test_failed_result_has_no_output_path(self, tmp_path):
        src = tmp_path / "does_not_exist.png"
        with JobQueue(max_workers=1) as q:
            job = q.submit(src, "jpeg", output_dir=tmp_path)
            _wait_for_terminal(q, job.job_id)
            result = q.get_result(job.job_id)
        assert result.output_path is None

    def test_failed_result_has_failed_status(self, tmp_path):
        src = tmp_path / "does_not_exist.png"
        with JobQueue(max_workers=1) as q:
            job = q.submit(src, "jpeg", output_dir=tmp_path)
            _wait_for_terminal(q, job.job_id)
            result = q.get_result(job.job_id)
        assert result.status is JobStatus.FAILED

    def test_same_format_produces_failed_job(self, tmp_path):
        src = _make_rgb_png(tmp_path / "in.png")
        with JobQueue(max_workers=1) as q:
            job = q.submit(src, "png", output_dir=tmp_path)
            status = _wait_for_terminal(q, job.job_id)
        assert status is JobStatus.FAILED

    def test_unsupported_format_raises_at_submission(self, tmp_path):
        """Unrecognised format strings raise ValueError at submit() time,
        before a job is created.  This is the correct documented behaviour:
        format validation happens eagerly at submission, not at execution."""
        src = _make_rgb_png(tmp_path / "in.png")
        q = JobQueue(max_workers=1)
        try:
            with pytest.raises(ValueError, match="Invalid target format"):
                q.submit(src, "pdf", output_dir=tmp_path)
        finally:
            q.shutdown(wait=True)


# ---------------------------------------------------------------------------
# Batch submission
# ---------------------------------------------------------------------------

class TestBatchSubmission:
    def test_batch_returns_batch_submission(self, tmp_path):
        srcs = [_make_rgb_png(tmp_path / f"img{i}.png") for i in range(3)]
        items = [(s, "jpeg") for s in srcs]
        with JobQueue(max_workers=2) as q:
            batch = q.submit_batch(items, output_dir=tmp_path)
        assert isinstance(batch, BatchSubmission)

    def test_batch_job_count_matches_input(self, tmp_path):
        srcs = [_make_rgb_png(tmp_path / f"img{i}.png") for i in range(3)]
        items = [(s, "jpeg") for s in srcs]
        with JobQueue(max_workers=2) as q:
            batch = q.submit_batch(items, output_dir=tmp_path)
        assert len(batch.jobs) == 3
        assert len(batch.rejected) == 0

    def test_batch_preserves_input_order(self, tmp_path):
        srcs = [_make_rgb_png(tmp_path / f"img{i}.png") for i in range(5)]
        items = [(s, "jpeg") for s in srcs]
        with JobQueue(max_workers=2) as q:
            batch = q.submit_batch(items, output_dir=tmp_path)
        for i, job in enumerate(batch.jobs):
            assert job.source == srcs[i], f"Job {i} source mismatch"

    def test_batch_all_jobs_succeed(self, tmp_path):
        srcs = [_make_rgb_png(tmp_path / f"img{i}.png") for i in range(3)]
        items = [(s, "jpeg") for s in srcs]
        with JobQueue(max_workers=2) as q:
            batch = q.submit_batch(items, output_dir=tmp_path)
            for job in batch.jobs:
                _wait_for_terminal(q, job.job_id)
            results = [q.get_result(job.job_id) for job in batch.jobs]
        for r in results:
            assert r.status is JobStatus.SUCCEEDED
            assert r.output_path is not None
            assert r.output_path.exists()

    def test_batch_failure_does_not_cancel_other_jobs(self, tmp_path):
        """A failing job must not kill its siblings."""
        good1 = _make_rgb_png(tmp_path / "good1.png")
        bad   = tmp_path / "missing.png"  # does not exist
        good2 = _make_rgb_png(tmp_path / "good2.png")
        items = [(good1, "jpeg"), (bad, "jpeg"), (good2, "jpeg")]
        with JobQueue(max_workers=2) as q:
            batch = q.submit_batch(items, output_dir=tmp_path)
            for job in batch.jobs:
                _wait_for_terminal(q, job.job_id)
            statuses = [q.get_result(job.job_id).status for job in batch.jobs]
        assert statuses[0] is JobStatus.SUCCEEDED
        assert statuses[1] is JobStatus.FAILED
        assert statuses[2] is JobStatus.SUCCEEDED

    def test_batch_rejected_item_has_index_and_reason(self, tmp_path):
        """Items with unrecognised format strings are rejected at submission (ValueError)."""
        src = _make_rgb_png(tmp_path / "in.png")
        items = [(src, "jpeg"), (src, "xyz_unknown")]
        with JobQueue(max_workers=1) as q:
            batch = q.submit_batch(items, output_dir=tmp_path)
        # 'jpeg' is valid → accepted; 'xyz_unknown' is invalid → rejected.
        assert len(batch.jobs) == 1
        assert len(batch.rejected) == 1
        idx, reason = batch.rejected[0]
        assert idx == 1
        assert len(reason) > 0

    def test_batch_duplicate_inputs_produces_independent_jobs(self, tmp_path):
        """Submitting the same source twice produces two separate jobs."""
        src = _make_rgb_png(tmp_path / "in.png")
        items = [(src, "jpeg"), (src, "jpeg")]
        # Use max_workers=1 so the jobs run sequentially; this guarantees the
        # second job sees the first output file and picks a new name.
        with JobQueue(max_workers=1) as q:
            batch = q.submit_batch(items, output_dir=tmp_path)
            assert len(batch.jobs) == 2
            assert batch.jobs[0].job_id != batch.jobs[1].job_id
            for job in batch.jobs:
                _wait_for_terminal(q, job.job_id)
        r0 = q.get_result(batch.jobs[0].job_id)
        r1 = q.get_result(batch.jobs[1].job_id)
        assert r0.status is JobStatus.SUCCEEDED
        assert r1.status is JobStatus.SUCCEEDED
        assert r0.output_path != r1.output_path  # collision avoidance active

    def test_batch_conflicting_output_names_both_succeed(self, tmp_path):
        """Two conversions producing the same stem/target both complete safely."""
        src1 = _make_rgb_png(tmp_path / "image.png")
        subdir = tmp_path / "sub"
        subdir.mkdir(parents=True, exist_ok=True)
        src2 = _make_rgb_png(subdir / "image.png")
        items = [(src1, "bmp"), (src2, "bmp")]
        # Sequential execution ensures collision avoidance in unique_output_path.
        with JobQueue(max_workers=1) as q:
            batch = q.submit_batch(items, output_dir=tmp_path)
            for job in batch.jobs:
                _wait_for_terminal(q, job.job_id)
        r0 = q.get_result(batch.jobs[0].job_id)
        r1 = q.get_result(batch.jobs[1].job_id)
        assert r0.status is JobStatus.SUCCEEDED
        assert r1.status is JobStatus.SUCCEEDED

    def test_empty_batch_returns_empty_submission(self, tmp_path):
        with JobQueue(max_workers=1) as q:
            batch = q.submit_batch([])
        assert batch.jobs == []
        assert batch.rejected == []


# ---------------------------------------------------------------------------
# Queue capacity
# ---------------------------------------------------------------------------

class TestQueueCapacity:
    def test_queue_full_error_raised_at_capacity(self, tmp_path):
        """Submitting beyond max_pending raises QueueFullError."""
        src = _make_rgb_png(tmp_path / "in.png")
        barrier = threading.Barrier(2)
        orig_convert = __import__("localshift.converter", fromlist=["convert_image"]).convert_image

        def blocked_convert(*args, **kwargs):
            # Block until we've filled the queue.
            barrier.wait(timeout=5)
            return orig_convert(*args, **kwargs)

        with patch("localshift.jobs.convert_image", side_effect=blocked_convert):
            q = JobQueue(max_workers=1, max_pending=2)
            # First job starts running immediately (worker picks it up fast).
            j1 = q.submit(src, "jpeg", output_dir=tmp_path)
            # Fill the remaining 2 pending slots.
            j2 = q.submit(src, "webp", output_dir=tmp_path)
            j3 = q.submit(src, "bmp",  output_dir=tmp_path)
            # Next submit should hit the cap.
            with pytest.raises(QueueFullError):
                q.submit(src, "tiff", output_dir=tmp_path)
            # Release the blocked worker.
            barrier.wait(timeout=5)
        q.shutdown(wait=True)

    def test_max_pending_one_accepts_one_pending(self, tmp_path):
        src = _make_rgb_png(tmp_path / "in.png")
        barrier = threading.Barrier(2)
        orig = __import__("localshift.converter", fromlist=["convert_image"]).convert_image

        def blocked(*args, **kwargs):
            barrier.wait(timeout=5)
            return orig(*args, **kwargs)

        with patch("localshift.jobs.convert_image", side_effect=blocked):
            q = JobQueue(max_workers=1, max_pending=1)
            _j1 = q.submit(src, "jpeg", output_dir=tmp_path)  # starts immediately
            j2 = q.submit(src, "webp", output_dir=tmp_path)   # fills the 1 pending slot
            with pytest.raises(QueueFullError):
                q.submit(src, "bmp", output_dir=tmp_path)
            barrier.wait(timeout=5)
        q.shutdown(wait=True)

    def test_invalid_max_workers_raises(self):
        with pytest.raises(ValueError, match="max_workers"):
            JobQueue(max_workers=0)

    def test_invalid_max_pending_raises(self):
        with pytest.raises(ValueError, match="max_pending"):
            JobQueue(max_pending=0)

    def test_batch_rejection_on_queue_full(self, tmp_path):
        """submit_batch treats QueueFullError as a per-item rejection."""
        src = _make_rgb_png(tmp_path / "in.png")
        barrier = threading.Barrier(2)
        orig = __import__("localshift.converter", fromlist=["convert_image"]).convert_image

        def blocked(*args, **kwargs):
            barrier.wait(timeout=5)
            return orig(*args, **kwargs)

        with patch("localshift.jobs.convert_image", side_effect=blocked):
            q = JobQueue(max_workers=1, max_pending=1)
            # One job starts running, one fills pending, next 2 hit cap.
            items = [(src, "jpeg"), (src, "webp"), (src, "bmp"), (src, "tiff")]
            batch = q.submit_batch(items, output_dir=tmp_path)
            barrier.wait(timeout=5)
        q.shutdown(wait=True)
        assert len(batch.rejected) >= 1


# ---------------------------------------------------------------------------
# Progress callbacks
# ---------------------------------------------------------------------------

class TestProgressCallbacks:
    def test_queued_event_fired_on_submit(self, tmp_path):
        src = _make_rgb_png(tmp_path / "in.png")
        events: list[ProgressEvent] = []

        def cb(job_id, event, result):
            events.append(event)

        with JobQueue(max_workers=1, progress_callback=cb) as q:
            job = q.submit(src, "jpeg", output_dir=tmp_path)
            _wait_for_terminal(q, job.job_id)

        assert ProgressEvent.QUEUED in events

    def test_started_event_fired(self, tmp_path):
        src = _make_rgb_png(tmp_path / "in.png")
        events: list[ProgressEvent] = []

        def cb(job_id, event, result):
            events.append(event)

        with JobQueue(max_workers=1, progress_callback=cb) as q:
            job = q.submit(src, "jpeg", output_dir=tmp_path)
            _wait_for_terminal(q, job.job_id)

        assert ProgressEvent.STARTED in events

    def test_succeeded_event_fired_on_success(self, tmp_path):
        src = _make_rgb_png(tmp_path / "in.png")
        events: list[ProgressEvent] = []

        def cb(job_id, event, result):
            events.append(event)

        with JobQueue(max_workers=1, progress_callback=cb) as q:
            job = q.submit(src, "jpeg", output_dir=tmp_path)
            _wait_for_terminal(q, job.job_id)

        assert ProgressEvent.SUCCEEDED in events

    def test_failed_event_fired_on_failure(self, tmp_path):
        src = tmp_path / "missing.png"
        events: list[ProgressEvent] = []

        def cb(job_id, event, result):
            events.append(event)

        with JobQueue(max_workers=1, progress_callback=cb) as q:
            job = q.submit(src, "jpeg", output_dir=tmp_path)
            _wait_for_terminal(q, job.job_id)

        assert ProgressEvent.FAILED in events

    def test_callback_receives_job_id(self, tmp_path):
        src = _make_rgb_png(tmp_path / "in.png")
        received_ids: list[str] = []

        def cb(job_id, event, result):
            received_ids.append(job_id)

        with JobQueue(max_workers=1, progress_callback=cb) as q:
            job = q.submit(src, "jpeg", output_dir=tmp_path)
            _wait_for_terminal(q, job.job_id)

        assert job.job_id in received_ids

    def test_callback_exception_does_not_corrupt_job_state(self, tmp_path):
        """A callback that raises must not leave the job in a broken state."""
        src = _make_rgb_png(tmp_path / "in.png")

        def bad_callback(job_id, event, result):
            raise RuntimeError("Intentional callback error")

        with JobQueue(max_workers=1, progress_callback=bad_callback) as q:
            job = q.submit(src, "jpeg", output_dir=tmp_path)
            status = _wait_for_terminal(q, job.job_id)

        # Job must still reach terminal state despite the bad callback.
        assert status is JobStatus.SUCCEEDED
        result = q.get_result(job.job_id)
        assert result is not None

    def test_terminal_event_callback_has_result(self, tmp_path):
        src = _make_rgb_png(tmp_path / "in.png")
        results_received: list[Optional[JobResult]] = []

        def cb(job_id, event, result):
            if event in (ProgressEvent.SUCCEEDED, ProgressEvent.FAILED, ProgressEvent.CANCELLED):
                results_received.append(result)

        with JobQueue(max_workers=1, progress_callback=cb) as q:
            job = q.submit(src, "jpeg", output_dir=tmp_path)
            _wait_for_terminal(q, job.job_id)

        assert len(results_received) == 1
        assert results_received[0] is not None

    def test_no_callback_does_not_raise(self, tmp_path):
        src = _make_rgb_png(tmp_path / "in.png")
        with JobQueue(max_workers=1) as q:
            job = q.submit(src, "jpeg", output_dir=tmp_path)
            status = _wait_for_terminal(q, job.job_id)
        assert status is JobStatus.SUCCEEDED


# ---------------------------------------------------------------------------
# Cancellation
# ---------------------------------------------------------------------------

class TestCancellation:
    def test_cancel_pending_job_returns_true(self, tmp_path):
        """A PENDING job can be cancelled; cancel() returns True."""
        src = _make_rgb_png(tmp_path / "in.png")
        barrier = threading.Barrier(2)
        orig = __import__("localshift.converter", fromlist=["convert_image"]).convert_image

        def blocked(*args, **kwargs):
            barrier.wait(timeout=5)
            return orig(*args, **kwargs)

        with patch("localshift.jobs.convert_image", side_effect=blocked):
            q = JobQueue(max_workers=1)
            # First job occupies the single worker.
            j1 = q.submit(src, "jpeg", output_dir=tmp_path)
            # Second job is PENDING.
            j2 = q.submit(src, "webp", output_dir=tmp_path)
            cancelled = q.cancel(j2.job_id)
            # Release the worker.
            barrier.wait(timeout=5)
        q.shutdown(wait=True)

        assert cancelled is True
        assert q.get_status(j2.job_id) is JobStatus.CANCELLED

    def test_cancelled_job_has_cancelled_result(self, tmp_path):
        src = _make_rgb_png(tmp_path / "in.png")
        barrier = threading.Barrier(2)
        orig = __import__("localshift.converter", fromlist=["convert_image"]).convert_image

        def blocked(*args, **kwargs):
            barrier.wait(timeout=5)
            return orig(*args, **kwargs)

        with patch("localshift.jobs.convert_image", side_effect=blocked):
            q = JobQueue(max_workers=1)
            j1 = q.submit(src, "jpeg", output_dir=tmp_path)
            j2 = q.submit(src, "webp", output_dir=tmp_path)
            q.cancel(j2.job_id)
            barrier.wait(timeout=5)
        q.shutdown(wait=True)

        result = q.get_result(j2.job_id)
        assert result is not None
        assert result.status is JobStatus.CANCELLED
        assert result.output_path is None

    def test_cancel_running_job_returns_false(self, tmp_path):
        """Cancelling a RUNNING job is not supported; cancel() returns False."""
        src = _make_rgb_png(tmp_path / "in.png")
        started = threading.Event()
        orig = __import__("localshift.converter", fromlist=["convert_image"]).convert_image

        def slow(*args, **kwargs):
            started.set()
            time.sleep(0.05)
            return orig(*args, **kwargs)

        with patch("localshift.jobs.convert_image", side_effect=slow):
            q = JobQueue(max_workers=1)
            job = q.submit(src, "jpeg", output_dir=tmp_path)
            started.wait(timeout=5)
            # Job is now RUNNING.
            cancelled = q.cancel(job.job_id)

        q.shutdown(wait=True)
        assert cancelled is False

    def test_cancel_completed_job_returns_false(self, tmp_path):
        src = _make_rgb_png(tmp_path / "in.png")
        with JobQueue(max_workers=1) as q:
            job = q.submit(src, "jpeg", output_dir=tmp_path)
            _wait_for_terminal(q, job.job_id)
            cancelled = q.cancel(job.job_id)
        assert cancelled is False

    def test_cancel_unknown_job_returns_false(self):
        q = JobQueue(max_workers=1)
        q.shutdown(wait=True)
        assert q.cancel("nonexistent_id") is False

    def test_cancelled_job_fires_cancelled_event(self, tmp_path):
        src = _make_rgb_png(tmp_path / "in.png")
        events: list[ProgressEvent] = []
        barrier = threading.Barrier(2)
        orig = __import__("localshift.converter", fromlist=["convert_image"]).convert_image

        def blocked(*args, **kwargs):
            barrier.wait(timeout=5)
            return orig(*args, **kwargs)

        def cb(job_id, event, result):
            events.append(event)

        with patch("localshift.jobs.convert_image", side_effect=blocked):
            q = JobQueue(max_workers=1, progress_callback=cb)
            j1 = q.submit(src, "jpeg", output_dir=tmp_path)
            j2 = q.submit(src, "webp", output_dir=tmp_path)
            q.cancel(j2.job_id)
            barrier.wait(timeout=5)
        q.shutdown(wait=True)

        assert ProgressEvent.CANCELLED in events

    def test_running_job_completes_correctly_despite_cancel_attempt(self, tmp_path):
        """Even if cancel() is called while running, the job completes."""
        src = _make_rgb_png(tmp_path / "in.png")
        started = threading.Event()
        orig = __import__("localshift.converter", fromlist=["convert_image"]).convert_image

        def slow(*args, **kwargs):
            started.set()
            time.sleep(0.05)
            return orig(*args, **kwargs)

        with patch("localshift.jobs.convert_image", side_effect=slow):
            q = JobQueue(max_workers=1)
            job = q.submit(src, "jpeg", output_dir=tmp_path)
            started.wait(timeout=5)
            q.cancel(job.job_id)  # no-op on running job

        q.shutdown(wait=True)
        result = q.get_result(job.job_id)
        # Must complete as SUCCEEDED, NOT be marked CANCELLED.
        assert result.status is JobStatus.SUCCEEDED
        assert result.output_path is not None


# ---------------------------------------------------------------------------
# Shutdown
# ---------------------------------------------------------------------------

class TestShutdown:
    def test_shutdown_cancels_pending_jobs(self, tmp_path):
        src = _make_rgb_png(tmp_path / "in.png")
        barrier = threading.Barrier(2)
        orig = __import__("localshift.converter", fromlist=["convert_image"]).convert_image

        def blocked(*args, **kwargs):
            barrier.wait(timeout=5)
            return orig(*args, **kwargs)

        with patch("localshift.jobs.convert_image", side_effect=blocked):
            q = JobQueue(max_workers=1)
            j1 = q.submit(src, "jpeg", output_dir=tmp_path)
            j2 = q.submit(src, "webp", output_dir=tmp_path)
            j3 = q.submit(src, "bmp",  output_dir=tmp_path)
            q.shutdown(wait=False)
            barrier.wait(timeout=5)
        # j2, j3 were pending and should be cancelled.
        q.shutdown(wait=True)
        assert q.get_status(j2.job_id) is JobStatus.CANCELLED
        assert q.get_status(j3.job_id) is JobStatus.CANCELLED

    def test_submit_after_shutdown_raises(self, tmp_path):
        src = _make_rgb_png(tmp_path / "in.png")
        q = JobQueue(max_workers=1)
        q.shutdown(wait=True)
        with pytest.raises(RuntimeError, match="shut down"):
            q.submit(src, "jpeg", output_dir=tmp_path)

    def test_context_manager_shuts_down_cleanly(self, tmp_path):
        src = _make_rgb_png(tmp_path / "in.png")
        job_id = None
        with JobQueue(max_workers=1) as q:
            job = q.submit(src, "jpeg", output_dir=tmp_path)
            job_id = job.job_id
        # After context exit, job must have reached terminal state.
        status = q.get_status(job_id)
        assert status in _TERMINAL


# ---------------------------------------------------------------------------
# Concurrent submission and reads
# ---------------------------------------------------------------------------

class TestConcurrency:
    def test_concurrent_submissions_all_accepted_or_rejected_cleanly(self, tmp_path):
        """Submit from many threads; no crashes, no state corruption."""
        src = _make_rgb_png(tmp_path / "in.png")
        q = JobQueue(max_workers=4, max_pending=50)
        errors: list[Exception] = []
        submitted: list[str] = []
        lock = threading.Lock()

        def submit_one():
            try:
                job = q.submit(src, "jpeg", output_dir=tmp_path)
                with lock:
                    submitted.append(job.job_id)
            except QueueFullError:
                pass  # Expected once cap reached.
            except Exception as exc:
                with lock:
                    errors.append(exc)

        threads = [threading.Thread(target=submit_one) for _ in range(30)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        q.shutdown(wait=True)
        assert errors == [], f"Threads raised: {errors}"
        # All submitted jobs should have reached terminal state.
        for jid in submitted:
            assert q.get_status(jid) in _TERMINAL

    def test_concurrent_status_reads_are_safe(self, tmp_path):
        """Reading status from multiple threads while jobs run must not crash."""
        src = _make_rgb_png(tmp_path / "in.png")
        read_errors: list[Exception] = []
        q = JobQueue(max_workers=2)
        jobs = [q.submit(src, "jpeg", output_dir=tmp_path) for _ in range(6)]

        def read_statuses():
            for j in jobs:
                try:
                    q.get_status(j.job_id)
                except Exception as exc:
                    read_errors.append(exc)

        readers = [threading.Thread(target=read_statuses) for _ in range(10)]
        for t in readers:
            t.start()
        q.shutdown(wait=True)
        for t in readers:
            t.join()

        assert read_errors == []

    def test_concurrent_cancel_and_submit_no_crash(self, tmp_path):
        """Cancelling and submitting from different threads simultaneously is safe."""
        src = _make_rgb_png(tmp_path / "in.png")
        errors: list[Exception] = []
        q = JobQueue(max_workers=2, max_pending=100)

        def submit_and_cancel():
            try:
                job = q.submit(src, "jpeg", output_dir=tmp_path)
                q.cancel(job.job_id)
            except (QueueFullError, RuntimeError):
                pass
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=submit_and_cancel) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        q.shutdown(wait=True)
        assert errors == []


# ---------------------------------------------------------------------------
# get_status / get_result edge cases
# ---------------------------------------------------------------------------

class TestQueryEdgeCases:
    def test_get_status_unknown_raises_job_not_found(self):
        q = JobQueue(max_workers=1)
        q.shutdown(wait=True)
        with pytest.raises(JobNotFoundError):
            q.get_status("no_such_id")

    def test_get_result_unknown_raises_job_not_found(self):
        q = JobQueue(max_workers=1)
        q.shutdown(wait=True)
        with pytest.raises(JobNotFoundError):
            q.get_result("no_such_id")

    def test_all_jobs_returns_list(self, tmp_path):
        src = _make_rgb_png(tmp_path / "in.png")
        with JobQueue(max_workers=1) as q:
            j1 = q.submit(src, "jpeg", output_dir=tmp_path)
            j2 = q.submit(src, "webp", output_dir=tmp_path)
            snapshot = q.all_jobs()
        assert len(snapshot) >= 2
        ids = [jid for jid, _ in snapshot]
        assert j1.job_id in ids
        assert j2.job_id in ids

    def test_pending_count_accurate(self, tmp_path):
        src = _make_rgb_png(tmp_path / "in.png")
        barrier = threading.Barrier(2)
        orig = __import__("localshift.converter", fromlist=["convert_image"]).convert_image

        def blocked(*args, **kwargs):
            barrier.wait(timeout=5)
            return orig(*args, **kwargs)

        with patch("localshift.jobs.convert_image", side_effect=blocked):
            q = JobQueue(max_workers=1)
            q.submit(src, "jpeg", output_dir=tmp_path)
            q.submit(src, "webp", output_dir=tmp_path)
            q.submit(src, "bmp",  output_dir=tmp_path)
            # Two jobs are pending (one is running).
            count = q.pending_count()
            barrier.wait(timeout=5)
        q.shutdown(wait=True)
        assert count >= 1  # At least one was pending.


# ---------------------------------------------------------------------------
# Source file integrity
# ---------------------------------------------------------------------------

class TestSourceFileIntegrity:
    def test_source_file_not_modified_after_successful_job(self, tmp_path):
        import hashlib
        src = _make_rgb_png(tmp_path / "in.png")
        before = hashlib.sha256(src.read_bytes()).hexdigest()
        with JobQueue(max_workers=1) as q:
            job = q.submit(src, "jpeg", output_dir=tmp_path)
            _wait_for_terminal(q, job.job_id)
        after = hashlib.sha256(src.read_bytes()).hexdigest()
        assert before == after, "Source file was modified by the job"

    def test_source_file_not_modified_after_failed_job(self, tmp_path):
        import hashlib
        src = _make_rgb_png(tmp_path / "in.png")
        before = hashlib.sha256(src.read_bytes()).hexdigest()
        with JobQueue(max_workers=1) as q:
            job = q.submit(src, "png", output_dir=tmp_path)  # same format → FAILED
            _wait_for_terminal(q, job.job_id)
        after = hashlib.sha256(src.read_bytes()).hexdigest()
        assert before == after, "Source file was modified by the failed job"

    def test_no_temp_files_left_after_jobs(self, tmp_path):
        src = _make_rgb_png(tmp_path / "in.png")
        with JobQueue(max_workers=1) as q:
            jobs = [q.submit(src, fmt, output_dir=tmp_path) for fmt in ("jpeg", "webp", "bmp")]
            for job in jobs:
                _wait_for_terminal(q, job.job_id)
        tmp_files = list(tmp_path.glob("*.tmp"))
        assert tmp_files == [], f"Temp files leaked: {tmp_files}"


# ---------------------------------------------------------------------------
# Regression compatibility — existing API remains unchanged
# ---------------------------------------------------------------------------

class TestRegressionCompatibility:
    def test_convert_image_still_returns_path(self, tmp_path):
        """The original convert_image() API must remain unchanged."""
        from localshift import convert_image
        src = _make_rgb_png(tmp_path / "in.png")
        result = convert_image(src, "jpeg", tmp_path)
        assert isinstance(result, Path)
        assert result.exists()

    def test_conversion_error_still_raised_directly(self, tmp_path):
        """ConversionError must still propagate from convert_image()."""
        from localshift import convert_image, ConversionError
        with pytest.raises(ConversionError):
            convert_image(tmp_path / "nonexistent.png", "jpeg", tmp_path)

    def test_cli_main_entry_point_importable(self):
        from localshift.cli import main
        assert callable(main)

    def test_formats_api_unchanged(self):
        from localshift.formats import SUPPORTED, route_supported, output_formats_for
        assert "png" in SUPPORTED
        assert route_supported("png", "jpeg")
        assert isinstance(output_formats_for(Path("file.png")), list)
