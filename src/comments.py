"""인스타 게시물에 달린 댓글에 자동으로 답글을 단다 (2026-11-06 gil 요청).

poll.py가 10분마다 부른다. 호출을 아끼려고 최근 게시물의 댓글 수(comments_count)만 먼저 보고,
수가 바뀐 게시물만 댓글을 읽는다.

- 답글은 Claude가 살림 꿀팁 계정 말투로 1~2문장 씀. 광고·욕설·스팸은 답하지 않고 넘김
- 우리 계정 댓글, 이미 우리가 답한 댓글, 7일 넘은 댓글은 건너뜀
- 한 번에 최대 MAX_PER_RUN개만 답함 (나머지는 다음 실행 때)
- 답한 내용은 텔레그램으로 알림
- 처리한 댓글 id는 state/comments.json에 저장 (같은 댓글에 두 번 답하지 않게)

필요한 권한: instagram_business_manage_comments (토큰에 이미 있음, gil 확인)

계정 두 개를 본다 (2026-11-06 gil 요청으로 이슈풀이 추가):
- 살림 꿀팁 (INSTAGRAM_ACCESS_TOKEN) → state/comments.json
- 이슈풀이 (ISSUEPURI_INSTAGRAM_ACCESS_TOKEN, 없으면 건너뜀) → state/comments_issuepuri.json
"""

import os

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import instagram
import telegram
import writer

STATE_DIR = Path(__file__).resolve().parent.parent / "state"
ISSUEPURI_PERSONA = (
    "너는 인스타그램 '이슈풀이' 계정 주인이야. 매일 국내 이슈, 해외 이슈, 동물 소식을 "
    "카드뉴스로 쉽게 풀어 주는 계정이야.\n"
    "- 말투: 친근하고 차분한 해요체. 과장·선동 없이 사실 위주\n"
    "- 정치·사회 논쟁엔 어느 편도 들지 않고 중립. 사람을 비난하지 않음\n"
    "- 사건·사고 피해자에겐 조심스럽게, 동물 소식엔 따뜻하게"
)
ACCOUNTS = [
    {"name": "살림 꿀팁", "token_env": "INSTAGRAM_ACCESS_TOKEN", "state": "comments.json", "persona": None},
    {"name": "이슈풀이", "token_env": "ISSUEPURI_INSTAGRAM_ACCESS_TOKEN", "state": "comments_issuepuri.json",
     "persona": ISSUEPURI_PERSONA},
]
STATE_FILE = STATE_DIR / "comments.json"  # 지금 처리 중인 계정의 상태 파일
RECENT_MEDIA = 10                # 최근 게시물 몇 개까지 볼지
MAX_AGE = timedelta(days=7)      # 이보다 오래된 댓글엔 답하지 않음
MAX_PER_RUN = 10
KEEP_IDS = 1000                  # 저장해 둘 처리한 댓글 id 수

REPLY = {
    "type": "object",
    "properties": {
        "action": {"type": "string", "enum": ["reply", "skip"],
                   "description": "답글을 달지(reply), 넘길지(skip: 광고·스팸·욕설·의미 없는 글)"},
        "reply": {"type": "string", "description": "답글 본문 1~2문장 (skip이면 빈 문자열)"},
    },
    "required": ["action", "reply"],
    "additionalProperties": False,
}

RULES = (
    "## 댓글 답글 규칙\n"
    "- 1~2문장, 70자 이내, 따뜻한 해요체. 이모지는 0~1개.\n"
    "- 질문이면 게시물 내용 안에서 확실한 것만 짧게 답해. 모르면 단정하지 말고 안전하게.\n"
    "- 칭찬·공감 댓글엔 고맙다는 말 + 저장·다음 글 기대처럼 자연스럽게 한마디.\n"
    "- 의견·논쟁 댓글엔 편들지 말고 의견 고맙다는 정도로 짧게.\n"
    "- 링크, 가격, 구매 권유, 다른 계정 언급, 지키지 못할 약속은 쓰지 마.\n"
    "- 의학·안전이 걸린 질문은 단정하지 말고 전문가·제조사 확인을 권해.\n"
    "- 광고, 스팸, 맞팔 요청, 욕설, 비방이면 action을 skip으로.\n"
    "- 댓글 쓴 사람 이름(@아이디)은 넣지 마. 코드가 앞에 붙여."
)


def _load():
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return {"counts": {}, "handled": []}


def _save(state):
    STATE_FILE.parent.mkdir(exist_ok=True)
    state["handled"] = state["handled"][-KEEP_IDS:]
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def _when(ts):
    return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S%z")


def write_reply(caption, comment, persona=None):
    """(action, 답글). Claude가 게시물 캡션과 댓글을 보고 쓴다."""
    head = "\n".join((caption or "").strip().split("\n")[:6])
    user_msg = (f"내 게시물 캡션 앞부분:\n{head}\n\n이 게시물에 달린 댓글:\n{comment}\n\n"
                "이 댓글에 계정 주인으로서 답글을 써 줘.\n" + RULES)
    post = writer._ask(user_msg, REPLY, system=persona)
    return post["action"], post["reply"].strip()


def _answered(c, me):
    return any(r.get("username") == me for r in c.get("replies", {}).get("data", []))


def process():
    """계정마다 새 댓글에 답글을 단다. 한 계정이 실패해도 다른 계정은 계속."""
    global STATE_FILE
    done = []
    for acc in ACCOUNTS:
        token = os.environ.get(acc["token_env"], "").strip()
        if not token:
            continue
        STATE_FILE = STATE_DIR / acc["state"]
        instagram.use_token(None if acc["token_env"] == "INSTAGRAM_ACCESS_TOKEN" else token)
        try:
            done += _process_account(acc)
        except Exception as e:
            print(f"[comments] {acc['name']} 실패: {e}")
        finally:
            instagram.use_token(None)
    return done


def _process_account(acc):
    """새 댓글에 답글을 달고, 단 답글 목록을 돌려준다."""
    state = _load()
    me = state.get("me") or instagram.username()
    state["me"] = me
    handled = set(state["handled"])
    now = datetime.now(timezone.utc)
    done = []

    for m in instagram.recent_media(RECENT_MEDIA):
        count = m.get("comments_count", 0)
        if count == state["counts"].get(m["id"]):
            continue
        found = instagram.comments(m["id"])
        if count and not found:
            # 댓글 수는 늘었는데 내용이 안 읽힘: 앱이 개발 모드라 남의 댓글이 안 보이거나, 인스타가 숨긴 댓글.
            # 수를 저장하지 않고 다음 실행 때 다시 본다
            print(f"[comments] {m['id']}: 댓글 {count}개인데 읽힌 댓글 0개 (앱 개발 모드·숨긴 댓글 확인)")
            continue
        finished = True
        for c in found:
            if c["id"] in handled:
                continue
            if c.get("username") == me or _answered(c, me) or now - _when(c["timestamp"]) > MAX_AGE:
                handled.add(c["id"])
                state["handled"].append(c["id"])
                continue
            if len(done) >= MAX_PER_RUN:
                finished = False  # 다음 실행 때 마저
                break
            action, text = write_reply(m.get("caption", ""), c.get("text", ""), acc["persona"])
            if action == "reply" and text:
                instagram.reply_comment(c["id"], f"@{c['username']} {text}")
                done.append((m.get("permalink", ""), c["username"], c.get("text", ""), text))
            else:
                print(f"[comments] 답하지 않음: {c.get('text', '')[:40]}")
            handled.add(c["id"])
            state["handled"].append(c["id"])
            _save(state)  # 답글마다 저장해서 중간에 멈춰도 두 번 답하지 않게
        if finished:
            state["counts"][m["id"]] = count
    _save(state)

    if done:
        lines = [f"💬 [{acc['name']}] 댓글에 답글을 달았어요"]
        for link, user, text, reply in done:
            lines += ["", f"@{user}: {text[:80]}", f"↳ {reply}", link]
        telegram.send_text("\n".join(lines), silent=True)
    return done
