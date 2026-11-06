"""저장소 클라이언트 테스트. 실제 저장소에는 접속하지 않는다."""
import pytest

from app.core.errors import BusinessException, ErrorCode
from app.domains.reviews import storage_client


@pytest.fixture()
def s3_config(app, monkeypatch):
    for key, value in {
        "S3_ENDPOINT": "http://127.0.0.1:1", "S3_REGION": "garage", "S3_BUCKET": "review-images",
        "S3_ACCESS_KEY": "test-access", "S3_SECRET_KEY": "test-secret", "S3_PUBLIC_URL": None,
    }.items():
        monkeypatch.setitem(app.config, key, value)
    monkeypatch.delitem(app.extensions, "review_storage_client", raising=False)
    with app.app_context():
        yield app


def test_client_is_cached_per_app_with_short_timeouts(s3_config):
    """조회마다 클라이언트를 새로 만들지 않고, 타임아웃·재시도를 짧게 둔다."""
    client = storage_client._client()
    assert storage_client._client() is client
    assert client.meta.config.connect_timeout == storage_client.CONNECT_TIMEOUT
    assert client.meta.config.read_timeout == storage_client.READ_TIMEOUT
    assert client.meta.config.retries["total_max_attempts"] == storage_client.MAX_ATTEMPTS


def test_object_url_presigned_without_public_url(s3_config):
    url = storage_client.object_url("reviews/a.webp")
    assert url.startswith("http://127.0.0.1:1/review-images/reviews/a.webp?")
    assert "Signature" in url


def test_object_url_uses_public_url(s3_config, monkeypatch):
    monkeypatch.setitem(s3_config.config, "S3_PUBLIC_URL", "http://img.test/images/")
    assert storage_client.object_url("reviews/a.webp") == "http://img.test/images/reviews/a.webp"


def test_object_url_is_none_without_config(s3_config, monkeypatch):
    monkeypatch.setitem(s3_config.config, "S3_BUCKET", None)
    assert storage_client.object_url("reviews/a.webp") is None


def test_put_object_without_config_is_unavailable(s3_config, monkeypatch):
    monkeypatch.setitem(s3_config.config, "S3_SECRET_KEY", None)
    with pytest.raises(BusinessException) as e:
        storage_client.put_object("reviews/a.webp", b"x", "image/webp")
    assert e.value.error_code == ErrorCode.REVIEW_IMAGE_STORAGE_UNAVAILABLE


def test_delete_objects_failure_is_only_logged(s3_config, monkeypatch):
    monkeypatch.setitem(s3_config.config, "S3_BUCKET", None)
    storage_client.delete_objects(["reviews/a.webp"])  # 예외를 올리지 않는다
