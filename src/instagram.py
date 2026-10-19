"""인스타그램 캐러셀(여러 장 넘기기) 게시.

순서: 사진마다 '카드 컨테이너' 만들기 → 묶음(CAROUSEL) 컨테이너 → 준비 끝나면 게시.
인스타 API는 사진 파일을 직접 받지 않고 공개 인터넷 주소(URL)만 받는다.

필요한 값 (GitHub Secrets):
- INSTAGRAM_ACCESS_TOKEN
- INSTAGRAM_USER_ID
- INSTAGRAM_API_HOST (선택) — 인스타 로그인 방식이면 graph.instagram.com(기본),
  페이스북 페이지 연결 방식이면 graph.facebook.com
"""

import os
import time

import requests

VERSION = "v23.0"
TIMEOUT = 60


def _base():
    host = os.environ.get("INSTAGRAM_API_HOST", "graph.instagram.com").strip() or "graph.instagram.com"
    return f"https://{host}/{VERSION}"


def _token():
    return os.environ["INSTAGRAM_ACCESS_TOKEN"].strip()


def _user():
    return os.environ["INSTAGRAM_USER_ID"].strip()


def _call(method, path, **params):
    params["access_token"] = _token()
    resp = requests.request(method, f"{_base()}/{path}", params=params, timeout=TIMEOUT)
    body = resp.json()
    if resp.status_code != 200 or "error" in body:
        err = body.get("error", {})
        raise RuntimeError(f"인스타 {path} 실패: {err.get('message', body)}")
    return body


def username():
    return _call("GET", _user(), fields="username")["username"]


def _wait_ready(container_id, tries=20):
    """컨테이너 준비가 끝날 때까지 기다린다 (보통 몇 초)."""
    for _ in range(tries):
        status = _call("GET", container_id, fields="status_code").get("status_code")
        if status == "FINISHED":
            return
        if status in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"인스타가 사진을 처리하지 못했어요 (상태: {status})")
        time.sleep(5)
    raise RuntimeError("인스타 사진 처리가 너무 오래 걸려요")


def post_carousel(image_urls, caption):
    """사진 주소 2~10개로 캐러셀을 올리고 (게시물 id, 링크)를 돌려준다."""
    children = []
    for url in image_urls:
        c = _call("POST", f"{_user()}/media", image_url=url, is_carousel_item="true")
        children.append(c["id"])
    for cid in children:
        _wait_ready(cid)
    album = _call("POST", f"{_user()}/media", media_type="CAROUSEL",
                  children=",".join(children), caption=caption)
    _wait_ready(album["id"])
    media_id = _call("POST", f"{_user()}/media_publish", creation_id=album["id"])["id"]
    try:
        link = _call("GET", media_id, fields="permalink").get("permalink", "")
    except RuntimeError:
        link = ""
    return media_id, link


def refresh_token():
    """인스타 로그인 방식 토큰(60일)을 새 60일짜리로 바꿔 돌려준다. (페이스북 방식은 해당 없음)"""
    resp = requests.get("https://graph.instagram.com/refresh_access_token",
                        params={"grant_type": "ig_refresh_token", "access_token": _token()},
                        timeout=TIMEOUT)
    body = resp.json()
    if "access_token" not in body:
        raise RuntimeError(f"토큰 갱신 실패: {body.get('error', body)}")
    return body["access_token"], body.get("expires_in")
