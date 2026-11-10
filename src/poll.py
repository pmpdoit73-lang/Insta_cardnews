"""10분마다 실행: 텔레그램 버튼 눌림을 반영하고, 게시 시각(07:00·17:30)이 되면 카드뉴스를 인스타에 올린다.
새 댓글에는 자동으로 답글을 단다 (comments.py). 밤 9시 이후엔 하루 한 번 숫자 보고서 (insights.py).
아침 8시 이후엔 하루 한 번 소통 안내, gil이 게시물 캡처를 보내면 맞춤 댓글 초안 (engage.py).
07:00 목록형은 릴스(영상), 17:30 인포그래픽형은 캐러셀(사진 넘기기)로 올린다.

승인(✅)을 안 눌러도 게시 시각이 되면 올린다. ⏭ 안 올리기를 누른 회차만 건너뛴다.

실행: python src/poll.py
"""

import sys
from datetime import datetime, timedelta
from pathlib import Path

import comments
import draft
import engage
import hosting
import insights
import instagram
import telegram
import threads_promo
import video

OFFSET_FILE = Path(__file__).resolve().parent.parent / "state" / "telegram_offset.txt"
LATE_LIMIT = timedelta(hours=2)  # 게시 시각보다 이만큼 넘게 늦으면 올리지 않음


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
    if draft.is_reel(d):  # 목록형: 카드를 15초 릴스로 (2026-11-04 gil 요청, 11-06부터 배경음악·첫 화면 문구)
        path = draft.make_reel(d)
        url = hosting.upload_temp(path.read_bytes(), f"{d['id']}-reel.mp4")
        media_id, link = instagram.post_reel(url, draft.ig_caption(d))
    else:
        urls = [hosting.upload_temp(p.read_bytes(), f"{d['id']}-{p.name}") for p in draft.card_paths(d)]
        media_id, link = instagram.post_carousel(urls, draft.ig_caption(d))
    d["instagram_id"] = media_id
    d["permalink"] = link
    d["status"] = "published"
    d["published_at"] = datetime.now(draft.KST).isoformat()
    share_story(d)
    promote_on_threads(d)


def promote_on_threads(d):
    """총정리표는 주 3회 쓰레드에도 홍보 글 (threads_promo.py). 실패해도 게시는 성공으로 둔다."""
    if not threads_promo.should_post(d, datetime.now(draft.KST)):
        return
    try:
        first = draft.card_paths(d)[0]
        url = hosting.upload_temp(first.read_bytes(), f"{d['id']}-threads.jpg")
        d["threads_promo_id"] = threads_promo.post(url, threads_promo.text_for(d))
        print(f"[poll] {d['id']} 쓰레드 홍보 글 완료")
    except Exception as e:
        d["threads_promo_error"] = str(e)[:300]
        print(f"[poll] {d['id']} 쓰레드 홍보 글 실패: {e}")


def share_story(d):
    """새 게시물 표지를 스토리에도 올린다 (2026-11-06 gil 요청, 조회수 개선 4단계).
    팔로워 화면 맨 위에 떠서 첫 반응을 늘린다. 실패해도 게시는 성공으로 둔다."""
    if d.get("story_id"):
        return
    try:
        path = video.story_image(draft.card_paths(d)[0], draft.folder(d["id"]) / "story.jpg")
        url = hosting.upload_temp(path.read_bytes(), f"{d['id']}-story.jpg")
        d["story_id"] = instagram.post_story(url)
        d.pop("story_error", None)
        print(f"[poll] {d['id']} 스토리 공유 완료")
    except Exception as e:
        d["story_error"] = str(e)[:300]
        print(f"[poll] {d['id']} 스토리 공유 실패: {e}")


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
        story = "📲 스토리에도 공유했어요" if d.get("story_id") else "⚠️ 스토리 공유는 실패했어요 (게시물은 정상)"
        if d.get("threads_promo_id"):
            story += "\n🧵 쓰레드에도 홍보 글을 올렸어요"
        telegram.send_text(f"🎉 인스타에 올렸어요\n{d.get('permalink', '')}\n{story}")


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
        msg = f"승인! {draft.time_label(draft.publish_time(d))}에 올릴게요"
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
        msg = u.get("message")
        if msg and str(msg.get("chat", {}).get("id")) == allowed and engage.wants_reply(msg):
            try:  # gil이 보낸 게시물 캡처·캡션 → 맞춤 댓글 초안 (engage.py)
                engage.reply_to(msg)
            except Exception as e:
                print(f"[poll] 맞춤 댓글 실패: {e}")
                telegram.send_text(f"⚠️ 맞춤 댓글을 못 만들었어요: {str(e)[:150]}")
            write_offset(offset)
            continue
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
        if now - draft.publish_time(d) > LATE_LIMIT:
            d["status"] = "skipped"
            draft.save(d)
            draft.refresh(d)
            print(f"[poll] {d['id']} 예정 시간이 너무 지나서 안 올림")
        else:
            try_publish(d)


if __name__ == "__main__":
    failed = False
    try:
        process_buttons()
        process_schedule()
    except Exception as e:
        failed = True
        print(f"[poll] 실패: {e}")
        try:
            telegram.send_text(f"⚠️ 버튼 처리 중 오류: {e}")
        except Exception:
            pass
    try:  # 댓글 답글은 게시와 따로: 실패해도 게시 쪽엔 영향 없게, 알림 없이 로그만
        comments.process()
    except Exception as e:
        print(f"[poll] 댓글 답글 실패: {e}")
    try:  # 하루 한 번 아침 소통 안내 (8시 이후 첫 실행, engage.py)
        engage.maybe_send()
    except Exception as e:
        print(f"[poll] 소통 안내 실패: {e}")
    try:  # 하루 한 번 숫자 보고서 (21시 이후 첫 실행)
        insights.maybe_report()
    except Exception as e:
        print(f"[poll] 숫자 보고서 실패: {e}")
    if failed:
        sys.exit(1)
