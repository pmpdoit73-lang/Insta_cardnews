"""카드뉴스 초안 한 건의 생성·저장·텔레그램 표시를 담당한다.

초안은 drafts/<날짜>/ 폴더에 저장된다.
  draft.json      대본·상태
  bg1~N.jpg       목록형: 제미나이 배경 사진 (표지 + 팁 6~8장 + 마무리, 같은 세트장)
  icon1~N.jpg     인포그래픽형: 칸마다 들어갈 만화풍 그림 (7개 또는 10개)
  card1~N.jpg     글씨까지 얹은 완성 카드 (목록형 8~10장, 인포그래픽형 2장)
  reel.mp4        목록형 릴스 영상 (카드로 그때그때 다시 만들 수 있어서 저장소에는 안 올림)
format: list(목록형) 또는 info(인포그래픽형 총정리표). 회차별로 SLOT_FORMAT에서 정함
status: pending(승인 대기) → approved(승인) → published(게시 완료)
        또는 skipped(건너뜀·승인 없음) / failed(게시 실패)
"""

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import images
import music
import instagram
import render
import telegram
import trends
import video
import writer

KST = timezone(timedelta(hours=9))
DRAFT_DIR = Path(__file__).resolve().parent.parent / "drafts"
SLOTS = [(7, 0), (17, 30)]  # 하루 두 번 게시 시각 (시, 분), 2026-10-23 gil 요청으로 3번 → 2번
SLOT_FORMAT = {(17, 30): "info"}  # 회차별 형식, 없으면 목록형. 2026-10-30 gil 요청으로 17:30은 인포그래픽형
DRAFT_LEAD = timedelta(minutes=30)    # 게시 시각이 이보다 가까우면 그다음 회차 초안을 만든다
SLOGAN = "주방의 질을 높이는 살림 꿀팁"  # 마지막 장 브랜드 한 줄

STATUS_LABEL = {
    "pending": "⏳ 대기 중 (그대로 두면 예정 시각에 자동 게시)",
    "approved": "✅ 승인됨 (예정 시각에 게시)",
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


def recent_issues(n=30):
    issues = []
    for d in all_drafts()[-n:]:
        issues.append(d.get("issue", ""))
        issues += d.get("rejected_issues", [])
    return [x for x in dict.fromkeys(issues) if x]


def _numbered(d, prefix):
    """card1.jpg, card2.jpg … card10.jpg를 번호 순서대로 (card10이 card2 앞에 오지 않게)."""
    return sorted(folder(d["id"]).glob(f"{prefix}*.jpg"), key=lambda p: int(p.stem[len(prefix):]))


def card_paths(d):
    return _numbered(d, "card")


def publish_time(d):
    return datetime.fromisoformat(d["publish_at"])


def time_label(when):
    """07:00 → '오전 7:00', 17:30 → '오후 5:30'"""
    ampm = "오전" if when.hour < 12 else "오후"
    hour = when.hour if when.hour <= 12 else when.hour - 12
    return f"{ampm} {hour}:{when.minute:02d}"


def next_slot(now=None):
    """초안을 만들 다음 게시 시각 (now + 30분 이후의 첫 회차)."""
    now = now or datetime.now(KST)
    for days in (0, 1):
        day = now + timedelta(days=days)
        for h, m in SLOTS:
            slot = day.replace(hour=h, minute=m, second=0, microsecond=0)
            if slot > now + DRAFT_LEAD:
                return slot


def format_for(slot):
    return SLOT_FORMAT.get((slot.hour, slot.minute), "list")


def is_info(d):
    return d.get("format") == "info"


def is_reel(d):
    """목록형은 릴스(영상)로 올린다. 2026-11-04 gil 요청. 인포그래픽형은 캐러셀 그대로."""
    return not is_info(d)


def reel_hook(d):
    """릴스 맨 위에 띄울 질문형 문구. 예전 초안처럼 hook이 없으면 표지 제목으로."""
    return (d.get("hook") or " ".join(d.get("title", []))).strip()


def make_reel(d):
    """카드로 릴스 영상(reel.mp4)을 만든다. 카드가 바뀌어도 늘 최신 카드로 다시 만든다.
    배경음악은 초안 id로 고르므로 미리보기와 실제 게시 영상이 같은 곡 (2026-11-06 gil 요청)."""
    return video.make_reel(card_paths(d), folder(d["id"]) / "reel.mp4", reel_hook(d), music.pick(d["id"]),
                           loop=d.get("loop_line", ""), extra=bool(d.get("stake")))


def slot_id(slot):
    return slot.strftime("%Y%m%d-%H%M")


def for_slot(slot):
    """그 회차 초안 (예전 방식 id로 만든 초안도 게시 시각이 같으면 찾는다)."""
    d = load(slot_id(slot))
    if d:
        return d
    return next((x for x in all_drafts() if publish_time(x) == slot), None)


# ---------- 내용 만들기 ----------

def _handle():
    if not os.environ.get("INSTAGRAM_ACCESS_TOKEN", "").strip():  # 인스타 연결 전
        return os.environ.get("INSTAGRAM_HANDLE", "").strip()
    try:
        return "@" + instagram.username()
    except Exception as e:
        print(f"[draft] 인스타 계정 이름 못 가져옴: {e}")
        return os.environ.get("INSTAGRAM_HANDLE", "").strip()


def _fill_script(d, avoid=()):
    collected = trends.collect()
    print(f"[draft] 이슈 수집: { {k: len(v) for k, v in collected.items()} }")
    avoid = list(recent_issues()) + list(avoid)
    post = writer.write_info(collected, avoid) if is_info(d) else writer.write_cards(collected, avoid)
    print(f"[draft] 이슈: {post['issue']} / 표지: {post['title']}")
    d.update(post)


def _fill_icons(d):
    """인포그래픽형: 첫 그림을 먼저 만들고, 나머지는 첫 그림을 참고로 넣어 같은 그림체로 맞춘다."""
    for old in _numbered(d, "icon"):
        old.unlink()
    ref, notes = None, []
    for i, item in enumerate(d["items"], 1):
        data, note = images.get_icon(item["icon_prompt"], ref)
        if data:
            (folder(d["id"]) / f"icon{i}.jpg").write_bytes(data)
            ref = ref or data
        notes.append(note)
    made = notes.count("제미나이")
    d["image_note"] = f"그림 {len(notes)}개 중 제미나이 {made}개" + (f", 이모지 {len(notes) - made}개" if made < len(notes) else "")


def _fill_photos(d):
    """표지 사진을 먼저 만들고, 나머지는 표지를 참고 이미지로 넣어 같은 세트장으로 맞춘다."""
    for old in _numbered(d, "bg"):
        old.unlink()
    if is_info(d):
        _fill_icons(d)
        return
    prompts = [d["cover_image_prompt"]] + [t["image_prompt"] for t in d["tips"]] + [d["warning"]["image_prompt"]]
    scene, query = d.get("scene", ""), d.get("photo_query", "")
    ref, notes = None, []
    for i, prompt in enumerate(prompts, 1):
        data, note = images.get_image(prompt, query, scene, ref)
        if data:
            (folder(d["id"]) / f"bg{i}.jpg").write_bytes(data)
            if i == 1 and note == "제미나이":
                ref = data
        notes.append(note)
    if all(n == notes[0] for n in notes):
        d["image_note"] = f"{len(notes)}장 모두 {notes[0]}"
    else:
        d["image_note"] = ", ".join(f"{i}번 {n}" for i, n in enumerate(notes, 1))


def render_cards(d):
    if is_info(d):
        keys = ("top_badge", "title", "highlight", "basis", "items", "save_tile", "check",
                "footer_line", "footer_highlight", "warning", "save_line", "handle")
        card = {k: d.get(k, "") for k in keys} | {"slogan": SLOGAN}
        icons = [folder(d["id"]) / f"icon{i}.jpg" for i in range(1, len(d["items"]) + 1)]
        render.render_info(card, [str(p) if p.exists() else None for p in icons], folder(d["id"]))
        return
    card = {
        "label": d["kind"],
        "title": d["title"],
        "highlight": d["highlight"],
        "subtitle": d["subtitle"],
        "tips": [{"title": t["title"], "lines": t["lines"], "note": t.get("note", "")} for t in d["tips"]],
        "warning": {"title": d["warning"]["title"], "lines": d["warning"]["lines"]},
        "save_line": d["save_line"],
        "slogan": SLOGAN,
        "handle": d.get("handle", ""),
        "stake": d.get("stake"),  # 2026-11-12~ 2번 '왜' 카드 + 정리 카드 (예전 초안은 없음 → 그대로)
    }
    total = len(d["tips"]) + 2  # 사진 수 (표지 + 팁 + 마무리). 추가 카드 2장은 이 사진을 다시 씀
    bgs = [folder(d["id"]) / f"bg{i}.jpg" for i in range(1, total + 1)]
    render.render_list(card, [str(p) if p.exists() else None for p in bgs], folder(d["id"]))


def create(slot):
    d = {
        "id": slot_id(slot),
        "created_at": datetime.now(KST).isoformat(),
        "publish_at": slot.isoformat(),
        "status": "pending",
        "handle": _handle(),
        "format": format_for(slot),
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
    d["format"] = format_for(publish_time(d))  # 형식 정하기 전에 만든 회차도 지금 규칙대로
    for key in ("body", "cta", "tips", "items"):  # 예전 형식 흔적 지우기
        d.pop(key, None)
    _fill_script(d, avoid=d["rejected_issues"])
    _fill_photos(d)
    render_cards(d)
    save(d)


def retext(d):
    """이슈는 그대로, 대본을 새로 쓴다. 팁 개수가 같으면 사진도 그대로 쓴다."""
    if is_info(d):  # 항목이 바뀌면 그림도 바뀌어야 하므로 그림도 새로
        d.update(writer.rewrite_info(d))
        _fill_photos(d)
        render_cards(d)
        save(d)
        return
    post = writer.rewrite_cards(d)
    same_count = len(post["tips"]) == len(d.get("tips", []))  # 예전 5장 초안은 tips가 없어 사진도 새로
    if same_count:  # 사진은 그대로 쓰므로 프롬프트도 유지
        for t_new, t_old in zip(post["tips"], d["tips"]):
            t_new["image_prompt"] = t_old["image_prompt"]
        for key in ("cover_image_prompt", "scene"):
            post.pop(key, None)
        post["warning"]["image_prompt"] = d["warning"]["image_prompt"]
    for key in ("body", "cta"):  # 예전 5장 형식 흔적 지우기
        d.pop(key, None)
    d.update(post)
    if not same_count:
        _fill_photos(d)
    render_cards(d)
    save(d)


def new_photos(d):
    if "tips" not in d and not is_info(d):  # 예전 5장 초안: 새 형식으로 대본부터 다시
        retext(d)
        return
    _fill_photos(d)
    render_cards(d)
    save(d)


MAX_TAGS = 5  # 2026-11-06: 해시태그 10~15개 → 3~5개 (요즘 인스타는 캡션 키워드를 더 봄)


def ig_caption(d):
    return (d["caption"].strip() + "\n\n" + " ".join(d.get("hashtags", [])[:MAX_TAGS])).strip()


# ---------- 텔레그램 표시 ----------

def summary(d):
    when = publish_time(d)
    lines = [
        f"🗞 {when:%m/%d} {time_label(when)} 카드뉴스 게시 예정",
        f"상태: {STATUS_LABEL[d['status']]}",
        "",
        f"🔥 이슈: {d.get('issue', '')} ({d.get('kind', '')})",
        f"📌 표지: {' / '.join(d.get('title', []))}",
        f"🧩 형식: {'인포그래픽 총정리표 (사진 넘기기)' if is_info(d) else '목록형 (릴스 약 15초)'}",
        f"🗂 카드: {len(card_paths(d))}장" + (f" (항목 {len(d['items'])}개)" if is_info(d) and d.get("items")
                                           else f" (팁 {len(d['tips'])}개)" if d.get("tips") else ""),
        f"🖼 사진: {d.get('image_note', '')}",
    ]
    if is_reel(d):
        song = music.pick(d["id"])
        lines += [f"💬 첫 화면 문구: {reel_hook(d)}"]
        others = [o for o in d.get("hook_options", []) if o.get("text") != d.get("hook")]
        if others:  # 2026-11-12: 훅 공식 3개로 써 보고 점수 높은 것을 고름 (/ig-reel)
            lines += ["   다른 후보: " + " / ".join(f"{o['text']}({o.get('score', '')})" for o in others)]
        if d.get("loop_line"):
            lines += [f"🔁 마지막 화면 문구: {d['loop_line']}"]
        lines += [f"🎵 배경음악: {music.title(song) if song else '없음'}"]
    lines += [
        "",
        "✍️ 캡션",
        ig_caption(d),
    ]
    if d.get("permalink"):
        lines += ["", f"🔗 {d['permalink']}"]
    if d.get("error"):
        lines += ["", f"⚠️ {d['error'][:300]}"]
    if d["status"] == "pending":
        lines += ["", f"그대로 두면 {time_label(when)}에 자동으로 올라가요. 올리기 싫으면 ⏭ 안 올리기를 눌러주세요.",
                  "(버튼은 10분마다 확인해요)"]
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
        [_btn(d, "🖼 그림 다시" if is_info(d) else "🖼 사진 다시", "photo"), _btn(d, "⏭ 안 올리기", "skip")],
    ]


def send(d):
    """카드 묶음(최대 10장) + (목록형이면) 릴스 영상 + 버튼 달린 설명 메시지를 새로 보낸다."""
    old = d.get("message")
    if old:
        try:
            telegram.edit_draft(old, "↓ 아래 새 초안으로 바뀌었어요", [])
        except RuntimeError as e:
            print(f"[draft] 옛 메시지 정리 실패: {e}")
    telegram.send_album([(p.name, p.read_bytes()) for p in card_paths(d)])
    if is_reel(d):  # 실제로 올라갈 릴스 영상도 미리 보여 준다. 실패해도 초안은 그대로 보냄
        try:
            telegram.send_video(make_reel(d).read_bytes(), "▶️ 이 영상이 릴스로 올라가요")
        except Exception as e:
            print(f"[draft] 릴스 미리보기 실패: {e}")
    msg = telegram.send_text(summary(d), keyboard(d))
    d["message"] = {"message_id": msg["message_id"], "has_photo": False}
    save(d)


def refresh(d):
    if d.get("message"):
        telegram.edit_draft(d["message"], summary(d), keyboard(d))
