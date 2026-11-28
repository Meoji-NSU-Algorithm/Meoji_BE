"""행사 태그를 고르는 사전과 규칙.

태그마다 인정하는 단어(terms), 소개글에서 몇 번 나와야 붙일지(min_hits), 먼저 지울 말(exclude)을 적는다.
단어를 그냥 "포함하는지"로 찾으면 '불꽃'이 '꽃'으로, 지나가는 "가족, 친구"가 가족 태그로 잡힌다.
그래서 이렇게 판단한다.

1. 소개글은 단어 앞이 한글이 아닐 때만 일치로 센다. '불꽃놀이'의 '꽃'이나 '이야기꽃'은 앞에 한글이 있어 제외된다.
2. 행사명은 한 번만 있어도 붙인다. 행사명은 붙여 쓰는 말이 많아서('마산가고파국화축제') 3글자 이상 단어는
   앞에 한글이 있어도 인정한다. 2글자 단어('국화', '가족')는 '한국화'처럼 다른 말에 들어가므로 앞이 한글이면 제외한다.
3. 소개글에서만 나오면 min_hits번 이상이어야 붙인다. '가족', '체험'처럼 넓은 단어는 2로 두어 지나가는 언급을 거른다.
4. exclude는 장소나 상용 문구('제1전시장', '[공연소개]')를 먼저 지워서 태그 근거로 세지 않게 한다.

단어를 더하거나 빼면 되고 코드는 고치지 않는다. 오탐이 나오면 단어를 구체적으로 바꾸거나 exclude에 더하고,
놓친 행사가 있으면 그 표현을 terms에 더한다. 키는 tags 테이블의 태그 이름과 같아야 한다.
"""

import re

# 조건: 태그마다 인정하는 단어와 최소 언급 횟수를 적는다. 예) "가족": 행사명에 있거나 소개글에 2번 이상이면 붙인다.
TAG_TERMS = {
    "불꽃놀이": {"terms": ("불꽃놀이", "불꽃축제", "불꽃쇼"), "min_hits": 1},
    "푸드트럭": {"terms": ("푸드트럭", "푸드 트럭"), "min_hits": 1},
    # 단어 '꽃' 하나는 "용서의 꽃", "꽃 핀 문명" 같은 은유에도 걸리고, '장미'는 연극 '어린 왕자'에도 나온다.
    "꽃": {
        "terms": ("꽃길", "벚꽃", "봄꽃", "꽃축제", "꽃박람회", "국화축제", "국화", "튤립", "장미꽃", "장미축제"),
        "min_hits": 1,
        # '불꽃축제'가 '꽃축제'로 잡히지 않게 먼저 지운다.
        "exclude": ("불꽃",),
    },
    # 행사 한 편의 프로그램 나열("공연, 먹거리, 체험")에 한 번 나오는 것은 먹거리 행사가 아니다.
    "먹거리": {
        "terms": ("먹거리", "먹거리장터", "음식축제", "미식", "수산물축제", "대하축제", "떡볶이", "보쌈", "농식품", "맛집"),
        "min_hits": 2,
    },
    "야간": {"terms": ("야간",), "min_hits": 1},
    "가족": {"terms": ("가족",), "min_hits": 2},
    "체험": {"terms": ("체험",), "min_hits": 2},
    # KOPIS 소개글은 '[공연소개]'로 시작하고, '공연장'은 장소다.
    "공연": {"terms": ("공연",), "min_hits": 2, "exclude": ("공연소개", "공연장")},
    # '제1전시장', '전시홀'은 장소다.
    "전시": {"terms": ("전시",), "min_hits": 2, "exclude": ("전시장", "전시홀", "전시관", "전시실")},
    "음악": {"terms": ("음악",), "min_hits": 2},
}


def _any_of(terms):
    """단어들 중 하나와 일치하는 정규식 조각. 긴 단어를 먼저 시도해 같은 자리를 한 번만 센다."""
    return "|".join(re.escape(term) for term in sorted(terms, key=len, reverse=True))


# 소개글: 단어 앞이 한글이 아닐 때만 일치한다. '불꽃놀이'의 '꽃'이나 '이야기꽃'은 제외된다.
_WORD_AT_START = {
    tag: re.compile("(?<![가-힣])(?:" + _any_of(rule["terms"]) + ")")
    for tag, rule in TAG_TERMS.items()
}

# 행사명: 3글자 이상 단어는 앞에 한글이 있어도 일치한다. 붙여 쓴 제목('마산가고파국화축제')을 잡기 위해서다.
_LONG_WORD_IN_TITLE = {
    tag: re.compile("(?:" + _any_of(long_terms) + ")")
    for tag, rule in TAG_TERMS.items()
    if (long_terms := [term for term in rule["terms"] if len(term) >= 3])
}


def _remove(text, words):
    """text에서 words를 지운다(공백으로 바꿔 앞뒤 글자가 붙지 않게 한다)."""
    for word in words:
        text = text.replace(word, " ")
    return text


def _in_title(tag, title):
    """행사명에 이 태그의 단어가 있는지."""
    if _WORD_AT_START[tag].search(title):
        return True
    return tag in _LONG_WORD_IN_TITLE and bool(_LONG_WORD_IN_TITLE[tag].search(title))


def _mentions(tag, description):
    """소개글에 이 태그의 단어가 몇 번 나오는지."""
    return len(_WORD_AT_START[tag].findall(description))


def match_tags(title, description):
    """행사명과 소개글에서 붙일 태그 이름 목록을 TAG_TERMS 순서대로 돌려준다."""
    matched = []
    for tag, rule in TAG_TERMS.items():
        # 장소나 상용 문구는 근거로 세지 않으려고 먼저 지운다.
        exclude = rule.get("exclude", ())
        clean_title = _remove(title or "", exclude)
        clean_description = _remove(description or "", exclude)

        # 행사명에 있으면 바로 붙이고, 소개글만 있으면 min_hits번 이상 나와야 붙인다.
        if _in_title(tag, clean_title) or _mentions(tag, clean_description) >= rule["min_hits"]:
            matched.append(tag)
    return matched


# 카테고리가 곧 태그인 경우. 소개글이 없는 KOPIS 공연도 이 규칙으로 최소 '공연' 태그를 갖는다.
CATEGORY_TAGS = ("공연", "전시", "체험")


def tags_for(title, description, category_name):
    """사전 규칙으로 고른 태그에 카테고리와 같은 이름의 태그를 더해 TAG_TERMS 순서로 돌려준다."""
    matched = match_tags(title, description)
    if category_name in CATEGORY_TAGS and category_name not in matched:
        matched.append(category_name)
    return [tag for tag in TAG_TERMS if tag in matched]
