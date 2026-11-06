"""17:30 인포그래픽(총정리표)이 인스타에 올라가면 쓰레드에도 홍보 글을 올린다
(2026-11-06 gil 요청, 조회수 개선 6단계: 조회가 잘 나오는 쓰레드에서 인스타로 사람 데려오기).

- 주 3회(월·수·금)만. 매일 올리면 쓰레드 팔로워가 광고로 느낄 수 있어서
- 총정리표 사진 1장 + 쓰레드 말투(반말) 짧은 글 + 댓글을 부르는 질문 + 인스타 게시물 링크 (Claude가 씀)
- 시크릿 THREADS_PROMO_TOKEN(홍보 글을 올릴 쓰레드 계정 토큰)이 없으면 아무것도 안 함
- 실패해도 인스타 게시는 성공으로 둔다
"""

import os
import sys
import time

import requests

API = "https://graph.threads.net/v1.0"
PROMO_DAYS = {0, 2, 4}  # 월·수·금 (월=0)
TIMEOUT = 60


def _token():
    return os.environ.get("THREADS_PROMO_TOKEN", "").strip()


def enabled():
    return bool(_token())


def _call(method, path, **params):
    params["access_token"] = _token()
    resp = requests.request(method, f"{API}/{path}", params=params, timeout=TIMEOUT)
    body = resp.json()
    if resp.status_code != 200 or "error" in body:
        raise RuntimeError(f"쓰레드 {path} 실패: {body.get('error', {}).get('message', body)}")
    return body


def whoami():
    """토큰 확인용: 이 토큰의 쓰레드 계정 이름 (글은 올리지 않음)."""
    return _call("GET", "me", fields="username").get("username", "")


THREADS_PERSONA = (
    "너는 쓰레드에서 살림 이야기를 하는 살림 30년 차 50대야. 말투는 편한 반말 트렌드체 "
    "(~함, ~임, ~더라, ~인 듯, ~해봐). 존댓말·광고 말투는 쓰지 않아."
)
TEXT = {
    "type": "object",
    "properties": {"lines": {"type": "array", "items": {"type": "string"},
                             "description": "쓰레드 글 2~4줄 (링크 제외)"}},
    "required": ["lines"],
    "additionalProperties": False,
}


def text_for(d):
    """쓰레드 말투(반말)로 짧게, 끝은 누구나 답할 질문으로 댓글을 부른다 (2026-11-06 gil 요청).
    Claude가 못 쓰면 정해 둔 문장으로."""
    link = d.get("permalink", "")
    try:
        import writer
        msg = (f"인스타에 올린 총정리표 주제: {d.get('issue', '')}\n"
               f"표 내용 일부:\n{(d.get('caption') or '')[:500]}\n\n"
               "이 표를 쓰레드에서 소개하는 짧은 글을 써 줘.\n"
               "- 2~4줄, 모두 합쳐 90자 이내. 링크는 쓰지 마 (코드가 맨 끝에 붙임)\n"
               "- 첫 줄: 표에서 '나만 몰랐네' 싶은 사실 하나로 시작 (주제 이름 그대로 나열 금지)\n"
               "- 중간: 인스타에 한 장 표로 정리해 뒀다는 말 (예: '인스타에 표로 정리해둠')\n"
               "- 마지막 줄: 누구나 바로 답할 수 있는 짧은 질문 (예: '너네 집 참기름은 냉장고임 찬장임?')\n"
               "- '댓글 달아줘', '팔로우' 같은 부탁, 해시태그, 광고 말투 금지")
        lines = [ln.strip() for ln in writer._ask(msg, TEXT, system=THREADS_PERSONA)["lines"] if ln.strip()]
        if lines:
            return "\n".join(lines) + f"\n\n👉 {link}"
    except Exception as e:
        print(f"[threads_promo] 글쓰기 실패, 기본 문장 사용: {e}")
    issue = (d.get("issue") or "").strip()
    return f"{issue}, 표 한 장으로 정리해둠 📌\n저장해두고 필요할 때 꺼내 봐\n\n👉 {link}"


def should_post(d, now):
    return enabled() and d.get("format") == "info" and now.weekday() in PROMO_DAYS and not d.get("threads_promo_id")


def post(image_url, text):
    """사진 1장 + 글로 쓰레드 게시물을 올리고 id를 돌려준다."""
    c = _call("POST", "me/threads", media_type="IMAGE", image_url=image_url, text=text)
    time.sleep(10)  # 쓰레드가 사진을 받아 갈 시간
    return _call("POST", "me/threads_publish", creation_id=c["id"])["id"]


if __name__ == "__main__":
    # 시험·수동용: python src/threads_promo.py <초안 id>  → 요일과 상관없이 그 게시물 홍보 글을 지금 올림
    import draft
    import hosting
    d = draft.load(sys.argv[1])
    if not d or not d.get("permalink"):
        sys.exit(f"게시된 초안이 아니에요: {sys.argv[1]}")
    first = draft.card_paths(d)[0]
    text = os.environ.get("PROMO_TEXT", "").strip().replace("\\n", "\n")  # 미리 확인한 글이 있으면 그대로
    if text and "{link}" in text:
        text = text.replace("{link}", d["permalink"])
    text = text or text_for(d)
    if os.environ.get("PREVIEW") == "1":  # 올리지 않고 텔레그램으로 미리보기만
        import telegram
        telegram.send_draft("🧵 쓰레드 홍보 글 미리보기 (아직 안 올림)\n\n" + text, first.read_bytes())
        print("미리보기 보냄:\n" + text)
        sys.exit(0)
    if d.get("threads_promo_id"):
        sys.exit("이미 홍보 글을 올린 게시물이에요")
    url = hosting.upload_temp(first.read_bytes(), f"{d['id']}-threads.jpg")
    d["threads_promo_id"] = post(url, text)
    draft.save(d)
    print(f"쓰레드 홍보 글 완료: {d['threads_promo_id']}")
