"""참고 계정에서 '평소보다 몇 배 터진' 릴스를 찾아 공식을 뽑는다 (2026-11-12 gil 요청, /ig-viral 반영).

원래 스킬(Jakeschincariol/instagram-agent-skill 의 ig-viral, MIT)의 핵심 생각:
- 조회수 자체는 증거가 아님. 팔로워 200만 계정의 40만 회는 평범한 날일 뿐.
- 그래서 '그 계정 평소(최근 릴스 조회수 중간값)의 몇 배인지'로 줄 세운다. 3배 넘으면 신호, 1.5배 아래는 평소.
- 남의 영상·문장은 베끼지 않고 '공식(첫 문구 모양)'만 가져온다.
- 자동으로 긁어 오지 않는다 (인스타 약관 위반·계정 정지 위험). 사람이 보고 캡처한 것만 읽는다.

쓰는 법 (텔레그램 인스타 봇):
  참고 계정 프로필 → 릴스 탭(조회수가 보이는 화면)을 캡처해서, 사진 설명에 '벤치'라고 적어 보낸다.
  → 10분 안에 그 계정 평소 조회수, 3배 넘게 터진 릴스, 쓰인 훅 공식, '우리 버전' 문구를 답장.
  → 결과는 state/swipe.json에 쌓이고, writer.py가 릴스 첫 화면 문구를 쓸 때 '요즘 터진 공식'으로 참고한다.

인스타 로그인 방식 API(graph.instagram.com)엔 남의 계정을 조회하는 기능(business discovery)이 없어서 캡처로 받는다.
"""

import base64
import html
import json
import re
import statistics
from datetime import datetime

import draft
import telegram
import writer

KEYWORDS = ("벤치", "터진", "viral", "바이럴")
OUTLIER, NORMAL = 3.0, 1.5
KEEP = 300

FORMULA_NAMES = dict(
    (int(m.group(1)), m.group(2).strip())
    for m in re.finditer(r"^(\d+)\. ([^—\n]+)—", writer.HOOK_FORMULAS, re.M)
)

SCHEMA = {
    "type": "object",
    "properties": {
        "account": {"type": "string", "description": "캡처에 보이는 계정 아이디 (@ 없이). 안 보이면 빈 문자열"},
        "reels": {
            "type": "array",
            "description": "캡처에 보이는 릴스 하나하나 (조회수가 보이는 것만, 왼쪽 위부터 순서대로)",
            "items": {
                "type": "object",
                "properties": {
                    "views": {"type": "integer",
                              "description": "조회수를 숫자로 ('1.2만' → 12000, '3,456' → 3456, '1.1M' → 1100000)"},
                    "cover_text": {"type": "string",
                                   "description": "썸네일에 보이는 글씨 그대로 (없으면 빈 문자열)"},
                    "formula": {"type": "integer",
                                "description": "cover_text가 해당하는 훅 공식 번호 1~26. 글씨가 없거나 어디에도 안 맞으면 0"},
                    "our_hook": {"type": "string",
                                 "description": "같은 공식으로 우리 계정(가전·주방 살림 꿀팁)에 맞게 새로 쓴 첫 화면 문구 "
                                                "16자 이내. 원래 문장을 베끼지 말 것. 글씨가 없으면 빈 문자열"},
                },
                "required": ["views", "cover_text", "formula", "our_hook"],
                "additionalProperties": False,
            },
        },
        "note": {"type": "string", "description": "캡처가 릴스 탭이 아니거나 조회수가 안 보이면 그 이유 한 줄, 아니면 빈 문자열"},
    },
    "required": ["account", "reels", "note"],
    "additionalProperties": False,
}


def wants(message):
    """'벤치' 같은 말과 함께 보낸 캡처 사진이면 이 모듈이 처리한다."""
    note = (message.get("caption") or message.get("text") or "").lower()
    return bool(message.get("photo")) and any(k in note for k in KEYWORDS)


def _load():
    try:
        return json.loads(writer.SWIPE_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return {"reels": []}


def _save(state):
    state["reels"] = state["reels"][-KEEP:]
    writer.SWIPE_FILE.parent.mkdir(exist_ok=True)
    writer.SWIPE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def rank(reels):
    """조회수 목록에 '평소(중간값)의 몇 배'를 붙인다. 중간값과 정렬된 목록을 돌려준다."""
    views = [r["views"] for r in reels if r.get("views", 0) > 0]
    if len(views) < 4:
        return 0, []
    median = statistics.median(views)
    out = [dict(r, multiple=round(r["views"] / median, 1)) for r in reels if r.get("views", 0) > 0]
    return median, sorted(out, key=lambda r: -r["multiple"])


def _name(n):
    return f"{n}번 {FORMULA_NAMES.get(n, '')}".strip() if n else "공식 없음"


def summary_lines(state):
    """지금까지 모은 '터진' 게시물의 공식 순위."""
    hits = [r for r in state["reels"] if r.get("multiple", 0) >= OUTLIER]
    accounts = {r.get("account") for r in state["reels"]}
    if not hits:
        return [f"📚 지금까지 {len(accounts)}개 계정, 릴스 {len(state['reels'])}개 · 3배 넘게 터진 건 아직 없어요"]
    counts = {}
    for r in hits:
        if r.get("formula"):
            counts[r["formula"]] = counts.get(r["formula"], 0) + 1
    top = sorted(counts.items(), key=lambda kv: -kv[1])[:3]
    lines = [f"📚 지금까지 {len(accounts)}개 계정, 릴스 {len(state['reels'])}개 중 터진 것 {len(hits)}개"]
    if top:
        lines.append("많이 쓰인 공식: " + ", ".join(f"{_name(f)} ×{n}" for f, n in top))
    if len(hits) < 10:
        lines.append("(아직 적어서 참고만 해요. 계정 6~12개쯤 모이면 믿을 만해져요)")
    return lines


def analyze(message):
    """캡처 한 장을 읽어 순위를 매기고, 기록하고, 답장한다."""
    data = telegram.download_file(message["photo"][-1]["file_id"])
    content = [
        {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                     "data": base64.b64encode(data).decode()}},
        {"type": "text", "text": (
            "인스타 계정의 릴스 탭 캡처야. 보이는 릴스마다 조회수와 썸네일 글씨를 읽고, "
            "그 글씨가 아래 훅 공식 중 몇 번인지 골라. 그리고 같은 공식으로 우리 계정에 맞는 문구를 새로 써.\n"
            "숫자는 보이는 그대로만 읽고 지어내지 마. 안 보이는 건 빼.\n\n" + writer.HOOK_FORMULAS)},
    ]
    out = writer._ask(content, SCHEMA, system=writer.PERSONA)
    account = (out.get("account") or "").lstrip("@") or "알 수 없음"
    median, ranked = rank(out.get("reels", []))
    if not ranked:
        reason = out.get("note") or "조회수가 보이는 릴스가 4개보다 적어요"
        telegram.send_text(f"⚠️ 분석 못 했어요: {reason}\n프로필의 릴스 탭(▶ 조회수가 보이는 화면)을 캡처해 주세요.",
                           reply_to=message.get("message_id"))
        return

    state = _load()
    today = datetime.now(draft.KST).strftime("%Y-%m-%d")
    seen = {(r.get("account"), r.get("views"), r.get("cover_text")) for r in state["reels"]}
    for r in ranked:
        key = (account, r["views"], r["cover_text"])
        if key not in seen:
            state["reels"].append({"date": today, "account": account, "median": median, **r})
    _save(state)

    lines = [f"📈 @{html.escape(account)} 릴스 {len(ranked)}개 · 평소(중간값) {int(median):,}회"]
    hits = [r for r in ranked if r["multiple"] >= OUTLIER]
    if hits:
        lines.append(f"🔥 평소보다 {OUTLIER:g}배 넘게 터진 릴스")
        for r in hits[:5]:
            lines.append(f"• {r['multiple']}배 · {r['views']:,}회 · '{html.escape(r['cover_text'] or '(글씨 없음)')}'")
            lines.append(f"   공식: {_name(r['formula'])}")
            if r.get("our_hook"):
                lines.append(f"   우리 버전: <code>{html.escape(r['our_hook'])}</code>")
    else:
        best = ranked[0]
        lines.append(f"😐 {OUTLIER:g}배 넘는 릴스는 없어요 (최고 {best['multiple']}배). "
                     "이 계정의 평소 수준이라 배울 점은 적어요.")
    lines += [""] + summary_lines(state)
    lines.append("→ 내일 릴스 첫 화면 문구를 쓸 때 '터진 공식'을 우선 참고해요.")
    telegram.send_text("\n".join(lines), html=True, reply_to=message.get("message_id"))


if __name__ == "__main__":
    print("\n".join(summary_lines(_load())))
