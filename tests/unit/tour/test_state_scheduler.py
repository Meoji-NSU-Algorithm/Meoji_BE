"""state_service와 FestivalSyncScheduler 루프 테스트. 실제 스레드는 시작하지 않는다."""
import logging
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.core.errors import BusinessException, ErrorCode
from app.core.extensions import db
from app.domains.tour import scheduler as sched
from app.domains.tour.models import TourSyncState
from app.domains.tour.scheduler import SYNC_INTERVAL, FestivalSyncScheduler
from app.domains.tour.state_service import last_success_at, record_success


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def set_state(value):
    state = db.session.get(TourSyncState, 1)
    state.last_success_at = value
    db.session.commit()
    db.session.remove()


# ---- state_service ----
def test_last_success_initially_none(seeded):
    assert last_success_at() is None


def test_last_success_none_when_row_missing(app_ctx):
    assert last_success_at() is None


def test_record_success_updates_row_and_returns_utc(seeded):
    before = utcnow()
    result = record_success()
    after = utcnow()
    assert result.tzinfo is None and before <= result <= after
    stored = last_success_at()
    assert abs((stored - result).total_seconds()) <= 1
    # KST(+9h)가 아니라 UTC로 저장된다.
    assert abs((stored - utcnow()).total_seconds()) < 60


def test_record_success_creates_missing_row(app_ctx):
    result = record_success()
    assert db.session.get(TourSyncState, 1) is not None
    assert abs((last_success_at() - result).total_seconds()) <= 1


def test_record_success_twice_keeps_single_row(seeded):
    record_success()
    record_success()
    assert db.session.query(TourSyncState).count() == 1


# ---- scheduler ----
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
    s = FestivalSyncScheduler()
    s._stop = FakeStop(max_waits)
    return s


def fake_service(reports):
    svc = MagicMock()
    svc.sync_festivals.side_effect = reports
    return MagicMock(return_value=svc), svc


def ok_report(): return {"saved": 2, "failures": [], "complete": True}
def bad_report(): return {"saved": 1, "failures": [{"code": "X"}], "complete": False}


def test_no_record_syncs_immediately_then_waits_12h(seeded):
    s = make()
    cls, svc = fake_service([ok_report()])
    with patch.object(sched, "TourSyncService", cls):
        s._run_loop(seeded)
    assert svc.sync_festivals.call_count == 1
    assert last_success_at() is not None
    (wait,) = s._stop.waits
    # MySQL DATETIME 은 소수 초를 반올림해 저장하므로 최대 0.5초 늦게 읽힐 수 있다.
    assert 12 * 3600 - 5 < wait <= 12 * 3600 + 1


def test_recent_success_waits_remaining_time_without_sync(seeded):
    set_state(utcnow() - timedelta(hours=1))
    s = make()
    cls, svc = fake_service([])
    with patch.object(sched, "TourSyncService", cls):
        s._run_loop(seeded)
    svc.sync_festivals.assert_not_called()
    # MySQL DATETIME 은 소수 초를 반올림해 저장하므로 최대 0.5초 늦게 읽힐 수 있다.
    assert 11 * 3600 - 5 < s._stop.waits[0] <= 11 * 3600 + 1


def test_overdue_success_syncs_now(seeded):
    set_state(utcnow() - timedelta(hours=12, minutes=1))
    s = make()
    cls, svc = fake_service([ok_report()])
    with patch.object(sched, "TourSyncService", cls):
        s._run_loop(seeded)
    assert svc.sync_festivals.call_count == 1


def test_exactly_due_boundary_syncs(seeded):
    set_state(utcnow() - SYNC_INTERVAL - timedelta(seconds=1))
    s = make()
    cls, svc = fake_service([ok_report()])
    with patch.object(sched, "TourSyncService", cls):
        s._run_loop(seeded)
    assert svc.sync_festivals.call_count == 1


def test_incomplete_does_not_record_and_retries_after_interval_without_db(seeded):
    s = make()
    cls, svc = fake_service([bad_report()])
    with patch.object(sched, "TourSyncService", cls), \
            patch.object(sched, "last_success_at", wraps=sched.last_success_at) as lsa, \
            patch.object(sched, "record_success") as rec:
        s._run_loop(seeded)
    rec.assert_not_called()
    assert svc.sync_festivals.call_count == 1
    assert lsa.call_count == 1  # 재시도 대기 중에는 DB를 다시 읽지 않는다.
    assert last_success_at() is None
    (wait,) = s._stop.waits
    # MySQL DATETIME 은 소수 초를 반올림해 저장하므로 최대 0.5초 늦게 읽힐 수 있다.
    assert 12 * 3600 - 5 < wait <= 12 * 3600 + 1


def test_incomplete_then_retry_after_wait_succeeds(seeded):
    s = make(max_waits=2)
    cls, svc = fake_service([bad_report(), ok_report()])
    real_now = sched.datetime
    # 첫 wait에서 시간이 12시간 흐른 것처럼 만든다.
    shift = {"on": False}
    orig_wait = s._stop.wait

    def wait(seconds):
        orig_wait(seconds)
        shift["on"] = True
        s._stop.flag = len(s._stop.waits) >= 2

    s._stop.wait = wait

    class Clock(real_now):
        @classmethod
        def now(cls, tz=None):
            base = real_now.now(tz)
            return base + SYNC_INTERVAL + timedelta(seconds=1) if shift["on"] else base

    def stop_after_record():
        s._stop.flag = True

    with patch.object(sched, "TourSyncService", cls), patch.object(sched, "datetime", Clock), \
            patch.object(sched, "record_success", side_effect=stop_after_record) as rec:
        s._run_loop(seeded)
    assert svc.sync_festivals.call_count == 2
    rec.assert_called_once()


def test_business_exception_sets_retry_and_loop_continues(seeded, caplog):
    s = make()
    cls, svc = fake_service([BusinessException(ErrorCode.TOUR_API_KEY_MISSING)])
    with patch.object(sched, "TourSyncService", cls):
        s._run_loop(seeded)
    assert svc.sync_festivals.call_count == 1
    assert 12 * 3600 - 5 < s._stop.waits[0] <= 12 * 3600


def test_unexpected_exception_does_not_kill_loop(seeded):
    s = make()
    cls, svc = fake_service([RuntimeError("boom")])
    with patch.object(sched, "TourSyncService", cls):
        s._run_loop(seeded)
    assert s._stop.waits and s._stop.waits[0] > 12 * 3600 - 5


def test_record_success_failure_triggers_retry_wait(seeded):
    s = make()
    cls, svc = fake_service([ok_report()])
    with patch.object(sched, "TourSyncService", cls), patch.object(sched, "record_success", side_effect=RuntimeError("db")):
        s._run_loop(seeded)
    assert svc.sync_festivals.call_count == 1 and s._stop.waits


def test_stop_set_before_start_exits_immediately(seeded):
    s = make()
    s._stop.flag = True
    cls, svc = fake_service([])
    with patch.object(sched, "TourSyncService", cls):
        s._run_loop(seeded)
    svc.sync_festivals.assert_not_called()


def test_last_success_in_future_waits_long(seeded):
    set_state(utcnow() + timedelta(hours=5))
    s = make()
    cls, svc = fake_service([])
    with patch.object(sched, "TourSyncService", cls):
        s._run_loop(seeded)
    svc.sync_festivals.assert_not_called()
    assert 17 * 3600 - 5 < s._stop.waits[0] <= 17 * 3600 + 2


def test_start_is_idempotent_and_daemon():
    s = FestivalSyncScheduler()
    with patch.object(sched, "Thread") as thread:
        s.start(object())
        s.start(object())
    assert thread.call_count == 1
    assert thread.call_args.kwargs["daemon"] is True
    thread.return_value.start.assert_called_once()


def test_interval_constant():
    assert SYNC_INTERVAL == timedelta(hours=12)
