"""두 인스타 계정의 숫자 보고서를 하루 한 번 텔레그램으로 보낸다 (2026-11-06 gil 요청, 조회수 개선 2단계).

poll.py가 10분마다 부르지만 실제로는 하루 한 번(REPORT_HOUR시 이후 첫 실행)만 보낸다.
무엇을 바꿨더니 숫자가 어떻게 변했는지 보려고 날마다 기록도 state/insights.json에 남긴다.

보고서 내용 (계정마다):
- 팔로워 수 (어제 대비)
- 최근 7일 도달 중 비팔로워 비율 (추천으로 퍼지고 있는지 보는 숫자)
- 최근 게시물별 조회·도달·저장·공유 (릴스는 평균 시청 초)

필요한 권한: instagram_business_manage_insights. 없으면 보고서에 '통계 권한 없음'이라고 나온다.
지금 바로 받기: python src/insights.py  (Actions의 '통계 보고서 지금 받기')
"""

import json
import os
import sys
from datetime import datetime, timedelta

import comments
import draft
import instagram
import telegram
import threads_promo

STATE_FILE = comments.STATE_DIR / "insights.json"
REPORT_HOUR = 21     # 한국 시각 21시 이후 첫 실행 때 보냄
POSTS = 6            # 보고서에 넣을 최근 게시물 수
KEEP_DAYS = 60


def _load():
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return {"last": "", "history": {}}


def _save(state):
    STATE_FILE.parent.mkdir(exist_ok=True)
    for acc in state["history"].values():
        for day in sorted(acc)[:-KEEP_DAYS]:
            acc.pop(day)
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def _title(m):
    line = (m.get("caption") or "").strip().split("\n")[0]
    return line[:22] + ("…" if len(line) > 22 else "")


def _when(m):
    try:
        t = datetime.strptime(m["timestamp"], "%Y-%m-%dT%H:%M:%S%z").astimezone(draft.KST)
        return f"{t:%m/%d %H:%M}"
    except (KeyError, ValueError):
        return ""


def _account_report(acc, history, today):
    """한 계정의 보고서 줄 목록. history: 그 계정의 날짜별 기록(고쳐 씀)."""
    info = instagram.account_info()
    followers = info.get("followers_count", 0)
    days = sorted(d for d in history if d < today)
    before = history[days[-1]]["followers"] if days else None
    diff = f" ({followers - before:+d})" if before is not None else ""
    lines = [f"📊 [{acc['name']}] @{info.get('username', '')}", f"팔로워 {followers:,}명{diff}"]
    record = {"followers": followers}

    now = datetime.now(draft.KST)
    try:
        split = instagram.reach_by_follow_type((now - timedelta(days=7)).timestamp(), now.timestamp())
        fol, non = split.get("FOLLOWER", 0), split.get("NON_FOLLOWER", 0)
        if fol + non:
            pct = round(non * 100 / (fol + non))
            lines.append(f"최근 7일 도달 {fol + non:,}명 중 비팔로워 {pct}% (높을수록 추천으로 퍼지는 중)")
            record["reach7"], record["non_follower_pct"] = fol + non, pct
    except RuntimeError as e:
        print(f"[insights] {acc['name']} 계정 도달 실패: {e}")

    lines.append("")
    lines.append("최근 게시물 (조회 · 도달 · 저장 · 공유)")
    posts = {}
    for m in instagram.recent_media(POSTS):
        reel = m.get("media_product_type") == "REELS"
        try:
            v = instagram.media_insights(m["id"], reel)
        except RuntimeError as e:
            print(f"[insights] 게시물 {m['id']} 실패: {e}")
            if "permission" in str(e).lower() or "권한" in str(e):
                lines.append("⚠️ 통계 권한이 없어요 (instagram_business_manage_insights)")
                break
            continue
        watch = v.get("ig_reels_avg_watch_time")
        extra = f" · 평균 {watch / 1000:.1f}초 시청" if watch else ""
        kind = "🎬" if reel else "🖼"
        lines.append(f"{kind} {_when(m)} {_title(m)}")
        lines.append(f"   👀{v.get('views', 0):,} · 도달 {v.get('reach', 0):,} · 💾{v.get('saved', 0)} · "
                     f"↗️{v.get('shares', 0)}{extra}")
        posts[m["id"]] = {k: v.get(k, 0) for k in ("views", "reach", "saved", "shares")}
    record["posts"] = posts
    history[today] = record
    return lines


def report():
    """두 계정 보고서를 만들어 텔레그램으로 보낸다. 보낸 글을 돌려준다."""
    state = _load()
    today = datetime.now(draft.KST).strftime("%Y-%m-%d")
    blocks = []
    for acc in comments.ACCOUNTS:
        token = os.environ.get(acc["token_env"], "").strip()
        if not token:
            continue
        instagram.use_token(None if acc["token_env"] == "INSTAGRAM_ACCESS_TOKEN" else token)
        try:
            blocks.append("\n".join(_account_report(acc, state["history"].setdefault(acc["name"], {}), today)))
        except Exception as e:
            print(f"[insights] {acc['name']} 실패: {e}")
            blocks.append(f"📊 [{acc['name']}] 통계를 못 가져왔어요: {str(e)[:150]}")
        finally:
            instagram.use_token(None)
    if not blocks:
        return ""
    if threads_promo.enabled():  # 쓰레드 홍보 토큰이 살아 있는지 같이 확인 (글은 안 올림)
        try:
            blocks.append(f"🧵 쓰레드 홍보 계정: @{threads_promo.whoami()} (월·수·금 17:30 총정리표 홍보)")
        except Exception as e:
            blocks.append(f"🧵 쓰레드 홍보 토큰 확인 실패: {str(e)[:150]}")
    text = f"🗓 {today} 인스타 숫자 보고서\n\n" + "\n\n".join(blocks)
    telegram.send_text(text)
    state["last"] = today
    _save(state)
    return text


def maybe_report():
    """REPORT_HOUR시가 지났고 오늘 아직 안 보냈으면 보낸다 (poll.py가 부름)."""
    now = datetime.now(draft.KST)
    if now.hour < REPORT_HOUR or _load().get("last") == now.strftime("%Y-%m-%d"):
        return
    report()


if __name__ == "__main__":
    out = report()
    print(out or "보낼 계정이 없어요")
    sys.exit(0 if out else 1)
