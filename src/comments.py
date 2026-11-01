"""댓글 답글 반자동화 (2026-11-01, gil 요청).

하루 1번(한국 20시 이후 첫 실행) 최근 게시물 5개의 새 댓글을 확인하고,
Claude가 답글 초안을 써서 텔레그램으로 보낸다.
✅ 올리기를 눌러야만 인스타에 답글이 달린다. 🔁 다른 답글, ⏭ 건너뛰기도 있음.

필요한 인스타 권한: instagram_business_manage_comments (토큰을 받을 때 체크)
상태 파일: state/comments.json  {댓글 id: {상태, 답글 초안, 텔레그램 메시지 번호 ...}}

실행: python src/comments.py  (FORCE=1이면 시간·하루 1번 제한 없이 바로 확인)
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path

import anthropic

import draft
import instagram
import telegram
import writer

STATE_FILE = Path(__file__).resolve().parent.parent / "state" / "comments.json"
CHECK_HOUR = 20          # 한국 시각 이 시간 이후 첫 실행 때 하루 1번 확인
RECENT_POSTS = 5         # 최근 게시물 몇 개의 댓글을 볼지
MAX_NEW = 5              # 한 번에 텔레그램으로 보낼 최대 개수 (몰리면 다음 날로)
PREFIX = "c:"            # 텔레그램 버튼 구분용 (카드뉴스 버튼과 섞이지 않게)

STATUS_LABEL = {"pending": "⏳ 대기", "posted": "✅ 답글 올림", "skipped": "⏭ 건너뜀", "failed": "⚠️ 실패"}


# ---------- 상태 저장 ----------

def load_state():
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return {"last_check": "", "comments": {}}


def save_state(state):
    STATE_FILE.parent.mkdir(exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")


# ---------- Claude 답글 초안 ----------

REPLY_GUIDE = """너는 인스타그램 살림 꿀팁 계정 주인이야. 내 게시물에 달린 댓글에 답글을 써 줘.
- 1~2문장, 60자 안팎. 해요체, 따뜻하고 자연스럽게. 이모지는 0~1개
- 댓글 내용을 짚어서 고마움이나 공감을 표현하고, 도움이 되면 게시물 내용과 이어지는 짧은 팁 하나
- 광고·홍보·링크·해시태그·다른 계정 태그 금지. 숫자나 사실을 지어내지 않기
- 질문이면 아는 범위에서 간단히 답하고, 모르면 확인해 보시라고 정중히
- 악플·스팸이어도 싸우지 말고 짧고 정중하게
답글 문장만 출력해. 따옴표나 설명 없이."""


def write_reply(post_caption, comment_text, username, avoid=""):
    msg = (f"[내 게시물 캡션]\n{post_caption[:600]}\n\n"
           f"[@{username} 님의 댓글]\n{comment_text}")
    if avoid:
        msg += f"\n\n[이전 초안 — 이것과 다르게 써 줘]\n{avoid}"
    resp = anthropic.Anthropic().messages.create(
        model=writer.MODEL,
        max_tokens=1000,
        system=REPLY_GUIDE,
        messages=[{"role": "user", "content": msg}],
    )
    text = "".join(b.text for b in resp.content if b.type == "text").strip().strip('"')
    if not text:
        raise RuntimeError("Claude가 답글을 쓰지 못했어요")
    return text


# ---------- 텔레그램 ----------

def _btn(cid, label, value):
    return {"text": label, "callback_data": f"{PREFIX}{cid}|{value}"}


def _keyboard(c, cid):
    if c["status"] in ("pending", "failed"):
        return [[_btn(cid, "✅ 올리기", "ok"), _btn(cid, "🔁 다른 답글", "again")],
                [_btn(cid, "⏭ 건너뛰기", "skip")]]
    return []


def _text(c):
    head = f"💬 새 댓글 · {STATUS_LABEL[c['status']]}"
    lines = [head, f"게시물: {c['post_title']}", "",
             f"@{c['username']}: {c['text']}", "",
             f"✍️ 답글 초안:\n{c['reply']}"]
    if c.get("error"):
        lines += ["", f"오류: {c['error'][:200]}"]
    if c.get("permalink"):
        lines += ["", c["permalink"]]
    return "\n".join(lines)


def _send(c, cid):
    m = telegram.send_text(_text(c), _keyboard(c, cid))
    c["message_id"] = m["message_id"]


def _refresh(c, cid):
    if c.get("message_id"):
        telegram.edit_draft({"message_id": c["message_id"]}, _text(c), _keyboard(c, cid))


# ---------- 새 댓글 확인 ----------

def due(state, now):
    if os.environ.get("FORCE") == "1":
        return True
    return now.hour >= CHECK_HOUR and state.get("last_check") != now.strftime("%Y-%m-%d")


def check():
    state = load_state()
    now = datetime.now(draft.KST)
    if not due(state, now):
        print("[comments] 오늘은 이미 확인했거나 아직 확인 시간이 아니에요")
        return
    state["last_check"] = now.strftime("%Y-%m-%d")  # 실패해도 하루 1번만 시도 (요청 한도 보호)
    save_state(state)

    me = instagram.username()
    seen = state["comments"]
    new = []
    for post in instagram.recent_media(RECENT_POSTS):
        if not post.get("comments_count"):
            continue
        for cm in instagram.comments(post["id"]):
            cid = cm["id"]
            if cid in seen or cm.get("username") == me:
                continue
            replied = any(r.get("username") == me for r in cm.get("replies", {}).get("data", []))
            if replied:  # gil이 직접 답글을 단 댓글
                seen[cid] = {"status": "posted", "username": cm.get("username", ""), "manual": True}
                continue
            new.append((post, cm))

    if not new:
        save_state(state)
        print("[comments] 새 댓글 없음")
        return
    for post, cm in new[:MAX_NEW]:
        cid = cm["id"]
        caption = post.get("caption") or ""
        c = {
            "status": "pending",
            "media_id": post["id"],
            "post_title": caption.strip().split("\n")[0][:40],
            "permalink": post.get("permalink", ""),
            "caption": caption[:600],
            "username": cm.get("username", ""),
            "text": cm.get("text", ""),
            "reply": write_reply(caption, cm.get("text", ""), cm.get("username", "")),
            "found_at": now.isoformat(),
        }
        seen[cid] = c
        _send(c, cid)
        save_state(state)  # 한 건마다 저장
        print(f"[comments] @{c['username']} 댓글 답글 초안 전송")
    if len(new) > MAX_NEW:
        print(f"[comments] 나머지 {len(new) - MAX_NEW}개는 내일 보낼게요")
    save_state(state)


# ---------- 버튼 처리 (poll.py가 부름) ----------

def is_mine(data):
    return (data or "").startswith(PREFIX)


def handle(data):
    try:
        cid, value = data[len(PREFIX):].split("|")
    except ValueError:
        return "알 수 없는 버튼이에요"
    state = load_state()
    c = state["comments"].get(cid)
    if not c or "reply" not in c:
        return "댓글 정보를 찾을 수 없어요"
    if c["status"] not in ("pending", "failed"):
        return f"이미 처리했어요 ({STATUS_LABEL[c['status']]})"

    if value == "ok":
        c.pop("error", None)
        try:
            instagram.reply_comment(cid, c["reply"])
            c["status"] = "posted"
            c["posted_at"] = datetime.now(draft.KST).isoformat()
            note = "답글을 올렸어요!"
        except Exception as e:
            c["status"] = "failed"
            c["error"] = str(e)
            note = "답글 올리기 실패, 메시지를 확인해 주세요"
    elif value == "again":
        c["reply"] = write_reply(c.get("caption", c.get("post_title", "")), c["text"], c["username"], avoid=c["reply"])
        note = "다른 답글로 바꿨어요"
    elif value == "skip":
        c["status"] = "skipped"
        note = "이 댓글은 건너뛸게요"
    else:
        return "알 수 없는 버튼이에요"
    save_state(state)
    _refresh(c, cid)
    return note


if __name__ == "__main__":
    try:
        check()
    except Exception as e:
        print(f"[comments] 실패: {e}")
        hint = ""
        if "permission" in str(e).lower() or "권한" in str(e):
            hint = "\n(인스타 토큰에 댓글 관리 권한 instagram_business_manage_comments 가 필요해요)"
        try:
            telegram.send_text(f"⚠️ 댓글 확인 실패: {e}{hint}")
        except Exception:
            pass
        sys.exit(1)
