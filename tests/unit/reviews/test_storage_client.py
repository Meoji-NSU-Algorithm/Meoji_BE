"""storage_client: 저장소 설정 판단과 삭제 실패 처리."""
import pytest

from app.core.errors import BusinessException, ErrorCode
from app.domains.reviews import storage_client


@pytest.fixture()
def s3_config(app_ctx, monkeypatch):
    config = app_ctx.config
    values = {"S3_ENDPOINT": "http://s3.test", "S3_BUCKET": "b", "S3_ACCESS_KEY": "k", "S3_SECRET_KEY": "s", "S3_PUBLIC_URL": None}
    for name, value in values.items():
        monkeypatch.setitem(config, name, value)
    monkeypatch.delitem(app_ctx.extensions, "review_storage_client", raising=False)
    return config


@pytest.mark.parametrize("name", ["S3_ENDPOINT", "S3_ACCESS_KEY"])
def test_placeholder_values_mean_not_configured(s3_config, monkeypatch, name):
    """.env.example 값이 남아 있으면 미설정으로 본다: 조회 url은 None, 저장은 503(500 아님)."""
    monkeypatch.setitem(s3_config, name, "NEED_TO_SET")
    assert storage_client.object_url("reviews/a.webp") is None
    with pytest.raises(BusinessException) as e:
        storage_client.put_object("reviews/a.webp", b"x", "image/webp")
    assert e.value.error_code == ErrorCode.REVIEW_IMAGE_STORAGE_UNAVAILABLE


def test_delete_failure_is_only_logged(s3_config, monkeypatch):
    """커밋 뒤 정리(탈퇴·리뷰 삭제)는 저장소가 어떤 오류를 내도 예외를 올리지 않는다."""
    def down():
        raise RuntimeError("storage down")

    monkeypatch.setattr(storage_client, "_client", down)
    storage_client.delete_objects(["reviews/a.webp"])
