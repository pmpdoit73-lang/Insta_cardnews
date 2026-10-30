"""카드 배경 사진 준비: 제미나이 실사 생성 → 실패하면 Pexels 무료 사진(키가 있을 때만).
인포그래픽형은 칸마다 들어갈 만화풍 그림(get_icon)을 만든다.

표지 사진을 먼저 만들고, 나머지 카드는 그 사진을 참고 이미지로 넣어 같은 세트장(같은 가전·조리대·햇살)으로 맞춘다.

사진에는 글씨를 넣지 않는다. 글씨는 render.py가 얹는다.
결과는 (사진 바이트, 출처 설명). 둘 다 실패하면 (None, 이유) → render가 시험용 배경을 씀.
"""

import base64
import os

import requests

GEMINI_IMAGE_MODEL = os.environ.get("GEMINI_IMAGE_MODEL", "gemini-2.5-flash-image")
TIMEOUT = 90

STYLE = (
    "A realistic lifestyle photograph for a Korean Instagram kitchen-tips post. "
    "Bright, warm morning sunlight through a window, cozy clean Korean home kitchen, "
    "true-to-life colors and textures, shot on a good camera at eye level. "
    "NOT a 3D render, NOT an illustration, NOT a glossy advertisement. "
    "Keep the lower third of the frame simple (counter surface, soft shadow) because text will be placed there. "
    "Vertical 4:5 composition. Absolutely no text, no letters, no numbers, no labels with writing, "
    "no logos, no watermarks, no faces (hands are fine). "
)
SAME_SET = (
    "Use the attached photo as the reference. Keep exactly the same kitchen, the same appliance, "
    "the same counter, props, lighting, colors and camera angle, so it looks like the next photo of the same shoot. "
    "Change only this: "
)

ICON_STYLE = (
    "A cute flat cartoon sticker illustration for a Korean Instagram infographic. "
    "One single object, centered, filling most of the frame, thick dark outlines, soft warm pastel colors, "
    "simple shading, friendly and clean like a children's picture book. Pure plain white background, "
    "no shadow on the background, no frame, no border. "
    "Absolutely no text, no letters, no numbers, no labels with writing, no logos, no faces. "
)
ICON_SAME_STYLE = (
    "Use the attached illustration only as the style reference: same drawing style, outline thickness, "
    "color palette and white background. Draw a different object: "
)


def _gemini(parts, aspect):
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("GEMINI_API_KEY 없음")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_IMAGE_MODEL}:generateContent"
    body = {
        "contents": [{"parts": parts}],
        "generationConfig": {"responseModalities": ["IMAGE"], "imageConfig": {"aspectRatio": aspect}},
    }
    resp = requests.post(url, params={"key": key}, json=body, timeout=TIMEOUT)
    resp.raise_for_status()
    for cand in resp.json().get("candidates", []):
        for part in cand.get("content", {}).get("parts", []):
            data = part.get("inlineData") or part.get("inline_data")
            if data and data.get("data"):
                return base64.b64decode(data["data"])
    raise RuntimeError("Gemini 응답에 이미지가 없음")


def _image_part(data):
    mime = "image/png" if data[:4] == b"\x89PNG" else "image/jpeg"
    return {"inlineData": {"mimeType": mime, "data": base64.b64encode(data).decode()}}


def gemini_image(prompt, scene="", ref=None):
    """scene: 모든 카드가 함께 쓰는 세트장 묘사. ref: 표지 사진 바이트(있으면 같은 세트장으로 맞춤)."""
    if ref:
        parts = [_image_part(ref), {"text": STYLE + SAME_SET + prompt}]
    else:
        parts = [{"text": STYLE + "Scene: " + scene + " Subject: " + prompt}]
    return _gemini(parts, "4:5")


def pexels_photo(query):
    key = os.environ.get("PEXELS_API_KEY")
    if not key:
        raise RuntimeError("PEXELS_API_KEY 없음")
    resp = requests.get(
        "https://api.pexels.com/v1/search",
        params={"query": query, "per_page": 1, "orientation": "portrait"},
        headers={"Authorization": key},
        timeout=30,
    )
    resp.raise_for_status()
    photos = resp.json().get("photos", [])
    if not photos:
        raise RuntimeError(f"Pexels 검색 결과 없음: {query}")
    img = requests.get(photos[0]["src"]["large2x"], timeout=30)
    img.raise_for_status()
    return img.content, photos[0].get("photographer", "")


def get_icon(icon_prompt, ref=None):
    """인포그래픽 칸에 넣을 만화풍 그림 하나. ref: 첫 그림 바이트(있으면 같은 그림체로 맞춤).

    결과는 (그림 바이트, 출처 설명). 실패하면 (None, 이유) → render가 이모지로 대신 그린다.
    """
    for r in ([ref, None] if ref else [None]):  # 그림체 맞추기가 안 되면 참고 그림 없이 한 번 더
        try:
            if r:
                parts = [_image_part(r), {"text": ICON_STYLE + ICON_SAME_STYLE + icon_prompt}]
            else:
                parts = [{"text": ICON_STYLE + "Subject: " + icon_prompt}]
            return _gemini(parts, "1:1"), "제미나이"
        except Exception as e:
            print(f"[images] Gemini 그림 실패: {e}")
    return None, "이모지"


def get_image(image_prompt, photo_query, scene="", ref=None):
    try:
        return gemini_image(image_prompt, scene, ref), "제미나이"
    except Exception as e:
        print(f"[images] Gemini 실패: {e}")
    if ref:  # 같은 세트장 맞추기가 안 되면 세트장 묘사만으로 한 번 더
        try:
            return gemini_image(image_prompt, scene), "제미나이"
        except Exception as e:
            print(f"[images] Gemini 재시도 실패: {e}")
    try:
        data, author = pexels_photo(photo_query)
        return data, f"Pexels ({author})"
    except Exception as e:
        print(f"[images] Pexels 실패: {e}")
        return None, "사진 준비 실패"
