"""카드뉴스 초안 한 건의 생성·저장·텔레그램 표시를 담당한다.

초안은 drafts/<날짜>/ 폴더에 저장된다.
  draft.json      대본·상태
  bg1~4.jpg       제미나이 배경 사진 (표지 + 본문 3장)
  card1~5.jpg     글씨까지 얹은 완성 카드
status: pending(승인 대기) → approved(승인) → published(게시 완료)
        또는 skipped(건너뜀·승인 없음) / failed(게시 실패)
"""

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import images
import instagram
import render
import telegram
import trends
import writer

KST = timezone(timedelta(hours=9))
DRAFT_DIR = Path(__file__).resolve().parent.parent / "drafts"
THEME = "A"           # gil이 고른 디자인: A안 뉴스 속보형
PUBLISH_HOUR = 19     # 하루 한 번, 저녁 7시 게시
CTA = ["저장해두고", "가족한테도 알려주세요"]

STATUS_LABEL = {
    "pending": "⏳ 승인 대기 중",
    "approved": "✅ 승인됨 (저녁 7시에 게시)",
    "published": "🎉 게시 완료",
    "skipped": "⏭ 안 올림",
    "failed": "⚠️ 게시 실패",
}


# ---------- 저장 ----------

def folder(draft_id):
    return DRAFT_DIR / draft_id


def load(draft_id):
    p = folder(draft_id) / "draft.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def save(d):
    folder(d["id"]).mkdir(parents=True, exist_ok=True)
    (folder(d["id"]) / "draft.json").write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")


def all_drafts():
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(DRAFT_DIR.glob("*/draft.json"))]


def open_drafts():
    return [d for d in all_drafts() if d.get("status") in ("pending", "approved", "failed")]


def recent_issues(n=14):
    issues = []
    for d in all_drafts()[-n:]:
        issues.append(d.get("issue", ""))
        issues += d.get("rejected_issues", [])
    return [x for x in dict.fromkeys(issues) if x]


def card_paths(d):
    return [folder(d["id"]) / f"card{i}.jpg" for i in range(1, 6)]


def publish_time(d):
    return datetime.fromisoformat(d["publish_at"])


# ---------- 내용 만들기 ----------

def _handle():
    try:
        return "@" + instagram.username()
    except Exception as e:
        print(f"[draft] 인스타 계정 이름 못 가져옴: {e}")
        return os.environ.get("INSTAGRAM_HANDLE", "").strip()


def _fill_script(d, avoid=()):
    collected = trends.collect()
    print(f"[draft] 이슈 수집: { {k: len(v) for k, v in collected.items()} }")
    post = writer.write_cards(collected, list(recent_issues()) + list(avoid))
    print(f"[draft] 이슈: {post['issue']} / 표지: {post['title']}")
    d.update(post)


def _fill_photos(d):
    prompts = [d["cover_image_prompt"]] + [b["image_prompt"] for b in d["body"]]
    notes = []
    for i, prompt in enumerate(prompts, 1):
        data, note = images.get_image(prompt, d.get("photo_query", ""))
        p = folder(d["id"]) / f"bg{i}.jpg"
        if data:
            p.write_bytes(data)
        elif p.exists():
            p.unlink()
        notes.append(note)
    d["image_note"] = ", ".join(f"{i}번 {n}" for i, n in enumerate(notes, 1))


def render_cards(d):
    card = {
        "label": d["kind"],
        "title": d["title"],
        "highlight": d["highlight"],
        "body": [{"head": b["head"], "lines": b["lines"], "highlight": b["highlight"]} for b in d["body"]],
        "cta": d.get("cta") or CTA,
        "handle": d.get("handle", ""),
    }
    bgs = [folder(d["id"]) / f"bg{i}.jpg" for i in range(1, 5)]
    photos = [str(p) if p.exists() else None for p in bgs] + [None]
    render.render(card, photos, folder(d["id"]), THEME)


def create(now=None):
    now = now or datetime.now(KST)
    d = {
        "id": now.strftime("%Y%m%d"),
        "created_at": now.isoformat(),
        "publish_at": now.replace(hour=PUBLISH_HOUR, minute=0, second=0, microsecond=0).isoformat(),
        "status": "pending",
        "handle": _handle(),
    }
    folder(d["id"]).mkdir(parents=True, exist_ok=True)
    _fill_script(d)
    _fill_photos(d)
    render_cards(d)
    save(d)
    return d


def rewrite(d):
    """다른 이슈로 처음부터 다시 만든다."""
    d["rejected_issues"] = [x for x in d.get("rejected_issues", []) + [d.get("issue", "")] if x][-10:]
    _fill_script(d, avoid=d["rejected_issues"])
    _fill_photos(d)
    render_cards(d)
    save(d)


def retext(d):
    """이슈·사진은 그대로, 대본만 새로 쓴다."""
    post = writer.rewrite_cards(d)
    for b_new, b_old in zip(post["body"], d["body"]):  # 사진은 그대로 쓰므로 프롬프트도 유지
        b_new["image_prompt"] = b_old["image_prompt"]
    post.pop("cover_image_prompt", None)
    d.update(post)
    render_cards(d)
    save(d)


def new_photos(d):
    _fill_photos(d)
    render_cards(d)
    save(d)


def ig_caption(d):
    return (d["caption"].strip() + "\n\n" + " ".join(d.get("hashtags", []))).strip()


# ---------- 텔레그램 표시 ----------

def summary(d):
    when = publish_time(d)
    lines = [
        f"🗞 {when:%m/%d} 카드뉴스 · 저녁 {when:%H}시 게시 예정",
        f"상태: {STATUS_LABEL[d['status']]}",
        "",
        f"🔥 이슈: {d.get('issue', '')} ({d.get('kind', '')})",
        f"📌 표지: {' / '.join(d.get('title', []))}",
        f"🖼 사진: {d.get('image_note', '')}",
        "",
        "✍️ 캡션",
        ig_caption(d),
    ]
    if d.get("permalink"):
        lines += ["", f"🔗 {d['permalink']}"]
    if d.get("error"):
        lines += ["", f"⚠️ {d['error'][:300]}"]
    if d["status"] == "pending":
        lines += ["", "✅ 승인을 눌러야 저녁 7시에 올라가요. 승인이 없으면 오늘은 안 올려요.",
                  "(버튼은 20분마다 확인해요)"]
    return "\n".join(lines)


def _btn(d, label, value):
    return {"text": label, "callback_data": f"{d['id']}|{value}"}


def keyboard(d):
    if d["status"] == "failed":
        return [[_btn(d, "🔁 다시 게시", "now"), _btn(d, "⏭ 안 올리기", "skip")]]
    if d["status"] == "approved":
        return [[_btn(d, "🚀 지금 게시", "now"), _btn(d, "↩️ 승인 취소", "undo")]]
    if d["status"] != "pending":
        return []
    return [
        [_btn(d, "✅ 승인", "ok"), _btn(d, "🚀 지금 게시", "now")],
        [_btn(d, "🔁 같은 이슈로 다시", "retext"), _btn(d, "🆕 새 이슈로", "rewrite")],
        [_btn(d, "🖼 사진 다시", "photo"), _btn(d, "⏭ 안 올리기", "skip")],
    ]


def send(d):
    """카드 5장 묶음 + 버튼 달린 설명 메시지를 새로 보낸다."""
    old = d.get("message")
    if old:
        try:
            telegram.edit_draft(old, "↓ 아래 새 초안으로 바뀌었어요", [])
        except RuntimeError as e:
            print(f"[draft] 옛 메시지 정리 실패: {e}")
    telegram.send_album([(p.name, p.read_bytes()) for p in card_paths(d)])
    msg = telegram.send_text(summary(d), keyboard(d))
    d["message"] = {"message_id": msg["message_id"], "has_photo": False}
    save(d)


def refresh(d):
    if d.get("message"):
        telegram.edit_draft(d["message"], summary(d), keyboard(d))
