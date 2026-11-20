"""텔레그램 봇(인스타 전용): 초안 전송, 버튼, 버튼 눌림 확인."""

import json
import os
import time

import requests

API = "https://api.telegram.org/bot{token}/{method}"
CAPTION_LIMIT = 1024

# 일시적 네트워크 오류는 최대 3회 시도: 1회 실패 2초, 2회 실패 4초 쉬고 다시
ATTEMPTS = 3
RETRY_DELAYS = (2, 4)
# 재시도해 볼 만한 HTTP 응답: 게이트웨이·서버 오류(5xx), 요청 시간 초과, 요청 과다
TRANSIENT_STATUS = {408, 429}


class _TransientError(Exception):
    """재시도해 볼 만한 일시 오류(5xx 등). 응답 본문 대신 이걸로 넘긴다."""


def _retry_ready_payload(payload):
    """파일 한 개를 여러 번 보내도 되게 준비한다."""
    if isinstance(payload, bytes):
        return payload  # 바이트는 스트림이 아니라서 그대로 다시 보내도 안전
    if isinstance(payload, (bytearray, memoryview)):
        return bytes(payload)
    if hasattr(payload, "read"):
        if hasattr(payload, "seek"):
            try:
                payload.seek(0)
                return payload  # 되감을 수 있으니 시도마다 처음부터 읽게 한다
            except (OSError, ValueError):
                pass
        return payload.read()  # 되감을 수 없으면 한 번 읽어 바이트로 (재전송 안전)
    return payload


def _retry_ready_files(files):
    """files={키: (이름, 데이터[, 타입])}를 재시도해도 안전한 형태로 준비한다."""
    if not files:
        return files
    ready = {}
    for key, value in files.items():
        if isinstance(value, tuple):
            parts = list(value)
            if len(parts) > 1:
                parts[1] = _retry_ready_payload(parts[1])
            ready[key] = tuple(parts)
        else:
            ready[key] = _retry_ready_payload(value)
    return ready


def _rewind_files(files):
    """재시도 직전에 파일 객체를 처음으로 되감는다 (1회차에 끝까지 읽혔을 수 있음)."""
    if not files:
        return
    for value in files.values():
        for part in (value if isinstance(value, tuple) else (value,)):
            if hasattr(part, "read") and hasattr(part, "seek"):
                try:
                    part.seek(0)
                except (OSError, ValueError):
                    pass


def _call(method, timeout=30, **kwargs):
    """텔레그램 API 호출. 일시적 네트워크 오류만 최대 3회까지 다시 시도한다.

    - 재시도: 시간 초과, 연결 오류, 5xx(408·429 포함), 응답이 JSON이 아닌 경우.
    - 재시도 안 함: 200으로 왔는데 {"ok": false}인 경우 → 그대로 종료.
      (이미 처리된 요청을 다시 보내 중복 전송하거나, 오래된 버튼 오류를 되풀이하지 않으려고)
    """
    url = API.format(token=os.environ["TELEGRAM_BOT_TOKEN"].strip(), method=method)
    if kwargs.get("files"):
        kwargs["files"] = _retry_ready_files(kwargs["files"])
    last_error = None
    for attempt in range(1, ATTEMPTS + 1):
        _rewind_files(kwargs.get("files"))
        resp = None
        try:
            resp = requests.post(url, timeout=timeout, **kwargs)
            if resp.status_code >= 500 or resp.status_code in TRANSIENT_STATUS:
                raise _TransientError(f"HTTP {resp.status_code}")
            body = resp.json()
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError,
                requests.exceptions.ChunkedEncodingError, _TransientError) as e:
            last_error = e
        except ValueError as e:  # 응답 본문이 JSON이 아님 (프록시·게이트웨이 오류 페이지 등)
            if resp is not None and 400 <= resp.status_code < 500 and resp.status_code not in TRANSIENT_STATUS:
                raise RuntimeError(
                    f"텔레그램 {method} 실패: HTTP {resp.status_code} 응답을 읽을 수 없음") from e
            last_error = e
        else:
            if not body.get("ok"):
                raise RuntimeError(f"텔레그램 {method} 실패: {body.get('description')}")
            return body["result"]
        if attempt < ATTEMPTS:
            delay = RETRY_DELAYS[min(attempt - 1, len(RETRY_DELAYS) - 1)]
            print(f"[telegram] {method} 일시 오류로 재시도 ({attempt}/{ATTEMPTS}): {last_error}")
            time.sleep(delay)
    raise RuntimeError(
        f"텔레그램 {method} 실패: 일시 오류로 {ATTEMPTS}회 시도했지만 안 됨 ({last_error})") from last_error


def bot_id():
    """토큰 앞부분(봇 번호)만. 비밀 부분은 쓰지 않음."""
    return os.environ["TELEGRAM_BOT_TOKEN"].strip().split(":")[0]


def _chat_id():
    return os.environ["TELEGRAM_CHAT_ID"].strip()


def send_text(text, keyboard=None, silent=False, html=False, reply_to=None):
    """html=True면 <b>굵게</b>, <code>누르면 복사</code> 같은 표시를 쓸 수 있다."""
    data = {"chat_id": _chat_id(), "text": text, "disable_web_page_preview": "true",
            "disable_notification": str(silent).lower()}
    if html:
        data["parse_mode"] = "HTML"
    if reply_to:
        data["reply_to_message_id"] = str(reply_to)
    if keyboard:
        data["reply_markup"] = json.dumps({"inline_keyboard": keyboard})
    return _call("sendMessage", data=data)


def send_draft(caption, photo=None, keyboard=None, silent=False):
    """초안을 보내고 버튼이 달린 메시지를 돌려준다."""
    caption = caption[:CAPTION_LIMIT]
    if not photo:
        return send_text(caption, keyboard, silent)
    data = {"chat_id": _chat_id(), "caption": caption, "disable_notification": str(silent).lower()}
    if keyboard:
        data["reply_markup"] = json.dumps({"inline_keyboard": keyboard})
    return _call("sendPhoto", data=data, files={"photo": ("draft.png", photo)})


def edit_draft(message, caption, keyboard=None):
    """이미 보낸 초안의 글자와 버튼을 바꾼다."""
    markup = json.dumps({"inline_keyboard": keyboard or []})
    base = {"chat_id": _chat_id(), "message_id": message["message_id"], "reply_markup": markup}
    try:
        if message.get("has_photo"):
            _call("editMessageCaption", data={**base, "caption": caption[:CAPTION_LIMIT]})
        else:
            _call("editMessageText", data={**base, "text": caption, "disable_web_page_preview": "true"})
    except RuntimeError as e:
        if "not modified" not in str(e):  # 같은 내용으로 다시 고치면 나는 오류는 무시
            raise


def answer(callback_id, text=""):
    try:
        _call("answerCallbackQuery", data={"callback_query_id": callback_id, "text": text})
    except RuntimeError:
        pass  # 오래된 버튼은 응답 기한이 지나 실패할 수 있음


def get_updates(offset):
    return _call("getUpdates", data={"offset": offset, "timeout": 0,
                                     "allowed_updates": json.dumps(["callback_query", "message"])})



def download_file(file_id):
    """텔레그램에 올라온 파일(사진)을 내려받는다."""
    path = _call("getFile", data={"file_id": file_id})["file_path"]
    token = os.environ["TELEGRAM_BOT_TOKEN"].strip()
    resp = requests.get(f"https://api.telegram.org/file/bot{token}/{path}", timeout=60)
    resp.raise_for_status()
    return resp.content


def send_album(photos, caption=""):
    """카드 사진 여러 장을 한 묶음(앨범)으로 보낸다. photos: [(파일이름, 바이트), ...]"""
    media = []
    files = {}
    for i, (name, data) in enumerate(photos):
        key = f"p{i}"
        item = {"type": "photo", "media": f"attach://{key}"}
        if i == 0 and caption:
            item["caption"] = caption[:CAPTION_LIMIT]
        media.append(item)
        files[key] = (name, data)
    data = {"chat_id": _chat_id(), "media": json.dumps(media), "disable_notification": "true"}
    return _call("sendMediaGroup", data=data, files=files)


def send_video(video, caption=""):
    """영상(MP4 바이트)을 보낸다. 릴스 미리보기용."""
    data = {"chat_id": _chat_id(), "caption": caption[:CAPTION_LIMIT], "supports_streaming": "true",
            "width": "1080", "height": "1920", "disable_notification": "true"}
    return _call("sendVideo", data=data, files={"video": ("reel.mp4", video, "video/mp4")}, timeout=120)
