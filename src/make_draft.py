"""오늘의 카드뉴스 초안을 만들어 텔레그램으로 보낸다.

실행: python src/make_draft.py
- 오늘 초안이 이미 있으면 아무것도 안 함 (FORCE=1이면 다른 이슈로 새로 만듦)
"""

import os
import sys
from datetime import datetime

import draft
import telegram


def main():
    now = datetime.now(draft.KST)
    today = draft.load(now.strftime("%Y%m%d"))
    force = os.environ.get("FORCE") == "1"
    if today and not force:
        print(f"[make_draft] 오늘 초안이 이미 있어요 ({today['status']})")
        return
    if today and today["status"] == "published":
        print("[make_draft] 오늘은 이미 게시했어요")
        return
    if today:  # 수동 실행: 오늘 초안을 다른 이슈로 다시
        draft.rewrite(today)
        d = today
    else:
        d = draft.create(now)
    draft.send(d)
    print(f"[make_draft] 초안 {d['id']} 전송 완료: {d['issue']}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"[make_draft] 실패: {e}")
        try:
            telegram.send_text(f"⚠️ 카드뉴스 초안 만들기 실패: {e}")
        except Exception:
            pass
        sys.exit(1)
