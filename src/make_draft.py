"""다음 회차(07:00·17:30 중 가장 가까운 시각) 카드뉴스 초안을 만들어 텔레그램으로 보낸다.

실행: python src/make_draft.py
- 다음 회차 초안이 이미 있으면 아무것도 안 함 (FORCE=1이면 다른 이슈로 새로 만듦)
- 알람은 회차마다 몇 시간 전에 한 번씩 (21:00 → 다음 날 07:00, 08:00 → 17:30. 14:00 알람은 이미 있으면 그냥 넘어감)
"""

import os
import sys

import draft
import telegram


def main():
    slot = draft.next_slot()
    existing = draft.for_slot(slot)
    force = os.environ.get("FORCE") == "1"
    label = f"{slot:%m/%d} {draft.time_label(slot)}"
    if existing and not force:
        print(f"[make_draft] {label} 초안이 이미 있어요 ({existing['status']})")
        return
    if existing and existing["status"] == "published":
        print(f"[make_draft] {label}은 이미 게시했어요")
        return
    if existing:  # 수동 실행: 같은 회차 초안을 다른 이슈로 다시
        draft.rewrite(existing)
        d = existing
    else:
        d = draft.create(slot)
    draft.send(d)
    print(f"[make_draft] {label} 초안 {d['id']} 전송 완료: {d['issue']}")


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
