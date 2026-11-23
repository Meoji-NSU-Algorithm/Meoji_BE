"""tag_terms.match_tags: 오탐(불꽃 -> 꽃, 지나가는 가족 언급)이 없는지 확인한다."""
import pytest

from app.domains.tour.tag_terms import TAG_TERMS, match_tags, tags_for


def test_fireworks_festival_is_not_flower():
    tags = match_tags("한강 축제", "한강 불꽃축제와 불꽃쇼가 열린다.")
    assert "불꽃놀이" in tags and "꽃" not in tags


@pytest.mark.parametrize("text", [
    "용서의 꽃 천 년의 이야기",   # 은유
    "제주에서 꽃 핀 문명은",      # 은유
    "이야기꽃을 피우는 시간",     # 앞이 한글
    "아름답게 꽃피운 축제",       # 단어 '꽃' 하나는 인정하지 않는다
])
def test_flower_metaphors_are_not_flower_tag(text):
    assert "꽃" not in match_tags("행사", text)


@pytest.mark.parametrize("text", ["봄꽃 축제가 열린다", "꽃길을 따라 걷는다", "벚꽃 명소"])
def test_real_flower_events_get_flower_tag(text):
    assert "꽃" in match_tags("행사", text)


def test_passing_mention_does_not_give_broad_tag():
    assert "가족" not in match_tags("행사", "가족, 친구, 연인과 함께 즐긴다.")


def test_repeated_mention_gives_broad_tag():
    assert "가족" in match_tags("행사", "온 가족이 함께하고 가족 단위 참가도 환영한다.")


def test_title_gives_broad_tag_with_one_mention():
    assert "음악" in match_tags("가을 음악 축제", "")


def test_specific_tag_needs_one_mention():
    assert match_tags("행사", "푸드트럭 20대가 운영된다.") == ["푸드트럭"]


def test_term_must_not_follow_hangul():
    # '야간'이 '심야간'처럼 한글 뒤에 붙어 있으면 일치가 아니다.
    assert "야간" not in match_tags("행사", "심야간 운영")
    assert "야간" in match_tags("행사", "야간 개장 행사")


def test_empty_inputs():
    assert match_tags(None, None) == []
    assert match_tags("", "") == []


def test_tag_names_are_the_seeded_ones():
    assert set(TAG_TERMS) == {"불꽃놀이", "푸드트럭", "야간", "체험", "가족", "공연", "전시", "음악", "꽃", "먹거리"}


@pytest.mark.parametrize("title", ["마산가고파국화축제", "부산불꽃축제"])
def test_compound_title_matches_long_terms(title):
    tags = match_tags(title, "")
    assert ("꽃" if "국화" in title else "불꽃놀이") in tags
    if "불꽃" in title:
        assert "꽃" not in tags   # '불꽃축제'가 '꽃축제'로 잡히면 안 된다


def test_short_term_in_title_needs_boundary():
    # '한국화'의 '국화'는 꽃이 아니다.
    assert "꽃" not in match_tags("한국화 전시", "")


def test_rose_in_play_is_not_flower_tag():
    assert "꽃" not in match_tags("연극 어린 왕자", "어린 왕자와 장미의 재회를 그린 음악극")


@pytest.mark.parametrize("text", ["제1전시장에서 열린다.", "수원컨벤션센터 전시홀에서 열린다."])
def test_exhibition_hall_is_not_exhibition_tag(text):
    assert "전시" not in match_tags("행사", text + " " + text)


def test_exhibition_tag_for_real_exhibition():
    assert "전시" in match_tags("행사", "작품 전시와 전시 해설이 있다.")


def test_performance_label_and_venue_are_not_performance_tag():
    assert "공연" not in match_tags("콘서트", "[공연소개] 대공연장에서 열린다. [공연소개]")


def test_food_listed_once_is_not_food_tag_but_twice_is():
    assert "먹거리" not in match_tags("행사", "공연, 먹거리와 체험을 즐긴다.")
    assert "먹거리" in match_tags("행사", "먹거리 부스를 운영하고 지역 먹거리를 판매한다.")


def test_food_festival_by_title():
    assert "먹거리" in match_tags("죽변항 수산물축제", "")


def test_tags_for_adds_category_tag():
    # 소개글 없는 공연도 카테고리로 '공연' 태그를 받고, 사전 태그와 겹치면 한 번만 들어간다.
    assert tags_for("햄릿", None, "공연") == ["공연"]
    assert tags_for("음악 공연", None, "공연") == ["공연", "음악"]
    assert tags_for("겨울 축제", None, "축제") == []
