"""자동화가 '어디서 삐걱였는지' 기록해 두고, 일주일에 한 번 고칠 점을 제안한다 (2026-11-20 gil 요청).

가져온 생각: rebelytics/one-skill-to-rule-them-all 의 task-observer 스킬 (Eoghan Henn 외, CC BY 4.0).
원래는 Claude Code 작업 중 사용자의 정정·반복되는 불편을 기록해 두었다가 주간 검토 때 스킬을 고치는 '메타 스킬'.
여기서는 그 방식만 카드뉴스 봇에 옮겼다:
- 바로 고치지 않고 '기록 후 미루기'(log-and-defer). 고칠지 말지는 주간 검토에서 gil이 정한다.
- 자기 규칙 위반도 기록한다 (대본 검사에 걸린 것).
- 같은 규칙을 두 번 넘게 어기면 '말(프롬프트)로 더 타이르기'가 아니라 코드 검사·구조로 막자고 제안한다.
- 한 번뿐인 일은 규칙으로 만들지 않는다. 제안은 '문제 → 고칠 점 → 원칙' 모양으로.

무엇이 기록되나 (state/observations.json):
- gil이 누른 버튼: ⏭ 안 올리기, 🆕 새로 만들기, ✍️ 글만 다시, 📷 사진 다시  (= 초안이 마음에 안 들었다는 신호)
- 게시 실패와 그 이유
- 대본이 규칙 검사에 걸린 것 (writer.py)
- gil이 텔레그램에 '피드백 …'이라고 보낸 말 (예: '피드백 표지 글씨가 너무 길어')

일요일 21시 이후 한 번: 지난 7일 기록을 Claude가 묶어서 '고칠 점 제안 1~3개'를 텔레그램으로 보낸다.
제안은 자동으로 적용하지 않는다. 마음에 드는 게 있으면 Claude에게 '이거 적용해줘'라고 하면 된다.
지금 바로 받기: python src/observer.py
"""

import html
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FILE = ROOT / "state" / "observations.json"
KEEP = 400
REVIEW_DAY, REVIEW_HOUR = 6, 21  # 일요일 21시 이후
KEYWORDS = ("피드백", "의견", "관찰")

ACTION_LABEL = {
    "skip": "⏭ 안 올리기", "rewrite": "🆕 새로 만들기", "retext": "✍️ 글만 다시", "photo": "📷 사진 다시",
    "publish_failed": "❌ 게시 실패", "rule": "📏 대본 규칙 위반", "feedback": "🗣 gil 피드백",
}

SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string", "description": "이번 주 기록을 한두 문장으로 (무엇이 몇 번 반복됐는지)"},
        "proposals": {
            "type": "array",
            "description": "고칠 점 0~3개. 두 번 이상 반복된 것만. 한 번뿐인 일은 빼",
            "items": {
                "type": "object",
                "properties": {
                    "issue": {"type": "string", "description": "문제: 무엇이 몇 번, 어느 시간대(07:00/12:00/17:30)에서"},
                    "fix": {"type": "string", "description": "고칠 점: 구체적으로 무엇을 바꾸면 되는지 (대본 규칙, 코드 검사, 디자인 등)"},
                    "principle": {"type": "string", "description": "원칙: 다른 주제에도 통하는 한 줄"},
                    "structural": {"type": "boolean",
                                   "description": "같은 규칙 위반이 2번 넘게 반복돼 말로 타이르는 대신 코드 검사·구조로 막아야 하면 true"},
                },
                "required": ["issue", "fix", "principle", "structural"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["summary", "proposals"],
    "additionalProperties": False,
}


def _now():
    import draft
    return datetime.now(draft.KST)


def _load():
    try:
        return json.loads(FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return {"items": [], "last_review": ""}


def _save(state):
    state["items"] = state["items"][-KEEP:]
    FILE.parent.mkdir(exist_ok=True)
    FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def _slot(d):
    try:
        import draft
        return draft.publish_time(d).strftime("%H:%M")
    except Exception:
        return ""


def log(kind, detail="", d=None):
    """기록 한 줄. 기록이 실패해도 본 작업은 멈추지 않는다."""
    try:
        item = {"at": _now().strftime("%Y-%m-%d %H:%M"), "kind": kind, "detail": str(detail)[:300]}
        if d:
            item.update({"draft": d.get("id", ""), "slot": _slot(d), "format": d.get("format", "list"),
                         "title": " ".join(d.get("title", []))[:60], "hook": d.get("hook", "")[:40]})
        state = _load()
        state["items"].append(item)
        _save(state)
    except Exception as e:
        print(f"[observer] 기록 실패: {e}")


def wants(message):
    text = (message.get("text") or "").strip()
    return any(text.startswith(k) for k in KEYWORDS)


def note(message):
    """gil이 보낸 '피드백 …'을 기록하고 답장."""
    import telegram
    text = (message.get("text") or "").strip()
    for k in KEYWORDS:
        if text.startswith(k):
            text = text[len(k):].lstrip(" :·-")
            break
    if not text:
        telegram.send_text("'피드백' 뒤에 고쳤으면 하는 점을 적어 주세요. 예: 피드백 표지 글씨가 너무 길어",
                           reply_to=message.get("message_id"))
        return
    log("feedback", text)
    telegram.send_text("📝 기록했어요. 일요일 밤 '이번 주 고칠 점'에서 다른 기록과 묶어 제안할게요.",
                       silent=True, reply_to=message.get("message_id"))


def _week(state, now):
    since = (now - timedelta(days=7)).strftime("%Y-%m-%d %H:%M")
    return [x for x in state["items"] if x.get("at", "") >= since]


def _counts(items):
    counts = {}
    for x in items:
        counts[x["kind"]] = counts.get(x["kind"], 0) + 1
    return counts


def review():
    """지난 7일 기록으로 '고칠 점' 제안을 텔레그램에 보낸다. 보낸 글을 돌려준다."""
    import telegram
    import writer
    state = _load()
    now = _now()
    items = _week(state, now)
    state["last_review"] = now.strftime("%Y-%m-%d")
    _save(state)
    if not items:
        text = "🔍 이번 주 고칠 점: 기록된 문제가 없어요 (버튼 다시 누르기·게시 실패·규칙 위반·피드백 0건) 👍"
        telegram.send_text(text, silent=True)
        return text

    counts = _counts(items)
    rows = "\n".join(json.dumps(x, ensure_ascii=False) for x in items[-120:])
    out = writer._ask(
        "인스타 카드뉴스 자동화 봇의 지난 7일 '삐걱인 기록'이야. 한 줄에 하나.\n"
        "kind: skip=gil이 안 올리기, rewrite=새로 만들기, retext=글만 다시, photo=사진 다시 "
        "(모두 초안이 마음에 안 들었다는 신호), publish_failed=게시 실패, rule=대본이 규칙 검사에 걸림, "
        "feedback=gil이 직접 적은 의견(가장 중요).\n"
        "slot은 게시 시각 (07:00 목록형 릴스, 12:00 스킬형 릴스, 17:30 총정리표).\n\n"
        "규칙:\n"
        "- 두 번 이상 반복된 것, 또는 gil 피드백만 제안해. 한 번뿐인 일은 빼.\n"
        "- 같은 규칙 위반이 2번 넘게 나오면 '프롬프트에 더 강하게 쓰기' 대신 코드 검사·구조로 막자고 제안하고 structural=true.\n"
        "- 기록에 없는 원인은 지어내지 마. 근거가 약하면 '확인 필요'라고 써.\n"
        "- 쉬운 말로, 50대 초보자도 바로 이해하게.\n\n" + rows,
        SCHEMA, model=writer.LIGHT_MODEL)

    e = html.escape
    lines = ["🔍 <b>이번 주 고칠 점</b> (지난 7일 자동화 기록)",
             " · ".join(f"{ACTION_LABEL.get(k, k)} {n}" for k, n in sorted(counts.items(), key=lambda kv: -kv[1])),
             "", e(out["summary"])]
    for i, p in enumerate(out["proposals"][:3], 1):
        lines += ["", f"<b>{i}. {e(p['issue'])}</b>",
                  f"🔧 고칠 점: {e(p['fix'])}" + (" (코드로 막기)" if p["structural"] else ""),
                  f"📌 원칙: {e(p['principle'])}"]
    if not out["proposals"]:
        lines += ["", "반복된 문제는 없어요. 그대로 가도 돼요."]
    else:
        lines += ["", "자동으로 바꾸지 않아요. 적용하고 싶은 번호를 Claude에게 말해 주세요."]
    text = "\n".join(lines)
    telegram.send_text(text, html=True)
    return text


def maybe_review():
    """일요일 21시 이후 첫 실행 때 한 번 (poll.py가 부름)."""
    now = _now()
    if now.weekday() != REVIEW_DAY or now.hour < REVIEW_HOUR:
        return
    if _load().get("last_review") == now.strftime("%Y-%m-%d"):
        return
    review()


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    print(review())
