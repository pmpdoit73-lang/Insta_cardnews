"""카드 배경 사진 준비: 제미나이 실사 생성 → 실패하면 Pexels 무료 사진(키가 있을 때만).
인포그래픽형은 칸마다 들어갈 만화풍 그림(get_icon)을 만든다.

표지 사진을 먼저 만들고, 나머지 카드는 그 사진을 참고 이미지로 넣어 같은 세트장(같은 가전·조리대·햇살)으로 맞춘다.

사진에는 글씨를 넣지 않는다. 글씨는 render.py가 얹는다.
결과는 (사진 바이트, 출처 설명). 둘 다 실패하면 (None, 이유) → render가 시험용 배경을 씀.
"""

import base64
import io
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

ICON_STYLE = (  # 2026-11-23 gil: 9장 카드뉴스처럼 3D 캐릭터 그림으로
    "A cute 3D animated character version of the object, Pixar-like 3D render, "
    "big round expressive eyes and a small friendly face on the object itself, tiny arms, "
    "soft studio lighting, glossy toy-like materials, warm pastel colors. "
    "One single character, centered, filling most of the frame. Pure plain white background, "
    "no shadow on the background, no frame, no border. "
    "Absolutely no text, no letters, no numbers, no labels with writing, no logos. "
)
HERO_STYLE = (
    "A cute 3D animated character, Pixar-like 3D render, big round expressive eyes, tiny arms, "
    "soft studio lighting, glossy toy-like materials, warm colors. One single character, centered, "
    "full body visible, filling about 80% of the frame. Pure plain white background, no frame, "
    "no text, no letters, no numbers, no logos. Character: "
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


SHEET_STYLE = (  # 2026-11-24 gil: 그림 요금 절감 — 아이콘 10개를 한 줄짜리 시트 2장으로 만들어 잘라 쓴다
    "A sheet of separate cute 3D animated characters, Pixar-like 3D render, "
    "big round expressive eyes and a small friendly face on each object itself, tiny arms, "
    "soft studio lighting, glossy toy-like materials, warm pastel colors. "
    "All characters share exactly the same style and size. Pure plain white background, no shadows on the background, "
    "no frame, no borders, no grid lines. Absolutely no text, no letters, no numbers, no labels, no logos. "
)


def sheet_chunks(n):
    """시트 한 장에 한 줄로 그릴 개수들. 10개 → [5, 5], 7개 → [4, 3].
    (2줄 이상을 한 장에 시키면 제미나이가 줄·칸 수를 마음대로 바꿔서, 한 줄짜리 시트 2장으로 한다)"""
    first = (n + 1) // 2
    return [first, n - first]


def _ink(im):
    """흰 바탕이 아닌 곳을 255로 칠한 흑백 그림 (그림자·살짝 회색인 곳도 포함)."""
    from PIL import ImageOps
    return ImageOps.invert(im.convert("L")).point(lambda v: 255 if v > 18 else 0)


def _runs(profile, min_gap):
    """프로필(칸마다 내용 픽셀 수)에서 내용이 이어진 구간 [(시작, 끝)]. 빈 구간이 min_gap 이상이면 나눈다."""
    runs, start, gap = [], None, 0
    for i, v in enumerate(profile):
        if v > 0:
            if start is None:
                start = i
            end, gap = i, 0
        elif start is not None:
            gap += 1
            if gap >= min_gap:
                runs.append((start, end + 1))
                start = None
    if start is not None:
        runs.append((start, end + 1))
    return runs


def _split_row(sheet, count):
    """한 줄 시트에서 캐릭터 칸(좌표) count개를 찾는다. 캐릭터가 같은 간격으로 놓인다고 보고,
    칸 경계 근처에서 내용이 가장 적은 세로줄(흰 틈, 팔이 닿았으면 가장 얇은 곳)을 경계로 삼는다.
    모서리의 어두운 그림자·잡티는 무시한다. 빈 칸이 있으면 None."""
    from PIL import ImageOps
    ink = ImageOps.invert(sheet.convert("L")).point(lambda v: 255 if v > 60 else 0)
    w, h = sheet.size
    from PIL import ImageDraw
    d = ImageDraw.Draw(ink)  # 가장자리 6픽셀은 비움 (모서리 그림자·잡티)
    d.rectangle([0, 0, w, 6], fill=0); d.rectangle([0, h - 6, w, h], fill=0)
    d.rectangle([0, 0, 6, h], fill=0); d.rectangle([w - 6, 0, w, h], fill=0)
    colp = [sum(1 for y in range(0, h, 2) if ink.getpixel((x, y))) for x in range(w)]
    cell = w / count
    cuts = [0]
    for k in range(1, count):
        lo, hi = int(cell * (k - 0.35)), int(cell * (k + 0.35))
        cuts.append(min(range(lo, hi), key=lambda x: (colp[x], abs(x - cell * k))))
    cuts.append(w)
    rects = []
    for x0, x1 in zip(cuts, cuts[1:]):
        box = ink.crop((x0, 0, x1, h)).getbbox()
        if not box or box[2] - box[0] < cell * 0.2 or box[3] - box[1] < h * 0.06:
            return None
        pad = 6
        rects.append((max(x0, x0 + box[0] - pad), max(0, box[1] - pad), min(x1, x0 + box[2] + pad), min(h, box[3] + pad)))
    return rects


def _one_sheet(prompts, debug_name=None, debug_dir=None):
    """캐릭터 len(prompts)개를 한 줄로 그린 시트 한 장 → 칸마다 정사각 흰 바탕 JPEG 바이트. 못 자르면 전부 None. 한 번 더 시도."""
    from PIL import Image
    n = len(prompts)
    listing = "; ".join(f"{i + 1}) {p}" for i, p in enumerate(prompts))
    prompt = (SHEET_STYLE +
              f"Layout: ONE single horizontal row with exactly {n} characters, left to right, evenly spaced, "
              f"each one separate with wide empty white space between them so none touch or overlap. "
              f"Draw ONLY these {n} characters, no extras, no second row: " + listing)
    for attempt in range(2):
        try:
            sheet = Image.open(io.BytesIO(_gemini([{"text": prompt}], "16:9"))).convert("RGB")
        except Exception as e:
            print(f"[images] Gemini 아이콘 시트 실패: {e}")
            continue
        if debug_dir:
            sheet.save(os.path.join(debug_dir, f"{debug_name}_{attempt + 1}.jpg"), quality=90)
        rects = _split_row(sheet, n)
        if not rects:
            print(f"[images] 시트 칸 수가 {n}개와 안 맞음 (시도 {attempt + 1})")
            continue
        out = []
        for rect in rects:
            cell = sheet.crop(rect)
            side = max(cell.size)  # 정사각 흰 바탕에 올려 render.icon_image가 그대로 다듬게
            sq = Image.new("RGB", (side, side), "white")
            sq.paste(cell, ((side - cell.width) // 2, (side - cell.height) // 2))
            buf = io.BytesIO()
            sq.save(buf, "JPEG", quality=92)
            out.append(buf.getvalue())
        return out
    return [None] * n


def get_icon_sheet(icon_prompts, debug_dir=None):
    """아이콘을 한 줄짜리 시트 2장(제미나이 2번 호출)으로 만들어 칸마다 잘라 돌려준다. 10번 → 2번.

    결과: 항목마다 그림 바이트(JPEG) 또는 None(못 잘랐음 → 호출한 쪽이 그 항목만 따로 만든다).
    debug_dir를 주면 원본 시트를 sheet_1_1.jpg 같은 이름으로 저장(시험용).
    """
    out, start = [], 0
    for k, count in enumerate(sheet_chunks(len(icon_prompts)), 1):
        if count:
            out += _one_sheet(icon_prompts[start:start + count], f"sheet_{k}", debug_dir)
        start += count
    return out


def get_hero(prompt, ref=None):
    """총정리 2번째 카드의 큰 3D 캐릭터 하나 (주인공 가전이 '멈춰!' 하는 모습). 실패하면 (None, 이유)."""
    for r in ([ref, None] if ref else [None]):
        try:
            parts = ([_image_part(r), {"text": "Same 3D character style as the attached image. " + HERO_STYLE + prompt}]
                     if r else [{"text": HERO_STYLE + prompt}])
            return _gemini(parts, "1:1"), "제미나이"
        except Exception as e:
            print(f"[images] Gemini 캐릭터 실패: {e}")
    return None, "없음"


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
