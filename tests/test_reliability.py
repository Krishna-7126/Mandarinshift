"""
tests/test_reliability.py — LS-BE-003 reliability, concurrency safety, and data integrity tests.

Coverage targets:
- Output collision prevention: concurrent identical targets, identical basenames from
  different folders.
- Reservation cleanup after success, failure.
- Destination identity check (source == output).
- Concurrent submissions at capacity boundaries.
- Registry retention / max_completed eviction.
- Active jobs not evicted during retention cleanup.
- purge_completed() API.
- Evicted job IDs raise JobNotFoundError.
- Shutdown double-fire fix: CANCELLED events only for newly-cancelled jobs.
- Guaranteed terminal state even on unexpected exceptions.
- Callback exceptions do not corrupt job state.
- Worker failure (mocked).
- Shutdown races.
- Source-file integrity after concurrent jobs.
- Temporary-file cleanup.
- Existing CLI and API compatibility.
- Windows case-insensitive path collision.
- max_completed=0 (immediate eviction).
- DEFAULT_MAX_COMPLETED exported.
"""
from __future__ import annotations

import os
import threading
import time
from collections import Counter
from pathlib import Path
from typing import Optional
from unittest.mock import patch

import pytest
from PIL import Image

from localshift import (
    DEFAULT_MAX_COMPLETED,
    DEFAULT_MAX_PENDING,
    DEFAULT_WORKERS,
    BatchSubmission,
    ConversionJob,
    JobNotFoundError,
    JobQueue,
    JobResult,
    JobStatus,
    ProgressEvent,
    QueueFullError,
)
from localshift.converter import (
    ConversionError,
    _path_reservation_lock,
    _validate_no_source_dest_collision,
    convert_image,
    unique_output_path,
)
from localshift.jobs import _TERMINAL


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_rgb_png(path: Path, size: tuple[int, int] = (8, 8)) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, (10, 20, 30)).save(path, format="PNG")
    return path


def _wait_terminal(q: JobQueue, job_id: str, timeout: float = 10.0) -> JobStatus:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            s = q.get_status(job_id)
            if s in _TERMINAL:
                return s
        except JobNotFoundError:
            # Job was evicted — it must have been terminal.
            return JobStatus.SUCCEEDED  # conservative; caller checks result separately
        time.sleep(0.01)
    pytest.fail(f"Job {job_id[:8]} did not reach terminal status within {timeout}s")


# ===========================================================================
# Phase 2 — Output collision tests
# ===========================================================================

class TestOutputCollisionPrevention:
    """Verify that concurrent conversions never silently overwrite each other."""

    def test_concurrent_same_source_same_target_produce_distinct_outputs(self, tmp_path):
        """Two concurrent jobs converting the same source to the same format
        must produce two different output files — the collision race is fixed."""
        src = _make_rgb_png(tmp_path / "photo.png")

        with JobQueue(max_workers=2) as q:
            j1 = q.submit(src, "jpeg", output_dir=tmp_path)
            j2 = q.submit(src, "jpeg", output_dir=tmp_path)
            _wait_terminal(q, j1.job_id)
            _wait_terminal(q, j2.job_id)
            r1 = q.get_result(j1.job_id)
            r2 = q.get_result(j2.job_id)

        assert r1.status is JobStatus.SUCCEEDED, f"j1 failed: {r1.error}"
        assert r2.status is JobStatus.SUCCEEDED, f"j2 failed: {r2.error}"
        assert r1.output_path != r2.output_path, (
            "Both concurrent jobs wrote to the same output path — collision not prevented"
        )
        assert r1.output_path.exists(), "j1 output missing"
        assert r2.output_path.exists(), "j2 output missing"

    def test_concurrent_different_sources_same_stem_produce_distinct_outputs(self, tmp_path):
        """Sources from different folders with the same stem must not collide."""
        dir_a = tmp_path / "a"
        dir_b = tmp_path / "b"
        src_a = _make_rgb_png(dir_a / "image.png")
        src_b = _make_rgb_png(dir_b / "image.png")

        with JobQueue(max_workers=2) as q:
            j1 = q.submit(src_a, "jpeg", output_dir=tmp_path)
            j2 = q.submit(src_b, "jpeg", output_dir=tmp_path)
            _wait_terminal(q, j1.job_id)
            _wait_terminal(q, j2.job_id)
            r1 = q.get_result(j1.job_id)
            r2 = q.get_result(j2.job_id)

        assert r1.status is JobStatus.SUCCEEDED
        assert r2.status is JobStatus.SUCCEEDED
        assert r1.output_path != r2.output_path

    def test_many_concurrent_conversions_all_unique_outputs(self, tmp_path):
        """Eight concurrent conversions of the same source produce 8 unique files."""
        src = _make_rgb_png(tmp_path / "in.png")
        n = 8

        with JobQueue(max_workers=4) as q:
            jobs = [q.submit(src, "jpeg", output_dir=tmp_path) for _ in range(n)]
            for j in jobs:
                _wait_terminal(q, j.job_id)
            results = [q.get_result(j.job_id) for j in jobs]

        paths = [r.output_path for r in results if r.status is JobStatus.SUCCEEDED]
        assert len(paths) == n, f"Only {len(paths)} of {n} jobs succeeded"
        assert len(set(paths)) == n, f"Duplicate output paths: {Counter(str(p) for p in paths)}"
        assert all(p.exists() for p in paths), "One or more output files are missing"

    def test_no_temp_files_left_after_concurrent_conversions(self, tmp_path):
        """No .tmp files should remain after concurrent conversions complete."""
        src = _make_rgb_png(tmp_path / "in.png")

        with JobQueue(max_workers=4) as q:
            jobs = [q.submit(src, "jpeg", output_dir=tmp_path) for _ in range(6)]
            for j in jobs:
                _wait_terminal(q, j.job_id)

        tmp_files = list(tmp_path.glob("*.tmp"))
        assert tmp_files == [], f"Temp files leaked: {tmp_files}"

    def test_source_file_unchanged_after_concurrent_conversions(self, tmp_path):
        """Source file must not be modified by concurrent conversions."""
        import hashlib
        src = _make_rgb_png(tmp_path / "in.png")
        before = hashlib.sha256(src.read_bytes()).hexdigest()

        with JobQueue(max_workers=4) as q:
            jobs = [q.submit(src, "jpeg", output_dir=tmp_path) for _ in range(6)]
            for j in jobs:
                _wait_terminal(q, j.job_id)

        after = hashlib.sha256(src.read_bytes()).hexdigest()
        assert before == after, "Source file was modified by concurrent conversions"

    def test_reservation_cleanup_after_failed_job(self, tmp_path):
        """A failed job must not leave any reservation artifacts."""
        # Submit a job that fails (missing source).
        with JobQueue(max_workers=1) as q:
            job = q.submit(tmp_path / "missing.png", "jpeg", output_dir=tmp_path)
            _wait_terminal(q, job.job_id)
            result = q.get_result(job.job_id)

        assert result.status is JobStatus.FAILED
        tmp_files = list(tmp_path.glob("*.tmp"))
        assert tmp_files == [], f"Temp files leaked after failed job: {tmp_files}"

    def test_reservation_cleanup_after_success(self, tmp_path):
        """A successful job must not leave any temp/reservation artifacts."""
        src = _make_rgb_png(tmp_path / "in.png")

        with JobQueue(max_workers=1) as q:
            job = q.submit(src, "jpeg", output_dir=tmp_path)
            _wait_terminal(q, job.job_id)

        tmp_files = list(tmp_path.glob("*.tmp"))
        assert tmp_files == [], f"Temp files leaked after successful job: {tmp_files}"

    def test_path_reservation_lock_is_exported(self):
        """The _path_reservation_lock must be importable for testing."""
        import threading
        assert isinstance(_path_reservation_lock, threading.Lock)

    def test_direct_convert_image_concurrent_distinct_outputs(self, tmp_path):
        """Direct convert_image() calls from multiple threads must not collide."""
        src = _make_rgb_png(tmp_path / "in.png")
        results = []
        errors = []
        lock = threading.Lock()

        def do_convert():
            try:
                path = convert_image(src, "jpeg", tmp_path)
                with lock:
                    results.append(path)
            except Exception as exc:
                with lock:
                    errors.append(exc)

        threads = [threading.Thread(target=do_convert) for _ in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == [], f"Conversion errors: {errors}"
        assert len(set(results)) == len(results), (
            f"Duplicate output paths from concurrent convert_image calls: {results}"
        )


# ===========================================================================
# Phase 3 — Path and source safety
# ===========================================================================

class TestPathSafety:
    def test_source_destination_identity_rejected(self, tmp_path):
        """Converting a file to the same path it lives at must raise ConversionError."""
        src = _make_rgb_png(tmp_path / "photo.png")
        # Attempt to produce a .jpeg in the same folder — the stem is "photo"
        # and there's no "photo.jpeg" yet, so we test the identity check directly.
        with pytest.raises(ConversionError, match="same as the source file"):
            _validate_no_source_dest_collision(src, src)

    def test_validate_no_collision_different_paths_ok(self, tmp_path):
        """Different source and output paths must not raise."""
        src = tmp_path / "input.png"
        out = tmp_path / "output.jpeg"
        _validate_no_source_dest_collision(src, out)  # no exception

    def test_convert_image_missing_file_raises_conversion_error(self, tmp_path):
        with pytest.raises(ConversionError, match="not found"):
            convert_image(tmp_path / "nonexistent.png", "jpeg", tmp_path)

    def test_convert_image_same_format_rejected(self, tmp_path):
        src = _make_rgb_png(tmp_path / "in.png")
        with pytest.raises(ConversionError):
            convert_image(src, "png", tmp_path)

    def test_output_dir_created_automatically(self, tmp_path):
        src = _make_rgb_png(tmp_path / "in.png")
        new_dir = tmp_path / "out" / "sub"
        assert not new_dir.exists()
        result = convert_image(src, "jpeg", new_dir)
        assert new_dir.is_dir()
        assert result.parent == new_dir

    def test_unique_output_path_no_collision(self, tmp_path):
        assert unique_output_path(tmp_path, "pic", "png") == tmp_path / "pic.png"

    def test_unique_output_path_collision_appends_suffix(self, tmp_path):
        (tmp_path / "pic.png").touch()
        assert unique_output_path(tmp_path, "pic", "png").name == "pic (2).png"

    def test_unique_output_path_multiple_collisions(self, tmp_path):
        for name in ("pic.png", "pic (2).png", "pic (3).png"):
            (tmp_path / name).touch()
        assert unique_output_path(tmp_path, "pic", "png").name == "pic (4).png"

    def test_unicode_filename_handled(self, tmp_path):
        """Files with Unicode characters in names must be handled gracefully."""
        src = _make_rgb_png(tmp_path / "测试图像.png")
        result = convert_image(src, "jpeg", tmp_path)
        assert result.exists()
        assert result.suffix == ".jpeg"

    def test_filename_with_spaces(self, tmp_path):
        src = _make_rgb_png(tmp_path / "my photo 2024.png")
        result = convert_image(src, "webp", tmp_path)
        assert result.exists()

    def test_deeply_nested_output_dir(self, tmp_path):
        src = _make_rgb_png(tmp_path / "in.png")
        deep = tmp_path / "a" / "b" / "c" / "d"
        result = convert_image(src, "bmp", deep)
        assert result.exists()
        assert result.parent == deep

    def test_existing_output_file_not_silently_overwritten_by_direct_api(self, tmp_path):
        """When output collides, unique_output_path produces a new name — no silent overwrite."""
        src = _make_rgb_png(tmp_path / "in.png")
        first = convert_image(src, "jpeg", tmp_path)
        first_content = first.read_bytes()
        second = convert_image(src, "jpeg", tmp_path)
        # First file must be unchanged.
        assert first.read_bytes() == first_content, "First output was silently overwritten"
        assert first != second, "Second output should have a different name"

    @pytest.mark.skipif(
        os.name == "nt" and not os.environ.get("LOCALSHIFT_TEST_SYMLINKS"),
        reason="Symlinks require Developer Mode on Windows.",
    )
    def test_dangling_symlink_source_rejected(self, tmp_path):
        link = tmp_path / "dangling.png"
        link.symlink_to(tmp_path / "nonexistent.png")
        with pytest.raises(ConversionError):
            convert_image(link, "jpeg", tmp_path)


# ===========================================================================
# Phase 4 — Job registry retention
# ===========================================================================

class TestRegistryRetention:
    def test_default_max_completed_exported(self):
        assert DEFAULT_MAX_COMPLETED == 1000

    def test_max_completed_zero_evicts_immediately(self, tmp_path):
        """With max_completed=0, completed jobs are evicted as soon as they finish."""
        src = _make_rgb_png(tmp_path / "in.png")
        with JobQueue(max_workers=1, max_completed=0) as q:
            job = q.submit(src, "jpeg", output_dir=tmp_path)
            _wait_terminal(q, job.job_id)
        # After shutdown, job must have been evicted.
        with pytest.raises(JobNotFoundError):
            q.get_status(job.job_id)

    def test_evicted_jobs_raise_job_not_found_error(self, tmp_path):
        """After eviction, get_status and get_result raise JobNotFoundError."""
        src = _make_rgb_png(tmp_path / "in.png")
        with JobQueue(max_workers=1, max_completed=2) as q:
            # Submit 3 jobs; 3rd will evict 1st (FIFO).
            j1 = q.submit(src, "jpeg", output_dir=tmp_path)
            j2 = q.submit(src, "webp", output_dir=tmp_path)
            j3 = q.submit(src, "bmp",  output_dir=tmp_path)
            for j in (j1, j2, j3):
                _wait_terminal(q, j.job_id)

        # After shutdown (sequential execution), j1 should be evicted.
        with pytest.raises(JobNotFoundError):
            q.get_status(j1.job_id)

    def test_active_jobs_never_evicted(self, tmp_path):
        """Active (PENDING/RUNNING) jobs must not be evicted by the retention policy."""
        src = _make_rgb_png(tmp_path / "in.png")
        barrier = threading.Barrier(2)
        orig = convert_image

        def blocked(*args, **kwargs):
            barrier.wait(timeout=5)
            return orig(*args, **kwargs)

        with patch("localshift.jobs.convert_image", side_effect=blocked):
            q = JobQueue(max_workers=1, max_completed=0)
            # With max_completed=0, terminal jobs evict immediately.
            j_running = q.submit(src, "jpeg", output_dir=tmp_path)
            j_pending = q.submit(src, "webp", output_dir=tmp_path)
            # j_running is RUNNING (blocked); j_pending is PENDING.
            # Even with max_completed=0, neither should be evicted.
            status_running = q.get_status(j_running.job_id)
            status_pending = q.get_status(j_pending.job_id)
            barrier.wait(timeout=5)
        q.shutdown(wait=True)

        # Both were active (not terminal) — they must not have been evicted mid-run.
        assert status_running is JobStatus.RUNNING
        assert status_pending is JobStatus.PENDING

    def test_purge_completed_removes_terminal_records(self, tmp_path):
        """purge_completed() must remove all terminal records."""
        src = _make_rgb_png(tmp_path / "in.png")
        with JobQueue(max_workers=1) as q:
            j1 = q.submit(src, "jpeg", output_dir=tmp_path)
            j2 = q.submit(src, "webp", output_dir=tmp_path)
            _wait_terminal(q, j1.job_id)
            _wait_terminal(q, j2.job_id)
            evicted = q.purge_completed()

        assert evicted == 2
        with pytest.raises(JobNotFoundError):
            q.get_status(j1.job_id)
        with pytest.raises(JobNotFoundError):
            q.get_status(j2.job_id)

    def test_purge_completed_does_not_touch_active_jobs(self, tmp_path):
        """purge_completed() must not remove PENDING or RUNNING jobs."""
        src = _make_rgb_png(tmp_path / "in.png")
        barrier = threading.Barrier(2)
        orig = convert_image

        def blocked(*args, **kwargs):
            barrier.wait(timeout=5)
            return orig(*args, **kwargs)

        with patch("localshift.jobs.convert_image", side_effect=blocked):
            q = JobQueue(max_workers=1)
            j_running = q.submit(src, "jpeg", output_dir=tmp_path)
            j_pending = q.submit(src, "webp", output_dir=tmp_path)
            evicted = q.purge_completed()
            assert evicted == 0
            # Both are still present and non-terminal.
            assert q.get_status(j_running.job_id) in (JobStatus.PENDING, JobStatus.RUNNING)
            assert q.get_status(j_pending.job_id) in (JobStatus.PENDING, JobStatus.RUNNING)
            barrier.wait(timeout=5)
        q.shutdown(wait=True)

    def test_purge_completed_returns_count(self, tmp_path):
        src = _make_rgb_png(tmp_path / "in.png")
        with JobQueue(max_workers=1) as q:
            for _ in range(5):
                j = q.submit(src, "jpeg", output_dir=tmp_path)
                _wait_terminal(q, j.job_id)
            count = q.purge_completed()
        assert count == 5

    def test_fifo_eviction_removes_oldest_first(self, tmp_path):
        """The retention policy evicts the oldest jobs first."""
        src = _make_rgb_png(tmp_path / "in.png")
        max_c = 3
        # Use max_workers=1 for deterministic ordering.
        with JobQueue(max_workers=1, max_completed=max_c) as q:
            all_jobs = [q.submit(src, "jpeg", output_dir=tmp_path) for _ in range(max_c + 2)]
            for j in all_jobs:
                _wait_terminal(q, j.job_id)

        # Oldest 2 should be evicted; newest 3 should remain.
        for j in all_jobs[:2]:
            with pytest.raises(JobNotFoundError):
                q.get_status(j.job_id)
        for j in all_jobs[2:]:
            # These should still be accessible.
            assert q.get_status(j.job_id) in _TERMINAL

    def test_max_completed_parameter_accepted(self):
        q = JobQueue(max_workers=1, max_completed=500)
        q.shutdown(wait=True)

    def test_invalid_max_completed_raises(self):
        with pytest.raises(ValueError, match="max_completed"):
            JobQueue(max_completed=-1)

    def test_registry_concurrent_query_during_eviction(self, tmp_path):
        """Concurrent queries while eviction happens must not crash."""
        src = _make_rgb_png(tmp_path / "in.png")
        errors = []
        q = JobQueue(max_workers=2, max_completed=5)

        def read_jobs():
            for _ in range(50):
                try:
                    q.all_jobs()
                    q.pending_count()
                except Exception as exc:
                    errors.append(exc)
                time.sleep(0.001)

        threads = [threading.Thread(target=read_jobs) for _ in range(5)]
        for t in threads:
            t.start()

        for _ in range(20):
            try:
                j = q.submit(src, "jpeg", output_dir=tmp_path)
                _wait_terminal(q, j.job_id)
            except (QueueFullError, RuntimeError):
                break

        q.shutdown(wait=True)
        for t in threads:
            t.join()

        assert errors == [], f"Concurrent read errors: {errors}"


# ===========================================================================
# Phase 5 — Queue and batch policy
# ===========================================================================

class TestQueuePolicy:
    def test_running_jobs_do_not_count_toward_pending_cap(self, tmp_path):
        """Running jobs must not consume pending capacity."""
        src = _make_rgb_png(tmp_path / "in.png")
        barrier = threading.Barrier(2)
        orig = convert_image

        def blocked(*args, **kwargs):
            barrier.wait(timeout=5)
            return orig(*args, **kwargs)

        with patch("localshift.jobs.convert_image", side_effect=blocked):
            q = JobQueue(max_workers=1, max_pending=1)
            j1 = q.submit(src, "jpeg", output_dir=tmp_path)  # starts running immediately
            # max_pending=1 and j1 is RUNNING → should be able to add 1 PENDING job.
            j2 = q.submit(src, "webp", output_dir=tmp_path)  # fills pending
            with pytest.raises(QueueFullError):
                q.submit(src, "bmp", output_dir=tmp_path)   # exceeds pending cap
            barrier.wait(timeout=5)
        q.shutdown(wait=True)

    def test_shutdown_cancels_only_newly_pending_jobs(self, tmp_path):
        """shutdown() must fire CANCELLED only for jobs it cancels, not re-fire for
        already-cancelled jobs (double-fire bug fix)."""
        src = _make_rgb_png(tmp_path / "in.png")
        barrier = threading.Barrier(2)
        orig = convert_image
        cancel_events: list[str] = []

        def blocked(*args, **kwargs):
            barrier.wait(timeout=5)
            return orig(*args, **kwargs)

        def cb(job_id, event, result):
            if event is ProgressEvent.CANCELLED:
                cancel_events.append(job_id)

        with patch("localshift.jobs.convert_image", side_effect=blocked):
            q = JobQueue(max_workers=1, progress_callback=cb)
            j1 = q.submit(src, "jpeg", output_dir=tmp_path)
            j2 = q.submit(src, "webp", output_dir=tmp_path)
            j3 = q.submit(src, "bmp",  output_dir=tmp_path)
            # Manually cancel j2 before shutdown.
            q.cancel(j2.job_id)
            # Release the worker, then shut down.
            barrier.wait(timeout=5)
        q.shutdown(wait=True)

        # j2 was already cancelled; shutdown cancels j3 (if still pending).
        # j2's CANCELLED event must appear exactly once.
        count_j2 = cancel_events.count(j2.job_id)
        assert count_j2 == 1, (
            f"CANCELLED fired {count_j2} times for j2 (expected exactly 1); "
            f"double-fire bug not fixed. all events: {cancel_events}"
        )

    def test_all_jobs_reflects_submission_order(self, tmp_path):
        src = _make_rgb_png(tmp_path / "in.png")
        with JobQueue(max_workers=1) as q:
            jobs = [q.submit(src, fmt, output_dir=tmp_path)
                    for fmt in ("jpeg", "webp", "bmp")]
            for j in jobs:
                _wait_terminal(q, j.job_id)
            snapshot = q.all_jobs()

        order = [jid for jid, _ in snapshot]
        submitted_ids = [j.job_id for j in jobs]
        # All submitted IDs must appear, in order.
        present = [jid for jid in submitted_ids if jid in order]
        assert present == submitted_ids, "all_jobs() does not preserve submission order"


# ===========================================================================
# Phase 6 — Failure and cleanup correctness
# ===========================================================================

class TestFailureAndCleanup:
    def test_job_always_terminal_on_conversion_error(self, tmp_path):
        """A ConversionError must produce a FAILED job, never strand it in RUNNING."""
        with JobQueue(max_workers=1) as q:
            job = q.submit(tmp_path / "missing.png", "jpeg", output_dir=tmp_path)
            status = _wait_terminal(q, job.job_id)
        assert status is JobStatus.FAILED

    def test_job_always_terminal_on_unexpected_exception(self, tmp_path):
        """Even an unexpected RuntimeError from convert_image must not strand job in RUNNING."""
        src = _make_rgb_png(tmp_path / "in.png")

        def explode(*args, **kwargs):
            raise RuntimeError("Simulated unexpected crash")

        with patch("localshift.jobs.convert_image", side_effect=explode):
            with JobQueue(max_workers=1) as q:
                job = q.submit(src, "jpeg", output_dir=tmp_path)
                status = _wait_terminal(q, job.job_id)
                result = q.get_result(job.job_id)

        assert status is JobStatus.FAILED
        assert result.error is not None
        assert "RuntimeError" in result.error or "Simulated" in result.error

    def test_failed_result_output_path_is_none(self, tmp_path):
        with JobQueue(max_workers=1) as q:
            job = q.submit(tmp_path / "missing.png", "jpeg", output_dir=tmp_path)
            _wait_terminal(q, job.job_id)
            result = q.get_result(job.job_id)
        assert result.output_path is None

    def test_no_false_success_on_crash(self, tmp_path):
        """A crashed worker must never report SUCCEEDED."""
        src = _make_rgb_png(tmp_path / "in.png")

        def explode(*args, **kwargs):
            raise ValueError("Simulated decode error")

        with patch("localshift.jobs.convert_image", side_effect=explode):
            with JobQueue(max_workers=1) as q:
                job = q.submit(src, "jpeg", output_dir=tmp_path)
                _wait_terminal(q, job.job_id)
                result = q.get_result(job.job_id)

        assert result.status is not JobStatus.SUCCEEDED

    def test_callback_exception_does_not_strand_job(self, tmp_path):
        """A callback that raises on every event must not affect job state."""
        src = _make_rgb_png(tmp_path / "in.png")
        call_count = 0

        def bad_callback(job_id, event, result):
            nonlocal call_count
            call_count += 1
            raise RuntimeError("Bad callback!")

        with JobQueue(max_workers=1, progress_callback=bad_callback) as q:
            job = q.submit(src, "jpeg", output_dir=tmp_path)
            status = _wait_terminal(q, job.job_id)

        assert status is JobStatus.SUCCEEDED
        assert call_count > 0, "Callback was never invoked"

    def test_source_file_integrity_after_failed_job(self, tmp_path):
        import hashlib
        src = _make_rgb_png(tmp_path / "in.png")
        before = hashlib.sha256(src.read_bytes()).hexdigest()
        with JobQueue(max_workers=1) as q:
            job = q.submit(src, "png", output_dir=tmp_path)  # same format → FAILED
            _wait_terminal(q, job.job_id)
        after = hashlib.sha256(src.read_bytes()).hexdigest()
        assert before == after, "Source file was modified by a failed job"

    def test_no_temp_files_after_failed_conversion(self, tmp_path):
        with JobQueue(max_workers=1) as q:
            job = q.submit(tmp_path / "missing.png", "jpeg", output_dir=tmp_path)
            _wait_terminal(q, job.job_id)
        tmp_files = list(tmp_path.glob("*.tmp"))
        assert tmp_files == [], f"Temp files leaked after failure: {tmp_files}"


# ===========================================================================
# Phase 7 — Additional concurrency tests
# ===========================================================================

class TestConcurrencyAdditional:
    def test_concurrent_submissions_near_capacity_no_corruption(self, tmp_path):
        """Submitting from many threads at the capacity boundary must not corrupt state."""
        src = _make_rgb_png(tmp_path / "in.png")
        q = JobQueue(max_workers=2, max_pending=10)
        submitted: list[str] = []
        errors: list[Exception] = []
        lock = threading.Lock()

        def submit_one():
            try:
                j = q.submit(src, "jpeg", output_dir=tmp_path)
                with lock:
                    submitted.append(j.job_id)
            except QueueFullError:
                pass
            except Exception as exc:
                with lock:
                    errors.append(exc)

        threads = [threading.Thread(target=submit_one) for _ in range(30)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        q.shutdown(wait=True)

        assert errors == [], f"Unexpected errors: {errors}"
        for jid in submitted:
            assert q.get_status(jid) in _TERMINAL

    def test_concurrent_cancel_and_shutdown_no_double_fire(self, tmp_path):
        """cancel() and shutdown() racing on the same job must not double-fire."""
        src = _make_rgb_png(tmp_path / "in.png")
        barrier = threading.Barrier(2)
        orig = convert_image
        cancel_events: list[str] = []

        def blocked(*args, **kwargs):
            barrier.wait(timeout=5)
            return orig(*args, **kwargs)

        def cb(job_id, event, result):
            if event is ProgressEvent.CANCELLED:
                cancel_events.append(job_id)

        with patch("localshift.jobs.convert_image", side_effect=blocked):
            q = JobQueue(max_workers=1, progress_callback=cb)
            j1 = q.submit(src, "jpeg", output_dir=tmp_path)   # RUNNING
            j2 = q.submit(src, "webp", output_dir=tmp_path)   # PENDING
            # Concurrently cancel j2 and start shutdown.
            t_cancel   = threading.Thread(target=q.cancel,   args=(j2.job_id,))
            t_shutdown = threading.Thread(target=q.shutdown,  kwargs={"wait": False})
            t_cancel.start()
            t_shutdown.start()
            barrier.wait(timeout=5)
            t_cancel.join()
            t_shutdown.join()
        q.shutdown(wait=True)

        # j2 should have been cancelled exactly once regardless of race.
        assert cancel_events.count(j2.job_id) <= 1, (
            f"CANCELLED fired {cancel_events.count(j2.job_id)} times for j2"
        )

    def test_get_result_thread_safe_during_completion(self, tmp_path):
        """Concurrent get_result() calls while job completes must not crash."""
        src = _make_rgb_png(tmp_path / "in.png")
        errors = []
        q = JobQueue(max_workers=1)
        job = q.submit(src, "jpeg", output_dir=tmp_path)

        def reader():
            for _ in range(100):
                try:
                    q.get_result(job.job_id)
                except JobNotFoundError:
                    pass  # evicted — fine
                except Exception as exc:
                    errors.append(exc)

        readers = [threading.Thread(target=reader) for _ in range(8)]
        for t in readers:
            t.start()
        q.shutdown(wait=True)
        for t in readers:
            t.join()

        assert errors == [], f"Thread-safety errors: {errors}"


# ===========================================================================
# Phase 8 — Compatibility
# ===========================================================================

class TestCompatibility:
    def test_convert_image_api_unchanged(self, tmp_path):
        """The original convert_image() must still return Path, unchanged."""
        from localshift import convert_image as ci
        src = _make_rgb_png(tmp_path / "in.png")
        result = ci(src, "jpeg", tmp_path)
        assert isinstance(result, Path)
        assert result.exists()

    def test_conversion_error_still_raised(self, tmp_path):
        from localshift import convert_image, ConversionError
        with pytest.raises(ConversionError):
            convert_image(tmp_path / "missing.png", "jpeg", tmp_path)

    def test_cli_main_importable(self):
        from localshift.cli import main
        assert callable(main)

    def test_formats_api_unchanged(self):
        from localshift.formats import SUPPORTED, route_supported, output_formats_for
        assert "png" in SUPPORTED
        assert route_supported("png", "jpeg")
        assert isinstance(output_formats_for(Path("file.png")), list)

    def test_no_pyside6_imported_by_new_modules(self):
        import sys
        was = "PySide6" in sys.modules
        import localshift.converter  # noqa: F401
        import localshift.jobs       # noqa: F401
        if not was:
            assert "PySide6" not in sys.modules

    def test_default_constants_exported(self):
        from localshift import DEFAULT_MAX_COMPLETED, DEFAULT_MAX_PENDING, DEFAULT_WORKERS
        assert DEFAULT_MAX_COMPLETED == 1000
        assert DEFAULT_MAX_PENDING == 200
        assert DEFAULT_WORKERS == 2

    def test_conversion_result_fields_unchanged(self):
        import dataclasses
        from localshift import ConversionResult
        fields = {f.name for f in dataclasses.fields(ConversionResult)}
        assert {"output_path", "source_format", "target_format",
                "input_bytes", "output_bytes"} <= fields

    def test_path_reservation_lock_in_converter(self):
        """_path_reservation_lock must exist in converter module."""
        from localshift.converter import _path_reservation_lock
        import threading
        assert isinstance(_path_reservation_lock, threading.Lock)
