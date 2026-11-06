"""인스타그램 게시: 캐러셀(여러 장 넘기기)과 릴스(영상). 댓글 읽기·답글 달기도 여기서.

캐러셀 순서: 사진마다 '카드 컨테이너' 만들기 → 묶음(CAROUSEL) 컨테이너 → 준비 끝나면 게시.
릴스 순서: 영상 주소로 REELS 컨테이너 → 인스타가 영상 처리 끝낼 때까지 기다림 → 게시.
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


_token_override = None  # 다른 계정(이슈풀이) 댓글을 볼 때만 잠깐 바꿔 씀


def _token():
    return _token_override or os.environ["INSTAGRAM_ACCESS_TOKEN"].strip()


def use_token(token):
    """다른 계정 토큰으로 바꾼다. None이면 원래 계정(살림 꿀팁)으로."""
    global _token_override, _user_id
    _token_override = token
    _user_id = None


_user_id = None


def _user():
    """INSTAGRAM_USER_ID가 숫자가 아니면(계정 이름 등) 토큰으로 진짜 숫자 ID를 찾는다."""
    global _user_id
    if _user_id:
        return _user_id
    value = "" if _token_override else os.environ.get("INSTAGRAM_USER_ID", "").strip()
    if value.isdigit():
        _user_id = value
    else:
        body = _call("GET", "me", fields="user_id,username")
        _user_id = str(body.get("user_id") or body["id"])
        print(f"[instagram] 계정 숫자 ID를 토큰으로 찾음 (@{body.get('username', '')})")
    return _user_id


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


def _wait_ready(container_id, tries=20, first=3, every=5):
    """컨테이너 준비가 끝날 때까지 기다린다 (사진은 몇 초, 영상은 30초~몇 분).
    첫 확인 전에 조금 쉬어서 호출 횟수를 줄인다."""
    time.sleep(first)
    for _ in range(tries):
        status = _call("GET", container_id, fields="status_code").get("status_code")
        if status == "FINISHED":
            return
        if status in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"인스타가 사진·영상을 처리하지 못했어요 (상태: {status})")
        time.sleep(every)
    raise RuntimeError("인스타 사진·영상 처리가 너무 오래 걸려요")


def _key(caption):
    """캡션 첫 줄로 같은 게시물인지 알아본다."""
    return (caption or "").strip().split("\n")[0].strip()


def _find_existing(caption):
    """같은 캡션의 게시물이 이미 최근 5개 안에 있으면 (id, 링크). 없으면 None.
    '다시 게시'를 눌렀는데 사실은 이미 올라가 있던 경우 중복 게시를 막는다."""
    key = _key(caption)
    if not key:
        return None
    try:
        recent = _call("GET", f"{_user()}/media", fields="id,caption,permalink", limit=5).get("data", [])
    except RuntimeError as e:
        print(f"[instagram] 최근 게시물 확인 실패: {e}")
        return None
    for m in recent:
        if _key(m.get("caption")) == key:
            return m["id"], m.get("permalink", "")
    return None


def _diagnose(container_id):
    """게시 실패 때 원인 파악용 정보를 로그에 남긴다."""
    for path, fields in ((container_id, "status_code,status"),
                         (f"{_user()}/content_publishing_limit", "quota_usage,config")):
        try:
            print(f"[instagram] 진단 {path}: {_call('GET', path, fields=fields)}")
        except RuntimeError as e:
            print(f"[instagram] 진단 {path} 실패: {e}")


def post_carousel(image_urls, caption):
    """사진 주소 2~10개로 캐러셀을 올리고 (게시물 id, 링크)를 돌려준다."""
    existing = _find_existing(caption)
    if existing:
        print("[instagram] 같은 게시물이 이미 올라가 있어서 다시 올리지 않음")
        return existing
    children = []
    for url in image_urls:
        c = _call("POST", f"{_user()}/media", image_url=url, is_carousel_item="true")
        children.append(c["id"])
    for cid in children:
        _wait_ready(cid)
    album = _call("POST", f"{_user()}/media", media_type="CAROUSEL",
                  children=",".join(children), caption=caption)
    _wait_ready(album["id"])
    return _publish(album["id"], caption)


def post_reel(video_url, caption):
    """MP4 영상 주소로 릴스를 올리고 (게시물 id, 링크)를 돌려준다. 피드(프로필 격자)에도 보이게 올린다."""
    existing = _find_existing(caption)
    if existing:
        print("[instagram] 같은 게시물이 이미 올라가 있어서 다시 올리지 않음")
        return existing
    reel = _call("POST", f"{_user()}/media", media_type="REELS", video_url=video_url,
                 caption=caption, share_to_feed="true")
    # 영상 처리는 오래 걸려서 15초마다 최대 약 6분 확인 (호출 횟수를 줄이려고 간격을 넓힘)
    _wait_ready(reel["id"], tries=24, first=20, every=15)
    return _publish(reel["id"], caption)


def _publish(container_id, caption):
    """준비된 컨테이너를 게시하고 (게시물 id, 링크)를 돌려준다."""
    try:
        media_id = _call("POST", f"{_user()}/media_publish", creation_id=container_id)["id"]
    except RuntimeError as e:
        # 인스타가 "요청 한도 초과" 오류를 내면서도 실제로는 올리는 경우가 있다 (2026-10-28~).
        # 컨테이너 상태는 늦게 바뀌기도 해서, 최근 게시물에 같은 캡션이 생겼는지 1분 동안 확인한다
        print(f"[instagram] 게시 오류: {e} → 실제로 올라갔는지 확인")
        for wait in (10, 20, 30):
            time.sleep(wait)
            existing = _find_existing(caption)
            if existing:
                print("[instagram] 오류가 났지만 실제로는 올라감")
                return existing
        _diagnose(container_id)
        raise e
    try:
        link = _call("GET", media_id, fields="permalink").get("permalink", "")
    except RuntimeError:
        link = ""
    return media_id, link


# ---------- 댓글 (comments.py가 씀) ----------

def recent_media(limit=10):
    """최근 게시물 [{id, caption, comments_count, permalink}] (최신순)."""
    return _call("GET", f"{_user()}/media", fields="id,caption,comments_count,permalink",
                 limit=limit).get("data", [])


def comments(media_id, limit=50):
    """게시물의 댓글 [{id, text, username, timestamp, replies}] (답글 단 사람 이름 포함)."""
    return _call("GET", f"{media_id}/comments", fields="id,text,username,timestamp,replies{username}",
                 limit=limit).get("data", [])


def reply_comment(comment_id, message):
    return _call("POST", f"{comment_id}/replies", message=message)["id"]


def refresh_token():
    """인스타 로그인 방식 토큰(60일)을 새 60일짜리로 바꿔 돌려준다. (페이스북 방식은 해당 없음)"""
    resp = requests.get("https://graph.instagram.com/refresh_access_token",
                        params={"grant_type": "ig_refresh_token", "access_token": _token()},
                        timeout=TIMEOUT)
    body = resp.json()
    if "access_token" not in body:
        raise RuntimeError(f"토큰 갱신 실패: {body.get('error', body)}")
    return body["access_token"], body.get("expires_in")
