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
