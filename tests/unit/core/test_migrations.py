"""마이그레이션 이력 검사. DB에 접속하지 않고 스크립트 파일만 읽는다."""
import pathlib

from alembic.config import Config as AlembicConfig
from alembic.script import ScriptDirectory

ROOT = pathlib.Path(__file__).resolve().parents[3]


def _script_directory() -> ScriptDirectory:
    config = AlembicConfig(str(ROOT / "migrations" / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    return ScriptDirectory.from_config(config)


def test_migrations_have_single_head():
    """head가 둘 이상이면 flask db upgrade가 실패하므로 하나여야 한다."""
    assert len(_script_directory().get_heads()) == 1


def test_every_revision_is_reachable_from_head():
    """어떤 마이그레이션도 이력에서 끊겨 있지 않아야 한다."""
    script = _script_directory()
    all_revisions = {revision.revision for revision in script.walk_revisions()}
    reachable = {revision.revision for revision in script.walk_revisions("base", script.get_current_head())}
    assert all_revisions == reachable


def test_merge_migration_joins_image_and_consent_branches():
    """merge 마이그레이션이 head이고 리뷰 이미지/약관 동의 두 갈래를 합친다."""
    script = _script_directory()
    assert script.get_current_head() == "e5460f15d1f5"
    assert set(script.get_revision("e5460f15d1f5").down_revision) == {"d5b81f3a6c27", "c5e8a2f7b140"}
    assert script.get_revision("c5e8a2f7b140").down_revision == "a7c3e1d94b52"


def test_consent_migration_matches_models():
    """마이그레이션이 모델의 새 컬럼과 FK 제약 이름을 모두 다룬다."""
    path = next((ROOT / "migrations" / "versions").glob("c5e8a2f7b140_*.py"))
    source = path.read_text(encoding="utf-8")
    for column in ("terms_agreed_at", "privacy_agreed_at", "marketing_agreed", "marketing_agreed_at"):
        assert f"'{column}'" in source
    assert "ondelete='CASCADE'" in source
    # 끊을 제약 이름이 이전 마이그레이션에서 실제로 만든 이름과 같아야 downgrade/upgrade가 동작한다.
    original = next((ROOT / "migrations" / "versions").glob("82d4628d9b03_*.py")).read_text(encoding="utf-8")
    assert "fk_review_user_id" in original
