"""KopisSyncScheduler 테스트. 실제 스레드는 시작하지 않는다."""
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from app.domains.kopis import scheduler as sched
from app.domains.kopis.scheduler import RETRY_INTERVAL, STATE_ID, SYNC_INTERVAL, KopisSyncScheduler
from app.domains.tour.state_service import last_success_at, record_success

OK = {"saved": 1, "updated": 0, "skipped": 0, "duplicates": [], "failures": [], "complete": True}


def service(report):
    cls = MagicMock()
    cls.return_value.sync_performances.return_value = report
    return cls


def test_start_skipped_without_key():
    app = MagicMock()
    app.config = {"KOPIS_API_KEY": None}
    with patch.object(sched, "Thread") as thread:
        KopisSyncScheduler().start(app)
    thread.assert_not_called()


def test_start_only_once_with_key():
    app = MagicMock()
    app.config = {"KOPIS_API_KEY": "k"}
    s = KopisSyncScheduler()
    with patch.object(sched, "Thread") as thread:
        s.start(app)
        s.start(app)
    thread.assert_called_once()


def test_runs_and_records_separately_from_tourapi(seeded):
    with patch.object(sched, "KopisSyncService", service(OK)):
        wait = KopisSyncScheduler().run_once(seeded)
    assert wait == SYNC_INTERVAL.total_seconds()
    assert abs((last_success_at(STATE_ID) - datetime.now(timezone.utc).replace(tzinfo=None)).total_seconds()) < 60
    assert last_success_at() is None  # TourAPI(id=1) 행은 그대로


def test_waits_until_due(seeded):
    record_success(STATE_ID)
    cls = service(OK)
    with patch.object(sched, "KopisSyncService", cls):
        wait = KopisSyncScheduler().run_once(seeded)
    cls.assert_not_called()
    # DATETIME은 초 단위로 반올림 저장되어 최대 1초 늦게 기록될 수 있다.
    assert SYNC_INTERVAL.total_seconds() - 120 < wait <= SYNC_INTERVAL.total_seconds() + 1


def test_incomplete_retries_sooner_without_record(seeded, caplog):
    with caplog.at_level("ERROR"), patch.object(sched, "KopisSyncService", service({**OK, "failures": [{}], "complete": False})):
        wait = KopisSyncScheduler().run_once(seeded)
    assert wait == RETRY_INTERVAL.total_seconds() and last_success_at(STATE_ID) is None
    assert "KOPIS_SYNC_INCOMPLETE" in caplog.text
