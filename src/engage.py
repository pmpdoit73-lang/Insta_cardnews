"""매일 아침 '오늘의 소통' 안내를 텔레그램으로 보낸다 (2026-11-10 gil 요청).

다른 계정 글에 좋아요·댓글을 '자동으로' 다는 건 하지 않는다.
- 인스타 공식 API에 그런 기능이 없고, 비공식 방법(자동 클릭)은 약관 위반이라 계정 정지 위험이 크다.
- 그래서 봇은 '어디에 가서 무슨 말을 할지'만 준비하고, 좋아요·댓글은 gil이 직접 누르고 붙여넣는다.

하는 일 두 가지:
1) 아침 안내 (poll.py가 10분마다 부르지만 SEND_HOUR시 이후 하루 한 번만 보냄)
   - 오늘 둘러볼 해시태그 2개 + 살림 계정 2~3개 (링크를 누르면 인스타 앱이 열림)
   - 바로 쓸 수 있는 상황별 댓글 초안 5개 (글씨를 누르면 복사됨)
   - 페이스북 페이지 연결 방식(graph.facebook.com)일 때만: 해시태그 인기 게시물 3개를 직접 찾아
     그 글에 맞춘 댓글 초안까지 (인스타 로그인 방식 API엔 해시태그 검색 기능이 없음)
2) 맞춤 댓글: gil이 마음에 드는 게시물을 캡처(또는 캡션 복사)해서 봇에 보내면
   다음 실행(10분 안)에 그 글에 딱 맞는 댓글 초안 3개를 답장으로 보냄

둘러볼 계정 목록: prompts/engage_accounts.txt (gil이 한 줄에 하나씩 추가·삭제)
지금 바로 받기: python src/engage.py
"""

import base64
import html
import json
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

import comments
import draft
import instagram
import telegram
import writer

STATE_FILE = comments.STATE_DIR / "engage.json"
ACCOUNTS_FILE = Path(__file__).resolve().parent.parent / "prompts" / "engage_accounts.txt"
SEND_HOUR = 8          # 한국 시각 8시 이후 첫 실행 때 보냄 (07:00 게시 한 시간 뒤)
TAGS_PER_DAY = 2
ACCOUNTS_PER_DAY = 3
HASHTAGS = ["살림꿀팁", "주방살림", "살림노하우", "정리수납", "주방꿀팁", "청소꿀팁",
            "살림스타그램", "살림템", "주방정리", "가전꿀팁", "자취꿀팁", "살림팁"]
WEEKDAYS = "월화수목금토일"

RULES = (
    "## 댓글 규칙 (남의 게시물에 다는 댓글)\n"
    "- 1~2문장, 25~60자. 따뜻하고 자연스러운 해요체. 이모지는 0~1개.\n"
    "- '좋은 정보 감사합니다'처럼 아무 글에나 붙는 말 금지. 글 내용 하나를 콕 집어 반응해.\n"
    "- 내 경험 한 조각(살림 30년 차, 주방·가전 좋아함)이나 진짜 궁금한 질문을 섞으면 좋아. 셋 중 하나는 질문으로 끝내.\n"
    "- 맞팔·선팔·홍보·링크·내 계정 언급·'제 계정에도 놀러 오세요' 같은 말은 절대 금지.\n"
    "- 과장된 칭찬, 광고 티, AI가 쓴 티(번호 매기기, 딱딱한 요약) 금지. 사람이 폰으로 쓴 것처럼.\n"
    "- 사실을 지어내지 마. 모르는 건 단정하지 말고 질문으로."
)

DRAFTS = {
    "type": "object",
    "properties": {
        "drafts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "situation": {"type": "string", "description": "어떤 글에 쓰면 좋은지 12자 이내 (예: '냉장고 정리 글')"},
                    "comment": {"type": "string", "description": "댓글 본문"},
                },
                "required": ["situation", "comment"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["drafts"],
    "additionalProperties": False,
}

REPLY = {
    "type": "object",
    "properties": {
        "summary": {"type": "string", "description": "이 게시물이 무슨 내용인지 20자 이내 (못 읽으면 '내용 확인 어려움')"},
        "comments": {"type": "array", "items": {"type": "string"}, "description": "댓글 초안 정확히 3개, 서로 다른 느낌"},
    },
    "required": ["summary", "comments"],
    "additionalProperties": False,
}


# ---------- 상태 ----------

def _load():
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return {"last": "", "day": 0}


def _save(state):
    STATE_FILE.parent.mkdir(exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def _accounts():
    """prompts/engage_accounts.txt의 계정 이름들 (# 뒤는 메모, @는 있어도 없어도 됨)."""
    try:
        lines = ACCOUNTS_FILE.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return []
    out = []
    for line in lines:
        name = line.split("#")[0].strip().lstrip("@")
        if name and name not in out:
            out.append(name)
    return out


def _rotate(items, day, n):
    """날마다 n개씩 돌아가며 고른다 (목록이 n개보다 적으면 있는 만큼)."""
    if not items:
        return []
    start = (day * n) % len(items)
    return [items[(start + i) % len(items)] for i in range(min(n, len(items)))]


def _link(url, label):
    """한글이 들어간 주소도 눌리게 링크로 감싼다."""
    return f'<a href="{html.escape(quote(url, safe=":/?=&%"))}">{html.escape(label)}</a>'


def _code(text):
    """텔레그램에서 누르면 복사되는 글씨."""
    return f"<code>{html.escape(text)}</code>"


# ---------- 아침 안내 ----------

def _general_drafts(tags):
    msg = (f"오늘 gil이 인스타에서 #{' #'.join(tags)} 해시태그와 살림 계정 글을 둘러보며 댓글을 남길 거야.\n"
           "이런 살림·주방·가전 글에 바로 붙여넣을 수 있는 댓글 초안 5개를 써 줘. "
           "5개는 서로 다른 상황(예: 정리수납 글, 청소 요령 글, 가전 사용법 글, 살림템 소개 글, 요리·보관 글)에 맞춰.\n"
           "글마다 한두 단어만 바꿔 쓰면 되도록 너무 특정하지 않게, 그래도 흔한 인사말은 아니게.\n\n" + RULES)
    return writer._ask(msg, DRAFTS, system=writer.PERSONA)["drafts"][:5]


def _post_drafts(posts):
    """실제 게시물(캡션)마다 맞춤 댓글 하나씩."""
    listing = "\n\n".join(f"[{i + 1}] {(p.get('caption') or '')[:400]}" for i, p in enumerate(posts))
    msg = (f"아래는 다른 살림 계정의 인스타 게시물 캡션 {len(posts)}개야. 순서대로 하나씩, 그 글에 다는 댓글을 써 줘. "
           "situation엔 그 글이 무슨 내용인지 짧게.\n\n" + listing + "\n\n" + RULES)
    return writer._ask(msg, DRAFTS, system=writer.PERSONA)["drafts"][:len(posts)]


def _find_posts(tags):
    """해시태그 인기 게시물 (페이스북 연결 방식에서만 됨). 안 되면 빈 목록."""
    if not instagram.can_search_hashtags():
        return []
    posts = []
    for tag in tags:
        try:
            posts += [p for p in instagram.hashtag_top_media(tag) if p.get("permalink") and p.get("caption")][:2]
        except RuntimeError as e:
            print(f"[engage] #{tag} 검색 실패: {e}")
    return posts[:3]


def build_message(today, day):
    tags = _rotate(HASHTAGS, day, TAGS_PER_DAY)
    accounts = _rotate(_accounts(), day, ACCOUNTS_PER_DAY)
    lines = [f"☀️ <b>{today:%m/%d}({WEEKDAYS[today.weekday()]}) 오늘의 소통</b> · 10~15분이면 충분해요",
             "좋아요·댓글은 gil님이 <b>직접</b> 눌러 주세요 (자동으로 하면 계정 정지 위험)", ""]

    num = iter("①②③④")
    posts = _find_posts(tags)
    if posts:
        lines.append(f"<b>{next(num)} 오늘 댓글 남길 게시물</b> (누르면 인스타 앱이 열려요)")
        for p, d in zip(posts, _post_drafts(posts)):
            lines += [_link(p["permalink"], f"👉 {d['situation']}"), _code(d["comment"]), ""]

    lines.append(f"<b>{next(num)} 오늘 둘러볼 곳</b> (누르면 인스타 앱이 열려요)")
    for t in tags:
        lines.append("• " + _link(f"https://www.instagram.com/explore/tags/{t}/", f"#{t}"))
    for a in accounts:
        lines.append("• " + _link(f"https://www.instagram.com/{a}/", f"@{a}"))
    lines += ["", f"<b>{next(num)} 이렇게 해 보세요</b>",
              "• 24시간 안에 올라온 글 3~5개에 좋아요 + 댓글",
              "• 팔로워 1천~1만 명 정도 비슷한 크기 계정이 답방이 잘 와요",
              "• 아래 초안은 글 내용에 맞게 한두 단어만 바꿔서 붙여넣기", ""]

    lines.append(f"<b>{next(num)} 상황별 댓글 초안</b> (글씨를 누르면 복사돼요)")
    for i, d in enumerate(_general_drafts(tags), 1):
        lines += [f"{i}. {html.escape(d['situation'])}", _code(d["comment"])]
    lines += ["", "📸 <b>맞춤 댓글</b>: 마음에 드는 게시물을 캡처하거나 캡션을 복사해서 이 봇에 보내 주세요. "
                  "10분 안에 그 글에 딱 맞는 댓글 3개를 써 드려요."]
    return "\n".join(lines)


def send():
    state = _load()
    today = datetime.now(draft.KST)
    text = build_message(today, state.get("day", 0))
    telegram.send_text(text, html=True)
    state["last"] = today.strftime("%Y-%m-%d")
    state["day"] = state.get("day", 0) + 1
    _save(state)
    return text


def maybe_send():
    """SEND_HOUR시가 지났고 오늘 아직 안 보냈으면 보낸다 (poll.py가 부름)."""
    now = datetime.now(draft.KST)
    if now.hour < SEND_HOUR or _load().get("last") == now.strftime("%Y-%m-%d"):
        return
    send()


# ---------- 맞춤 댓글 (gil이 캡처·캡션을 봇에 보내면) ----------

def wants_reply(message):
    """gil이 보낸 메시지 중 맞춤 댓글 요청으로 볼 것: 사진, 또는 10자 넘는 글."""
    return bool(message.get("photo")) or len((message.get("text") or "").strip()) > 10


def reply_to(message):
    """캡처 사진이나 캡션 글을 보고 댓글 초안 3개를 답장으로 보낸다."""
    content = []
    if message.get("photo"):
        data = telegram.download_file(message["photo"][-1]["file_id"])  # 가장 큰 크기
        content.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                                    "data": base64.b64encode(data).decode()}})
    note = (message.get("caption") or message.get("text") or "").strip()
    content.append({"type": "text", "text": (
        "다른 살림 계정의 인스타 게시물이야 (캡처 화면이나 캡션 글). "
        "이 글에 내가 남길 댓글 초안 3개를 써 줘. 캡처에 보이는 계정 이름·댓글은 무시하고 게시물 내용에만 반응해.\n"
        + (f"\n함께 보낸 글:\n{note[:1500]}\n" if note else "") + "\n" + RULES)})
    out = writer._ask(content, REPLY, system=writer.PERSONA)
    lines = [f"💬 맞춤 댓글 초안 · {html.escape(out['summary'])}", "(글씨를 누르면 복사돼요)", ""]
    for i, c in enumerate(out["comments"][:3], 1):
        lines += [f"{i}.", _code(c)]
    telegram.send_text("\n".join(lines), html=True, reply_to=message.get("message_id"))


if __name__ == "__main__":
    out = send()
    print(out)
    sys.exit(0)
