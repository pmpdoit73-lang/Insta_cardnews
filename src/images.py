"""카드 배경 사진 준비: 제미나이 실사 생성 → 실패하면 Pexels 무료 사진(키가 있을 때만).

사진에는 글씨를 넣지 않는다. 글씨는 render.py가 얹는다.
결과는 (사진 바이트, 출처 설명). 둘 다 실패하면 (None, 이유) → render가 시험용 배경을 씀.
"""

import base64
import os

import requests

GEMINI_IMAGE_MODEL = os.environ.get("GEMINI_IMAGE_MODEL", "gemini-2.5-flash-image")
TIMEOUT = 90

STYLE = (
    "A realistic news-style photograph for a Korean Instagram card news post. "
    "Must look like a real photo taken by a photojournalist or an ordinary person on a smartphone, "
    "NOT AI art, NOT a 3D render, NOT an illustration, NOT a glossy advertisement. "
    "Natural light, true-to-life colors, realistic textures and small imperfections, Korean setting when relevant. "
    "Leave calm, simple areas (sky, wall, floor, table surface) where text can be placed later. "
    "Vertical 4:5 composition. Absolutely no text, no letters, no numbers, no signs with writing, "
    "no logos, no watermarks, no recognizable human faces. Subject: "
)


def gemini_image(prompt):
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("GEMINI_API_KEY 없음")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_IMAGE_MODEL}:generateContent"
    body = {
        "contents": [{"parts": [{"text": STYLE + prompt}]}],
        "generationConfig": {"responseModalities": ["IMAGE"], "imageConfig": {"aspectRatio": "4:5"}},
    }
    resp = requests.post(url, params={"key": key}, json=body, timeout=TIMEOUT)
    resp.raise_for_status()
    for cand in resp.json().get("candidates", []):
        for part in cand.get("content", {}).get("parts", []):
            data = part.get("inlineData") or part.get("inline_data")
            if data and data.get("data"):
                return base64.b64decode(data["data"])
    raise RuntimeError("Gemini 응답에 이미지가 없음")


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


def get_image(image_prompt, photo_query):
    try:
        return gemini_image(image_prompt), "제미나이"
    except Exception as e:
        print(f"[images] Gemini 실패: {e}")
    try:
        data, author = pexels_photo(photo_query)
        return data, f"Pexels ({author})"
    except Exception as e:
        print(f"[images] Pexels 실패: {e}")
        return None, "사진 준비 실패"
