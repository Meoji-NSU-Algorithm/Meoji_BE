"""SyncScheduler의 stop()/join() 테스트. DB·외부 API 없이 실제 스레드를 잠깐 띄운다."""
from unittest.mock import MagicMock

from app.domains.tour.scheduler import SyncScheduler


class FakeScheduler(SyncScheduler):
    """설정 키 없이 시작되고, run_once는 곧바로 큰 대기 초를 반환하는 테스트용 스케줄러."""

    name = "fake-scheduler"
    state_id = 99
    config_key = None

    def run_once(self, app):
        return 3600


def test_stop_then_join_ends_thread():
    app = MagicMock()
    scheduler = FakeScheduler()
    scheduler.start(app)
    assert scheduler._thread.is_alive()

    scheduler.stop()
    scheduler.join(timeout=5)

    # 큰 대기 중이어도 stop()이 대기를 깨워 스레드가 끝난다.
    assert not scheduler._thread.is_alive()


def test_join_without_start_returns_immediately():
    scheduler = FakeScheduler()
    scheduler.join(timeout=5)  # 예외 없이 바로 반환
    assert scheduler._thread is None
