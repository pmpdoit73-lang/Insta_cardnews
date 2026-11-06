"""17:30 인포그래픽(총정리표)이 인스타에 올라가면 쓰레드에도 홍보 글을 올린다
(2026-11-06 gil 요청, 조회수 개선 6단계: 조회가 잘 나오는 쓰레드에서 인스타로 사람 데려오기).

- 주 3회(월·수·금)만. 매일 올리면 쓰레드 팔로워가 광고로 느낄 수 있어서
- 총정리표 사진 1장 + "저장용 정리표 인스타에 올려뒀어요" + 인스타 게시물 링크
- 시크릿 THREADS_PROMO_TOKEN(홍보 글을 올릴 쓰레드 계정 토큰)이 없으면 아무것도 안 함
- 실패해도 인스타 게시는 성공으로 둔다
"""

import os
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


def text_for(d):
    issue = (d.get("issue") or "").strip()
    return (f"{issue}, 한 장으로 정리했어요 📌\n\n"
            "저장해 두고 필요할 때 꺼내 보세요.\n"
            f"전체 표는 인스타에 올려뒀어요 👉 {d.get('permalink', '')}")


def should_post(d, now):
    return enabled() and d.get("format") == "info" and now.weekday() in PROMO_DAYS and not d.get("threads_promo_id")


def post(image_url, text):
    """사진 1장 + 글로 쓰레드 게시물을 올리고 id를 돌려준다."""
    c = _call("POST", "me/threads", media_type="IMAGE", image_url=image_url, text=text)
    time.sleep(10)  # 쓰레드가 사진을 받아 갈 시간
    return _call("POST", "me/threads_publish", creation_id=c["id"])["id"]
