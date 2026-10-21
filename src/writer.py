"""Claude로 가전·주방 살림 주제를 고르고 카드뉴스 5장 대본·캡션·해시태그·사진 프롬프트를 쓴다."""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import anthropic

MODEL = "claude-opus-5-5"
PERSONA = (Path(__file__).resolve().parent.parent / "prompts" / "persona.md").read_text(encoding="utf-8")

KINDS = ["가전 꿀팁", "주방 꿀팁", "살림 꿀팁", "가전 소식"]
TITLE_MAX, BODY_MAX = 11, 13  # 카드 한 줄 최대 글자 수 (넘으면 render가 글씨를 줄임)

LINES = {"type": "array", "items": {"type": "string"}}
BODY_CARD = {
    "type": "object",
    "properties": {
        "head": {"type": "string", "description": "카드 위 작은 소제목 (8자 이내, 예: '무슨 일?', '핵심 숫자')"},
        "lines": {**LINES, "description": f"본문 2~3줄, 한 줄 {BODY_MAX}자 이내"},
        "highlight": {"type": "string", "description": "lines 안에 그대로 들어 있는 강조할 말 (2~7자)"},
        "image_prompt": {"type": "string",
                         "description": "이 카드 배경 사진 영어 묘사. 구체적인 장소·물건·상황. 글자·얼굴 없이"},
    },
    "required": ["head", "lines", "highlight", "image_prompt"],
    "additionalProperties": False,
}
SCRIPT = {
    "type": "object",
    "properties": {
        "title": {**LINES, "description": f"표지 제목 정확히 2줄, 한 줄 {TITLE_MAX}자 이내"},
        "highlight": {"type": "string", "description": "title 안에 그대로 들어 있는 강조할 말 (2~7자)"},
        "cover_image_prompt": {"type": "string", "description": "표지 배경 사진 영어 묘사. 글자·얼굴 없이"},
        "body": {"type": "array", "items": BODY_CARD, "description": "본문 카드 정확히 3장"},
        "cta": {**LINES, "description": "마지막 카드 2줄 (저장·공유 유도, 한 줄 13자 이내)"},
        "caption": {"type": "string", "description": "인스타 캡션: 3~6줄 요약 + 마지막 질문 한 줄. 해시태그 제외"},
        "hashtags": {**LINES, "description": "해시태그 10~15개, # 포함"},
        "photo_query": {"type": "string", "description": "무료 사진 검색용 영어 키워드 2~3단어"},
    },
    "required": ["title", "highlight", "cover_image_prompt", "body", "cta", "caption", "hashtags",
                 "photo_query"],
    "additionalProperties": False,
}
SCHEMA = {
    "type": "object",
    "properties": {
        "issue": {"type": "string", "description": "고른 주제 한 줄 (기사면 기사 제목, 꿀팁이면 '에어프라이어 바스켓 기름때 제거' 처럼)"},
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
    f"- 표지 title은 정확히 2줄, 한 줄 {TITLE_MAX}자 이내. 첫 줄에 주어(누가/무엇이)를 이름으로.\n"
    f"- 본문 카드는 정확히 3장, 카드마다 2~3줄, 한 줄 {BODY_MAX}자 이내. 한 장에 한 가지만.\n"
    "  흐름: 흔한 실수/문제 → 이유 → 이렇게 하세요, 또는 꿀팁 1·2·3\n"
    "- highlight는 해당 줄 안에 글자 그대로 들어 있어야 해.\n"
    "- 기사의 숫자·날짜·제품명은 기사 제목에 있는 것만 써. 꿀팁의 시간·온도·양은 널리 알려진 방법만.\n"
    "- 위험한 방법(전자레인지에 금속, 세제 섞기, 전원 켠 채 손대기)은 절대 권하지 마.\n"
    "- 사진 프롬프트 4개(표지+본문 3)는 서로 다른 장면으로, 글자·간판·얼굴이 나오지 않게."
)


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
        "2. 그 주제로 카드뉴스 5장 대본, 캡션, 해시태그, 사진 프롬프트를 만들어.\n"
        "   사진은 깔끔한 한국 가정 주방·가전이 보이는 장면으로.\n"
        + RULES + _external_text(external)
    )
    return _checked(user_msg, SCHEMA)


def rewrite_cards(d):
    """같은 주제로 대본만 새로 쓴다."""
    user_msg = (
        f"주제: {d['issue']}\n종류: {d['kind']}\n시선: {d.get('angle', '')}\n\n"
        f"지난번 표지 제목: {' / '.join(d['title'])}\n\n"
        "같은 주제로 카드뉴스 5장 대본을 다시 써 줘. 지난번 표지와 다른 각도로 시작해.\n" + RULES
    )
    return _checked(user_msg, SCRIPT)


def problems(post):
    """대본이 카드 규칙에 맞는지 검사. 문제 목록(없으면 빈 목록)."""
    errs = []
    if len(post.get("title", [])) != 2:
        errs.append("표지 title이 2줄이 아님")
    if len(post.get("body", [])) != 3:
        errs.append("본문 카드가 3장이 아님")
    if post.get("highlight") and post["highlight"] not in "".join(post.get("title", [])):
        errs.append("표지 highlight가 제목 안에 없음")
    for i, b in enumerate(post.get("body", []), 1):
        if not 2 <= len(b.get("lines", [])) <= 3:
            errs.append(f"본문 {i}번이 2~3줄이 아님")
        if b.get("highlight") and b["highlight"] not in "".join(b.get("lines", [])):
            errs.append(f"본문 {i}번 highlight가 본문 안에 없음")
    long = [ln for ln in post.get("title", []) if len(ln) > TITLE_MAX + 2]
    long += [ln for b in post.get("body", []) for ln in b.get("lines", []) if len(ln) > BODY_MAX + 3]
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
