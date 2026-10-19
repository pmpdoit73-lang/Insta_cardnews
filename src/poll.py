"""20분마다 실행: 텔레그램 버튼 눌림을 반영하고, 저녁 7시가 되면 승인된 카드뉴스를 인스타에 올린다.

쓰레드 자동화와 다른 점: 승인(✅)을 눌러야만 올린다. 7시까지 승인이 없으면 오늘은 안 올린다.

실행: python src/poll.py
"""

import sys
from datetime import datetime, timedelta
from pathlib import Path

import draft
import hosting
import instagram
import telegram

OFFSET_FILE = Path(__file__).resolve().parent.parent / "state" / "telegram_offset.txt"
LATE_LIMIT = timedelta(hours=4)  # 승인된 글이라도 7시보다 이만큼 넘게 늦으면 올리지 않음 (23시까지)


def read_offset():
    """저장된 위치를 읽는다. 봇이 바뀌었으면 처음(0)부터."""
    try:
        bot, value = OFFSET_FILE.read_text().strip().split(":")
        return int(value) if bot == telegram.bot_id() else 0
    except (FileNotFoundError, ValueError):
        return 0


def write_offset(value):
    OFFSET_FILE.parent.mkdir(exist_ok=True)
    OFFSET_FILE.write_text(f"{telegram.bot_id()}:{value}")


# ---------- 게시 ----------

def publish(d):
    urls = [hosting.upload_temp(p.read_bytes(), f"{d['id']}-{p.name}") for p in draft.card_paths(d)]
    media_id, link = instagram.post_carousel(urls, draft.ig_caption(d))
    d["instagram_id"] = media_id
    d["permalink"] = link
    d["status"] = "published"
    d["published_at"] = datetime.now(draft.KST).isoformat()


def try_publish(d):
    d.pop("error", None)
    try:
        publish(d)
        print(f"[poll] {d['id']} 게시 완료: {d.get('permalink')}")
    except Exception as e:
        print(f"[poll] {d['id']} 게시 실패: {e}")
        d["status"] = "failed"
        d["error"] = str(e)
    draft.save(d)
    draft.refresh(d)
    if d["status"] == "published":
        telegram.send_text(f"🎉 인스타에 올렸어요\n{d.get('permalink', '')}")


# ---------- 버튼 처리 ----------

def handle(callback):
    try:
        draft_id, value = callback["data"].split("|")
    except ValueError:
        return "알 수 없는 버튼이에요"
    d = draft.load(draft_id)
    if not d:
        return "초안을 찾을 수 없어요"
    if d["status"] == "failed" and value not in ("now", "skip"):
        return "게시 실패한 초안은 🔁 다시 게시 또는 ⏭ 안 올리기만 돼요"
    if d["status"] not in ("pending", "approved", "failed"):
        return f"이미 처리된 초안이에요 ({draft.STATUS_LABEL[d['status']]})"

    if value == "ok":
        d["status"] = "approved"
        msg = "승인! 저녁 7시에 올릴게요"
    elif value == "undo":
        d["status"] = "pending"
        msg = "승인 취소"
    elif value == "skip":
        d["status"] = "skipped"
        msg = "오늘은 안 올릴게요"
    elif value == "now":
        try_publish(d)
        return "게시 완료!" if d["status"] == "published" else "게시 실패, 메시지를 확인해 주세요"
    elif value in ("rewrite", "retext", "photo"):
        {"rewrite": draft.rewrite, "retext": draft.retext, "photo": draft.new_photos}[value](d)
        draft.send(d)
        return {"rewrite": "새 이슈로 새로 만들었어요", "retext": "같은 이슈로 글만 새로 썼어요",
                "photo": "사진을 바꿨어요"}[value]
    else:
        return "알 수 없는 버튼이에요"

    draft.save(d)
    draft.refresh(d)
    return msg


def process_buttons():
    offset = read_offset()
    allowed = str(telegram._chat_id())
    for u in telegram.get_updates(offset):
        offset = max(offset, u["update_id"] + 1)
        cb = u.get("callback_query")
        if not cb or str(cb.get("from", {}).get("id")) != allowed:  # 다른 사람이 누른 버튼·일반 대화는 무시
            write_offset(offset)
            continue
        try:
            note = handle(cb)
        except Exception as e:
            print(f"[poll] 버튼 처리 실패: {e}")
            note = f"처리 실패: {str(e)[:150]}"
        telegram.answer(cb["id"], note)
        write_offset(offset)  # 한 건 처리할 때마다 저장해서 중간에 멈춰도 중복 처리 안 되게
    write_offset(offset)


# ---------- 시간 확인 ----------

def process_schedule():
    now = datetime.now(draft.KST)
    for d in draft.open_drafts():
        if d["status"] == "failed" or draft.publish_time(d) > now:
            continue
        if d["status"] == "pending":  # 승인 없이 시간이 됨 → 안 올림
            d["status"] = "skipped"
            draft.save(d)
            draft.refresh(d)
            telegram.send_text("⏭ 7시까지 승인이 없어서 오늘 카드뉴스는 안 올렸어요.")
            print(f"[poll] {d['id']} 승인 없음 → 안 올림")
        elif now - draft.publish_time(d) > LATE_LIMIT:
            d["status"] = "skipped"
            draft.save(d)
            draft.refresh(d)
            print(f"[poll] {d['id']} 예정 시간이 너무 지나서 안 올림")
        else:
            try_publish(d)


if __name__ == "__main__":
    try:
        process_buttons()
        process_schedule()
    except Exception as e:
        print(f"[poll] 실패: {e}")
        try:
            telegram.send_text(f"⚠️ 버튼 처리 중 오류: {e}")
        except Exception:
            pass
        sys.exit(1)
