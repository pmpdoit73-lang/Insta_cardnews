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


SHEET_STYLE = (  # 2026-11-24 gil: 그림 요금 절감 — 아이콘 10장을 한 장짜리 시트로 한 번에 만들어 잘라 쓴다
    "A sheet of separate cute 3D animated characters, Pixar-like 3D render, "
    "big round expressive eyes and a small friendly face on each object itself, tiny arms, "
    "soft studio lighting, glossy toy-like materials, warm pastel colors. "
    "All characters share exactly the same style and size. Pure plain white background, no shadows on the background, "
    "no frame, no borders, no grid lines. Absolutely no text, no letters, no numbers, no labels, no logos. "
)


def sheet_grid(n):
    """(열, 행). 10개 → 5×2, 7개 → 4×2. 가로로 긴 그림 한 장에 한 줄 5칸씩 들어간다."""
    cols = 5 if n > 8 else 4
    return cols, (n + cols - 1) // cols


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


def _split_sheet(sheet, n, cols, rows):
    """시트에서 캐릭터 n개의 칸(좌표)을 찾는다. 1) 흰 틈으로 줄·칸을 가르고(캐릭터가 칸 선에서 벗어나도 OK),
    안 맞으면 2) 균등 격자로 자른다. 결과: [(left, top, right, bottom) 또는 None] × n"""
    ink = _ink(sheet)
    w, h = sheet.size
    rowp = [sum(1 for x in range(0, w, 2) if ink.getpixel((x, y))) for y in range(h)]
    row_runs = _runs(rowp, max(6, h // 40))
    rects = []
    if len(row_runs) == rows:
        for (y0, y1) in row_runs:
            strip = ink.crop((0, y0, w, y1))
            colp = [sum(1 for y in range(0, y1 - y0, 2) if strip.getpixel((x, y))) for x in range(w)]
            col_runs = _runs(colp, max(6, w // 80))
            want = min(cols, n - len(rects))
            if len(col_runs) != want:
                rects = None
                break
            rects += [(x0, y0, x1, y1) for (x0, x1) in col_runs]
    else:
        rects = None
    if rects and len(rects) == n:
        return rects
    cw, ch = w / cols, h / rows  # 균등 격자
    out = []
    for i in range(n):
        r, c = divmod(i, cols)
        out.append((int(c * cw), int(r * ch), int((c + 1) * cw), int((r + 1) * ch)))
    return out


def get_icon_sheet(icon_prompts, debug_dir=None):
    """아이콘 여러 개를 시트 한 장(제미나이 1번 호출)으로 만들어 칸마다 잘라 돌려준다.

    결과: 항목마다 그림 바이트(JPEG) 또는 None(그 칸이 비었음 → 호출한 쪽이 그 항목만 따로 다시 만든다).
    시트 전체가 실패하면 전부 None. debug_dir를 주면 원본 시트를 sheet.jpg로 저장(시험용).
    """
    from PIL import Image
    n = len(icon_prompts)
    cols, rows = sheet_grid(n)
    listing = "; ".join(f"cell {i + 1}: {p}" for i, p in enumerate(icon_prompts))
    prompt = (SHEET_STYLE +
              f"Layout: exactly {rows} rows and {cols} columns of equal invisible cells ({cols * rows} cells, read left to right, "
              f"top to bottom), one character per cell, each centered in its own cell with wide empty white space around it "
              f"so no character touches another or the edge. "
              + (f"The last {cols * rows - n} cell(s) stay empty white. " if cols * rows > n else "")
              + "Characters: " + listing)
    try:
        sheet = Image.open(io.BytesIO(_gemini([{"text": prompt}], "16:9" if cols == 5 else "4:3"))).convert("RGB")
    except Exception as e:
        print(f"[images] Gemini 아이콘 시트 실패: {e}")
        return [None] * n
    if debug_dir:
        sheet.save(os.path.join(debug_dir, "sheet.jpg"), quality=90)
    out = []
    for rect in _split_sheet(sheet, n, cols, rows):
        cell = sheet.crop(rect)
        box = _ink(cell).getbbox()
        if not box or (box[2] - box[0]) < cell.width * 0.2 or (box[3] - box[1]) < cell.height * 0.2:
            out.append(None)  # 빈 칸
            continue
        side = max(cell.size)  # 정사각 흰 바탕에 올려 render.icon_image가 그대로 다듬게
        sq = Image.new("RGB", (side, side), "white")
        sq.paste(cell, ((side - cell.width) // 2, (side - cell.height) // 2))
        buf = io.BytesIO()
        sq.save(buf, "JPEG", quality=92)
        out.append(buf.getvalue())
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
