"""이미 저장된 행사의 태그를 현재 사전(tag_terms)으로 다시 계산한다.

태그 규칙(tag_terms.TAG_TERMS)을 고치면 새로 수집하는 행사부터 새 규칙이 적용되므로,
DB에 이미 있는 행사는 이 명령으로 한 번 다시 계산해야 한다.

    flask --app wsgi retag-events                     # 바뀔 내용만 보여 준다(저장하지 않음)
    flask --app wsgi retag-events --apply --backup b.json   # 저장하고, 이전 태그를 b.json에 남긴다

KOPIS 공연은 수집할 때 태그를 붙이지 않으므로 대상이 아니다.
"""

import json

import click
from flask.cli import with_appcontext
from sqlalchemy import select

from app.core.errors import BusinessException, ErrorCode
from app.core.extensions import db
from app.domains.events.models import Event, Tag
from app.domains.kopis.sync_service import ID_PREFIX
from app.domains.tour.tag_terms import match_tags


def retag_events(session, apply=False):
    """KOPIS 외 행사의 태그를 사전 규칙으로 다시 계산해 바뀐 행사 목록을 돌려준다.

    apply=False면 저장하지 않는다. 각 항목은 {id, title, old, new}(태그 이름 목록)이다.

    Raises:
        BusinessException: 사전의 태그가 tags 테이블에 없으면 TOUR_SYNC_SEED_MISSING.
    """
    tags = {tag.name: tag for tag in session.scalars(select(Tag))}
    changes = []

    events = session.scalars(select(Event).where(~Event.tour_content_id.startswith(ID_PREFIX)))
    for event in events:
        old = sorted(tag.name for tag in event.tags)
        new = sorted(match_tags(event.title, event.description))
        if old == new:
            continue

        changes.append({"id": event.id, "title": event.title, "old": old, "new": new})
        if apply:
            missing = [name for name in new if name not in tags]
            if missing:
                raise BusinessException(ErrorCode.TOUR_SYNC_SEED_MISSING, extra={"tags": missing})
            event.tags = [tags[name] for name in new]

    return changes


@click.command("retag-events")
@click.option("--apply", is_flag=True, help="저장한다. 없으면 바뀔 내용만 보여 준다.")
@click.option("--backup", type=click.Path(dir_okay=False), help="--apply와 함께 쓰면 바뀌기 전 태그를 이 파일(JSON)에 남긴다.")
@with_appcontext
def retag_events_command(apply, backup):
    """저장된 행사의 태그를 현재 태그 사전으로 다시 계산한다."""
    changes = retag_events(db.session, apply=apply)

    if apply and backup:
        with open(backup, "w", encoding="utf-8") as file:
            json.dump(changes, file, ensure_ascii=False, indent=1)
    if apply:
        db.session.commit()

    for change in changes[:60]:
        click.echo(f"{change['id']:>5} {change['title'][:20]} | {change['old']} -> {change['new']}")
    click.echo(f"바뀐 행사 {len(changes)}건 ({'저장함' if apply else '저장하지 않음(dry-run)'})")
