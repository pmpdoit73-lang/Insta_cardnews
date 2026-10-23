"""Claude로 가전·주방 살림 주제를 고르고 목록형 카드뉴스(표지 + 팁 6~8장 + 경고·저장 유도) 대본·캡션·해시태그·사진 프롬프트를 쓴다."""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import anthropic

MODEL = "claude-opus-5-5"
PERSONA = (Path(__file__).resolve().parent.parent / "prompts" / "persona.md").read_text(encoding="utf-8")

KINDS = ["가전 꿀팁", "주방 꿀팁", "살림 꿀팁", "가전 소식"]
TITLE_MAX, TIP_TITLE_MAX, LINE_MAX = 12, 10, 20  # 한 줄 최대 글자 수 (넘으면 render가 글씨를 줄임)
TIPS_MIN, TIPS_MAX = 6, 8  # 팁 카드 수. 표지 + 팁 + 마무리 = 8~10장 (인스타·텔레그램 한도 10장)
N_MARK = "{N}"             # 표지 제목의 팁 개수 자리. 코드가 실제 개수로 바꿔 넣는다

LINES = {"type": "array", "items": {"type": "string"}}
TIP_CARD = {
    "type": "object",
    "properties": {
        "title": {"type": "string", "description": f"팁 제목 2~{TIP_TITLE_MAX}자 (예: '바스켓 기름때 불리기')"},
        "lines": {**LINES, "description": f"설명 정확히 2줄, 한 줄 {LINE_MAX}자 이내. "
                                          "1줄: 방법 + 구체적 숫자(시간·양), 2줄: 이유나 효과"},
        "note": {"type": "string", "description": "꼭 필요한 주의 한 줄(24자 이내), 없으면 빈 문자열"},
        "image_prompt": {"type": "string",
                         "description": "같은 세트장에서 이 카드만 바뀌는 것 영어 묘사 "
                                        "(올려 둔 음식·물건·손 동작). 글자·얼굴 없이"},
    },
    "required": ["title", "lines", "note", "image_prompt"],
    "additionalProperties": False,
}
WARNING_CARD = {
    "type": "object",
    "properties": {
        "title": {"type": "string", "description": f"경고 제목 {TITLE_MAX}자 이내 (예: '이건 절대 하지 마세요')"},
        "lines": {**LINES, "description": "하지 말아야 할 것과 이유 2~3줄, 한 줄 24자 이내"},
        "image_prompt": {"type": "string", "description": "같은 세트장에 하지 말아야 할 물건들이 놓인 장면 영어 묘사"},
    },
    "required": ["title", "lines", "image_prompt"],
    "additionalProperties": False,
}
SCRIPT = {
    "type": "object",
    "properties": {
        "title": {**LINES, "description": f"표지 제목 정확히 2줄, 한 줄 {TITLE_MAX}자 이내. "
                                          f"둘째 줄 끝에 개수 자리 {N_MARK} (예: '기름때 확 줄이는' / "
                                          f"'에어프라이어 관리법 {N_MARK}')"},
        "highlight": {"type": "string", "description": "title 안에 그대로 들어 있는 강조할 말 (2~7자, {N} 제외)"},
        "subtitle": {"type": "string", "description": "표지 부제 한 줄 18자 이내, 공감형 (예: '굽기만 하고 청소는 미루셨죠?')"},
        "scene": {"type": "string",
                  "description": "모든 카드가 같이 쓸 세트장 영어 묘사: 주인공 가전 1개 + 밝은 한국 가정 주방 "
                                 "(조리대 재질, 소품, 창가 햇살). 모든 사진이 이 장면을 그대로 씀"},
        "cover_image_prompt": {"type": "string", "description": "표지 사진: 세트장에서 주인공 가전이 돋보이는 장면 영어 묘사"},
        "tips": {"type": "array", "items": TIP_CARD,
                 "description": f"팁 카드 {TIPS_MIN}~{TIPS_MAX}장. 서로 다른 활용법·관리법"},
        "warning": WARNING_CARD,
        "save_line": {"type": "string", "description": "저장 유도 한 줄 20자 이내 (예: '저장해두고 청소할 때 꺼내보세요')"},
        "caption": {"type": "string",
                    "description": "인스타 캡션. 첫 줄은 1인칭 고백·공감 한 문장 + 이모지 1개 "
                                   "(예: '에어프라이어 바스켓, 1년 동안 물로만 헹궜어요 😅'), 이어서 3~5줄 요약, "
                                   "마지막에 누구나 답할 질문 한 줄. 해시태그 제외"},
        "hashtags": {**LINES, "description": "해시태그 10~15개, # 포함"},
        "photo_query": {"type": "string", "description": "무료 사진 검색용 영어 키워드 2~3단어"},
    },
    "required": ["title", "highlight", "subtitle", "scene", "cover_image_prompt", "tips", "warning",
                 "save_line", "caption", "hashtags", "photo_query"],
    "additionalProperties": False,
}
SCHEMA = {
    "type": "object",
    "properties": {
        "issue": {"type": "string", "description": "고른 주제 한 줄 ('에어프라이어 관리법', '전기밥솥 숨은 활용법' 처럼)"},
        "kind": {"type": "string", "enum": KINDS, "description": "표지 라벨"},
        "angle": {"type": "string", "description": "왜 골랐는지, 지금 계절·살림과 어떻게 이었는지 한 줄"},
        **SCRIPT["properties"],
    },
    "required": ["issue", "kind", "angle", *SCRIPT["required"]],
    "additionalProperties": False,
}


def _trend_text(trends):
    if not trends:
        return "(오늘은 기사를 못 가져왔어. 아래 지침대로 계절 꿀팁을 골라.)"
    lines = []
    for source, titles in trends.items():
        lines.append(f"## {source}")
        lines.extend(f"- {t}" for t in titles)
    return "\n".join(lines)


RULES = (
    "## 형식: 목록형 카드뉴스 (가전·도구 하나 × 활용법·관리법 여러 개)\n"
    f"- 표지 title은 정확히 2줄, 한 줄 {TITLE_MAX}자 이내. 공식: [이득] + [가전 이름] + [활용법·관리법 {N_MARK}].\n"
    f"  개수 숫자는 직접 쓰지 말고 {N_MARK}로 둬 (코드가 실제 팁 개수로 바꿈).\n"
    "- subtitle은 보는 사람이 '내 얘기네' 할 공감 한 줄.\n"
    f"- 팁은 {TIPS_MIN}~{TIPS_MAX}개. 제목은 짧게, 설명은 정확히 2줄(한 줄 {LINE_MAX}자 이내):\n"
    "  1줄 = 방법 + 구체적인 숫자(2분, 20초, 1큰술), 2줄 = 왜 좋은지·효과. 위험할 수 있으면 note에 주의 한 줄.\n"
    "- warning은 '이건 절대 ~하지 마세요' 식으로 하지 말아야 할 것과 이유.\n"
    "- save_line은 '저장해두고 ~할 때 꺼내보세요' 식으로 다시 볼 상황을 짚어.\n"
    "- highlight는 title 안에 글자 그대로 들어 있어야 해.\n"
    "- 시간·온도·양은 널리 알려진 방법만. 숫자를 지어내지 마.\n"
    "- 위험한 방법(전자레인지에 금속, 세제 섞기, 전원 켠 채 손대기)은 절대 권하지 마.\n"
    "- 사진: scene 하나를 모든 카드가 함께 써(같은 가전, 같은 조리대, 같은 햇살). "
    "image_prompt에는 그 카드에서 바뀌는 것(음식·물건·손)만 써. 글자·간판·얼굴이 나오지 않게."
)


def fill_count(post):
    """표지 제목의 {N}을 실제 팁 개수로 바꾼다 (표지 숫자와 팁 수가 어긋나지 않게)."""
    n = str(len(post.get("tips", [])))
    post["title"] = [ln.replace(N_MARK, n) for ln in post.get("title", [])]
    return post


def write_cards(trends, recent_issues=(), external=None):
    """trends: {출처: [제목...]}, recent_issues: 최근에 다룬·거절한 이슈(중복 방지)."""
    recent = "\n".join(f"- {r}" for r in recent_issues) or "(없음)"
    today = datetime.now(timezone(timedelta(hours=9)))
    user_msg = (
        f"오늘은 {today:%Y년 %m월 %d일}이야. 아래는 최근 가전·주방 관련 기사 목록이야.\n\n"
        f"{_trend_text(trends)}\n\n"
        f"최근에 이미 다뤘거나 거절된 주제 (같은 가전·같은 요령은 피해서 골라):\n{recent}\n\n"
        "1. 계정 소개(주방의 질을 높이는 가성비 가전·쿠팡 꿀템)에 딱 맞는 주제 하나를 골라.\n"
        "   - 기사 중에 가전을 쓰는 사람이 꼭 알아야 할 소식(리콜, 전기요금, 쓸모 있는 신기능)이 있으면 '가전 소식'\n"
        "   - 아니면 '이거 몰랐으면 손해' 싶은 꿀팁을 골라 '가전 꿀팁'·'주방 꿀팁'·'살림 꿀팁' 중 하나로.\n"
        "     지금 계절에 맞으면 더 좋아 (예: 가을·겨울엔 김장, 가습기, 전기요금, 난방 가전).\n"
        "   - 누구나 아는 뻔한 얘기보다 '나만 몰랐네' 싶은 구체적인 요령을 골라. kind에 종류를 적어.\n"
        "   - 가전·도구 하나를 정해 '활용법'·'관리법'·'청소법'처럼 여러 요령을 묶을 수 있는 주제가 좋아.\n"
        "2. 그 주제로 목록형 카드뉴스 대본, 캡션, 해시태그, 사진 프롬프트를 만들어.\n"
        + RULES + _external_text(external)
    )
    return fill_count(_checked(user_msg, SCHEMA))


def rewrite_cards(d):
    """같은 주제로 대본만 새로 쓴다."""
    user_msg = (
        f"주제: {d['issue']}\n종류: {d['kind']}\n시선: {d.get('angle', '')}\n\n"
        f"지난번 표지 제목: {' / '.join(d['title'])}\n\n"
        "같은 주제로 목록형 카드뉴스 대본을 다시 써 줘. 지난번 표지와 다른 각도로 시작해.\n" + RULES
    )
    return fill_count(_checked(user_msg, SCRIPT))


def problems(post):
    """대본이 카드 규칙에 맞는지 검사. 문제 목록(없으면 빈 목록)."""
    errs = []
    title, tips = post.get("title", []), post.get("tips", [])
    if len(title) != 2:
        errs.append("표지 title이 2줄이 아님")
    if N_MARK not in "".join(title):
        errs.append(f"표지 title에 개수 자리 {N_MARK}가 없음")
    if not TIPS_MIN <= len(tips) <= TIPS_MAX:
        errs.append(f"팁이 {TIPS_MIN}~{TIPS_MAX}개가 아님 ({len(tips)}개)")
    if post.get("highlight") and post["highlight"] not in "".join(title):
        errs.append("표지 highlight가 제목 안에 없음")
    for i, t in enumerate(tips, 1):
        if len(t.get("lines", [])) != 2:
            errs.append(f"팁 {i}번 설명이 2줄이 아님")
    if not 2 <= len(post.get("warning", {}).get("lines", [])) <= 3:
        errs.append("warning 설명이 2~3줄이 아님")
    long = [ln for ln in title if len(ln.replace(N_MARK, "8")) > TITLE_MAX + 2]
    long += [t["title"] for t in tips if len(t.get("title", "")) > TIP_TITLE_MAX + 2]
    long += [ln for t in tips for ln in t.get("lines", []) if len(ln) > LINE_MAX + 3]
    if long:
        errs.append("너무 긴 줄: " + ", ".join(long))
    return errs


def _checked(user_msg, schema):
    post = _ask(user_msg, schema)
    errs = problems(post)
    if errs:  # 규칙을 어기면 한 번 더 쓰게 한다
        print(f"[writer] 규칙 위반 → 다시 씀: {errs}")
        post = _ask(user_msg + "\n\n주의: 지난번 대본은 이 규칙을 어겼어. 고쳐서 다시 써: " + "; ".join(errs), schema)
        errs = problems(post)
        if errs:
            print(f"[writer] 두 번째도 규칙 위반 (그대로 진행, render가 글씨 크기로 맞춤): {errs}")
    return post


def _ask(user_msg, schema):
    client = anthropic.Anthropic()
    response = client.beta.messages.create(
        model=MODEL,
        max_tokens=16000,
        system=PERSONA,
        messages=[{"role": "user", "content": user_msg}],
        output_config={"effort": "low", "format": {"type": "json_schema", "schema": schema}},
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
    )
    if response.stop_reason == "refusal":
        raise RuntimeError("Claude가 이번 글쓰기를 거절했어요.")
    text = next(b.text for b in response.content if b.type == "text")
    return json.loads(text)


def _external_text(external):
    """gil이 보내 줄 벤치마킹 카드뉴스 분석 (나중에 추가). 없으면 빈 문자열."""
    if not external:
        return ""
    parts = [f"- {x.get('why_it_works', '')} / 형식: {' / '.join(x.get('format_rules', []))}"
             for x in external[-6:]]
    return ("\n\n## 벤치마킹: gil이 고른 인기 카드뉴스의 형식 (가장 중요)\n" + "\n".join(parts)
            + "\n형식만 따라 하고 내용·문장은 절대 베끼지 마.")
