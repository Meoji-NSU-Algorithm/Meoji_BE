"""UploadCleanupScheduler와 run_cleanup_until_empty 테스트. 실제 스레드는 시작하지 않는다."""
from unittest.mock import MagicMock, patch

from app.domains.reviews import scheduler as sched
from app.domains.reviews.scheduler import (
    CLEANUP_INTERVAL_SECONDS,
    MAX_BATCHES_PER_RUN,
    UploadCleanupScheduler,
)


class FakeStop:
    def __init__(self, max_waits=1):
        self.flag, self.waits, self.checks, self.max_waits = False, [], 0, max_waits

    def is_set(self):
        self.checks += 1
        assert self.checks < 50, "무한 루프"
        return self.flag

    def wait(self, seconds):
        self.waits.append(seconds)
        if len(self.waits) >= self.max_waits:
            self.flag = True


def make(max_waits=1):
    s = UploadCleanupScheduler()
    s._stop = FakeStop(max_waits)
    return s


# ---- run_cleanup_until_empty ----
def test_run_cleanup_sums_batches_until_empty():
    with patch.object(sched, "cleanup_unattached_uploads", side_effect=[50, 50, 7, 0]) as cleanup:
        assert sched.run_cleanup_until_empty() == 107
    assert cleanup.call_count == 4


def test_run_cleanup_stops_at_max_batches():
    with patch.object(sched, "cleanup_unattached_uploads", return_value=50) as cleanup:
        assert sched.run_cleanup_until_empty() == 50 * MAX_BATCHES_PER_RUN
    assert cleanup.call_count == MAX_BATCHES_PER_RUN


def test_run_cleanup_returns_zero_when_nothing_to_delete():
    with patch.object(sched, "cleanup_unattached_uploads", return_value=0) as cleanup:
        assert sched.run_cleanup_until_empty() == 0
    assert cleanup.call_count == 1


# ---- start ----
def test_start_creates_one_daemon_thread_only_once():
    s = make()
    with patch.object(sched, "Thread") as thread_cls:
        s.start(MagicMock())
        s.start(MagicMock())
    assert thread_cls.call_count == 1
    assert thread_cls.call_args.kwargs["daemon"] is True
    thread_cls.return_value.start.assert_called_once()


# ---- _run_loop ----
def test_loop_runs_cleanup_inside_app_context_then_waits_interval(app_ctx):
    s = make()
    with patch.object(sched, "run_cleanup_until_empty", return_value=3) as run:
        s._run_loop(app_ctx)
    run.assert_called_once()
    assert s._stop.waits == [CLEANUP_INTERVAL_SECONDS]


def test_loop_survives_exception_and_keeps_waiting(app_ctx):
    s = make(max_waits=2)
    with patch.object(sched, "run_cleanup_until_empty", side_effect=[RuntimeError("boom"), 0]) as run, \
            patch.object(app_ctx.logger, "exception") as log_exception:
        s._run_loop(app_ctx)
    assert run.call_count == 2
    log_exception.assert_called_once()
    assert s._stop.waits == [CLEANUP_INTERVAL_SECONDS] * 2


def test_loop_does_not_run_when_already_stopped(app_ctx):
    s = make()
    s._stop.flag = True
    with patch.object(sched, "run_cleanup_until_empty") as run:
        s._run_loop(app_ctx)
    run.assert_not_called()
    assert s._stop.waits == []


# ---- 지난 조회 기록 정리 (#47) ----
def test_loop_also_cleans_old_user_views(app_ctx):
    s = make()
    with patch.object(sched, "run_cleanup_until_empty", return_value=0), \
            patch.object(sched, "cleanup_old_user_views", return_value=4) as views:
        s._run_loop(app_ctx)
    views.assert_called_once()


def test_view_cleanup_runs_even_if_upload_cleanup_fails(app_ctx):
    s = make()
    with patch.object(sched, "run_cleanup_until_empty", side_effect=RuntimeError("s3")), \
            patch.object(sched, "cleanup_old_user_views", return_value=0) as views, \
            patch.object(app_ctx.logger, "exception") as log_exception:
        s._run_loop(app_ctx)
    views.assert_called_once()
    log_exception.assert_called_once()
    assert s._stop.waits == [CLEANUP_INTERVAL_SECONDS]


def test_upload_cleanup_unaffected_when_view_cleanup_fails(app_ctx):
    s = make(max_waits=2)
    with patch.object(sched, "run_cleanup_until_empty", return_value=0) as run, \
            patch.object(sched, "cleanup_old_user_views", side_effect=RuntimeError("db")), \
            patch.object(app_ctx.logger, "exception") as log_exception:
        s._run_loop(app_ctx)
    assert run.call_count == 2 and log_exception.call_count == 2
    assert s._stop.waits == [CLEANUP_INTERVAL_SECONDS] * 2
