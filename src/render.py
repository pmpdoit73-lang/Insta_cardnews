"""카드뉴스 합성: 배경 사진 위에 한글 글씨를 얹어 1080x1350 JPG를 만든다.

지금 쓰는 디자인은 목록형(render_list, 8~10장)과 인포그래픽형(render_info, 2장, 하루 1번).
A·B·C안(render, 5장)은 예전 시안으로 남겨 둠.

제미나이는 한글 글씨를 자주 깨뜨리므로 사진에는 글씨를 넣지 않고,
제목·본문·CTA 글씨는 전부 여기서 Pillow로 그린다.

카드 내용(card) 형식:
{
  "label": "충격 뉴스",                          # 표지 위 작은 라벨
  "title": ["에어프라이어 냄새", "식초 2큰술로 끝"],
  "highlight": "식초 2큰술",                     # 제목에서 강조할 말 (없으면 "")
  "body": [                                      # 본문 카드 3장
    {"head": "핵심 1", "lines": ["...", "..."], "highlight": "..."},
  ],
  "cta": ["저장해두고", "가족한테도 알려주세요"],
  "handle": "@계정이름",
}
"""
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H = 1080, 1350
MARGIN = 60
FONT_DIR = Path(__file__).resolve().parent.parent / "fonts"
THEMES = ("A", "B", "C")


def font(weight, size):
    return ImageFont.truetype(str(FONT_DIR / f"Pretendard-{weight}.otf"), size)


# ---------- 배경 ----------

def placeholder(seed, w=W, h=H, tone=(70, 60, 50)):
    """사진이 없을 때(시험용) 쓰는 흐린 색 배경."""
    r = random.Random(seed)
    im = Image.new("RGB", (w, h), tone)
    d = ImageDraw.Draw(im)
    for _ in range(40):
        x, y, s = r.randint(-200, w), r.randint(-200, h), r.randint(120, 420)
        c = tuple(max(0, min(255, t + r.randint(-40, 90))) for t in tone)
        d.ellipse([x, y, x + s, y + s], fill=c)
    return im.filter(ImageFilter.GaussianBlur(60))


def load_photo(path, w, h, seed):
    """사진을 w x h에 꽉 차게 가운데 기준으로 잘라 넣는다."""
    if not path:
        return placeholder(seed, w, h)
    im = Image.open(path).convert("RGB")
    scale = max(w / im.width, h / im.height)
    im = im.resize((round(im.width * scale), round(im.height * scale)), Image.LANCZOS)
    left, top = (im.width - w) // 2, (im.height - h) // 2
    return im.crop((left, top, left + w, top + h))


def bottom_gradient(im, start, max_alpha):
    ov = Image.new("RGBA", im.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    for y in range(start, im.height):
        a = int(max_alpha * (y - start) / (im.height - start))
        d.line([(0, y), (im.width, y)], fill=(0, 0, 0, a))
    return Image.alpha_composite(im.convert("RGBA"), ov)


def darken(im, alpha):
    return Image.alpha_composite(im.convert("RGBA"), Image.new("RGBA", im.size, (0, 0, 0, alpha)))


def rounded_paste(base, photo, xy, radius=40):
    mask = Image.new("L", photo.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, *photo.size], radius, fill=255)
    base.paste(photo, xy, mask)


# ---------- 글씨 ----------

def fit(d, lines, weight, size, max_w):
    """가장 긴 줄이 max_w 안에 들어올 때까지 글씨를 줄인다."""
    while size > 30:
        f = font(weight, size)
        if all(d.textlength(ln, font=f) <= max_w for ln in lines):
            return f
        size -= 4
    return font(weight, size)


def draw_lines(d, lines, x, y, f, color, hl="", hl_color=None, hl_box=None,
               gap=1.3, center=False):
    """여러 줄을 그린다. hl(강조어)이 든 줄은 그 부분만 상자를 깔고 색을 바꾼다."""
    for ln in lines:
        lx = (W - d.textlength(ln, font=f)) / 2 if center else x
        if hl and hl in ln:
            before, after = ln.split(hl, 1)
            parts = [(before, color, None), (hl, hl_color, hl_box), (after, color, None)]
        else:
            parts = [(ln, color, None)]
        for text, col, box in parts:
            if box:
                bb = d.textbbox((lx, y), text, font=f)
                d.rectangle([bb[0] - 10, bb[1] - 8, bb[2] + 10, bb[3] + 10], fill=box)
            d.text((lx, y), text, font=f, fill=col)
            lx += d.textlength(text, font=f)
        y += int(f.size * gap)
    return y


def page_no(d, n, color):
    d.text((W - MARGIN, MARGIN), f"{n}/5", font=font("Bold", 30), fill=color, anchor="ra")


def footer(d, handle, color, center=False):
    f = font("SemiBold", 30)
    if center:
        d.text((W // 2, H - 110), handle, font=f, fill=color, anchor="ma")
    else:
        d.text((MARGIN, H - 80), handle, font=f, fill=color)


# ---------- A안: 뉴스 속보형 ----------

A_RED, A_YELLOW, A_DARK = (228, 30, 40), (255, 214, 0), (20, 20, 24)


def a_cover(c, photo):
    im = bottom_gradient(load_photo(photo, W, H, 1), 450, 235)
    d = ImageDraw.Draw(im)
    f = fit(d, c["title"], "Black", 92, W - 2 * MARGIN)
    title_h = int(f.size * 1.25) * len(c["title"])
    y = 1080 - title_h
    lf = font("Bold", 34)
    lw = d.textlength(c["label"], font=lf)
    d.rounded_rectangle([MARGIN, y - 90, MARGIN + lw + 50, y - 30], 12, fill=A_RED)
    d.text((MARGIN + 25, y - 60), c["label"], font=lf, fill="white", anchor="lm")
    draw_lines(d, c["title"], MARGIN, y, f, "white", c["highlight"], A_DARK, A_YELLOW, 1.25)
    d.text((MARGIN, 1110), "넘겨서 확인 →", font=font("SemiBold", 36), fill=A_YELLOW)
    footer(d, c["handle"], (220, 220, 220))
    page_no(d, 1, "white")
    return im


def a_body(c, b, n, photo):
    im = Image.new("RGBA", (W, H), "white")
    im.paste(load_photo(photo, W, 680, n), (0, 0))
    d = ImageDraw.Draw(im)
    d.rectangle([MARGIN, 740, MARGIN + 10, 840], fill=A_RED)
    d.text((MARGIN + 35, 740), b["head"], font=font("Bold", 40), fill=A_RED)
    f = fit(d, b["lines"], "Bold", 62, W - 2 * MARGIN - 35)
    draw_lines(d, b["lines"], MARGIN + 35, 810, f, (25, 25, 25), b.get("highlight", ""),
               (25, 25, 25), A_YELLOW, 1.4)
    footer(d, c["handle"], (120, 120, 120))
    page_no(d, n, "white")
    return im


def a_cta(c, photo):
    im = Image.new("RGBA", (W, H), A_DARK)
    d = ImageDraw.Draw(im)
    f = fit(d, c["cta"], "Black", 80, W - 2 * MARGIN)
    draw_lines(d, c["cta"], 0, 450, f, "white", gap=1.3, center=True)
    for i, (t, col) in enumerate([("저장", A_YELLOW), ("공유", (255, 255, 255)), ("팔로우", A_RED)]):
        x = 150 + i * 290
        d.rounded_rectangle([x, 800, x + 230, 890], 45, outline=col, width=5)
        d.text((x + 115, 845), t, font=font("Bold", 40), fill=col, anchor="mm")
    footer(d, c["handle"], (160, 160, 160))
    page_no(d, 5, "white")
    return im


# ---------- B안: 매거진형 ----------

B_CREAM, B_NAVY, B_ORANGE, B_HL = (247, 242, 232), (26, 47, 92), (232, 110, 40), (255, 226, 150)


def b_cover(c, photo):
    im = Image.new("RGBA", (W, H), B_CREAM)
    rounded_paste(im, load_photo(photo, W - 2 * MARGIN, 700, 1), (MARGIN, 560))
    d = ImageDraw.Draw(im)
    d.text((MARGIN, 110), c["label"], font=font("SemiBold", 34), fill=B_ORANGE)
    f = fit(d, c["title"], "ExtraBold", 88, W - 2 * MARGIN)
    draw_lines(d, c["title"], MARGIN, 180, f, B_NAVY, c["highlight"], B_NAVY, B_HL, 1.25)
    footer(d, c["handle"], B_NAVY)
    page_no(d, 1, B_NAVY)
    return im


def b_body(c, b, n, photo):
    im = Image.new("RGBA", (W, H), B_CREAM)
    rounded_paste(im, load_photo(photo, W - 2 * MARGIN, 520, n), (MARGIN, 700))
    d = ImageDraw.Draw(im)
    d.ellipse([MARGIN, 120, MARGIN + 120, 240], fill=B_ORANGE)
    d.text((MARGIN + 60, 180), str(n - 1), font=font("Black", 64), fill="white", anchor="mm")
    f = fit(d, b["lines"], "Bold", 66, W - 2 * MARGIN)
    draw_lines(d, b["lines"], MARGIN, 300, f, B_NAVY, b.get("highlight", ""), B_NAVY, B_HL, 1.4)
    footer(d, c["handle"], B_NAVY)
    page_no(d, n, B_NAVY)
    return im


def b_cta(c, photo):
    im = Image.new("RGBA", (W, H), B_NAVY)
    d = ImageDraw.Draw(im)
    f = fit(d, c["cta"], "ExtraBold", 80, W - 2 * MARGIN)
    draw_lines(d, c["cta"], 0, 440, f, B_CREAM, gap=1.3, center=True)
    d.rounded_rectangle([240, 780, 840, 890], 55, fill=B_ORANGE)
    d.text((540, 835), "저장하고 팔로우하기", font=font("Bold", 44), fill="white", anchor="mm")
    footer(d, c["handle"], B_CREAM)
    page_no(d, 5, B_CREAM)
    return im


# ---------- C안: 형광펜 노트형 ----------

C_LIME, C_INK = (190, 255, 80), (20, 20, 20)


def c_cover(c, photo):
    im = darken(load_photo(photo, W, H, 1), 140)
    d = ImageDraw.Draw(im)
    d.text((W // 2, 420), c["label"], font=font("SemiBold", 38), fill=C_LIME, anchor="ma")
    f = fit(d, c["title"], "Black", 90, W - 2 * MARGIN)
    draw_lines(d, c["title"], 0, 520, f, "white", c["highlight"], C_INK, C_LIME, 1.4, center=True)
    footer(d, c["handle"], "white", center=True)
    page_no(d, 1, "white")
    return im


def c_body(c, b, n, photo):
    im = darken(load_photo(photo, W, H, n), 170)
    d = ImageDraw.Draw(im)
    d.text((W // 2, 380), b["head"], font=font("SemiBold", 38), fill=C_LIME, anchor="ma")
    f = fit(d, b["lines"], "Bold", 68, W - 2 * MARGIN)
    draw_lines(d, b["lines"], 0, 480, f, "white", b.get("highlight", ""), C_INK, C_LIME, 1.6,
               center=True)
    footer(d, c["handle"], "white", center=True)
    page_no(d, n, "white")
    return im


def c_cta(c, photo):
    im = Image.new("RGBA", (W, H), C_LIME)
    d = ImageDraw.Draw(im)
    f = fit(d, c["cta"], "Black", 82, W - 2 * MARGIN)
    draw_lines(d, c["cta"], 0, 480, f, C_INK, gap=1.3, center=True)
    d.text((W // 2, 820), "저장 · 공유 · 팔로우", font=font("Bold", 46), fill=C_INK, anchor="ma")
    footer(d, c["handle"], C_INK, center=True)
    page_no(d, 5, C_INK)
    return im


LAYOUTS = {
    "A": (a_cover, a_body, a_cta),
    "B": (b_cover, b_body, b_cta),
    "C": (c_cover, c_body, c_cta),
}


def render(card, photos, out_dir, theme="A"):
    """카드 5장을 out_dir/card1.jpg ~ card5.jpg로 저장하고 경로 목록을 돌려준다.

    photos: 카드 5장에 쓸 배경 사진 경로 5개 (None이면 시험용 흐린 배경).
    """
    cover, body, cta = LAYOUTS[theme]
    photos = list(photos) + [None] * (5 - len(photos))
    images = [cover(card, photos[0])]
    for i, b in enumerate(card["body"][:3]):
        images.append(body(card, b, i + 2, photos[i + 1]))
    images.append(cta(card, photos[4]))

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    paths = []
    for i, im in enumerate(images, 1):
        p = out / f"card{i}.jpg"
        im.convert("RGB").save(p, "JPEG", quality=92)  # 인스타 API는 JPG만 받음
        paths.append(p)
    return paths


# ---------- 목록형 (2026-10-23~, 지금 쓰는 디자인) ----------
# 모든 장이 같은 구성: 사진 전체 + 아래쪽 어두운 그라데이션 + 가운데 정렬 흰 글씨.
# 왼쪽 위 @계정, 오른쪽 위 "2/10" 쪽번호. 강조는 노란색(번호, 표지 강조어, 저장 유도).

L_GRAY = (215, 215, 215)


def l_frame(photo, seed, n, total, handle):
    """사진 + 아래 그라데이션 + 위쪽 계정·쪽번호 알약."""
    im = bottom_gradient(load_photo(photo, W, H, seed), 480, 250)
    ov = Image.new("RGBA", im.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    pf = font("Bold", 34)
    label = f"{n}/{total}"
    pw = d.textlength(label, font=pf)
    d.rounded_rectangle([W - MARGIN - pw - 56, MARGIN, W - MARGIN, MARGIN + 70], 35, fill=(25, 25, 25, 170))
    d.text((W - MARGIN - (pw + 56) / 2, MARGIN + 35), label, font=pf, fill="white", anchor="mm")
    if handle:
        hf = font("SemiBold", 30)
        hw = d.textlength(handle, font=hf)
        d.rounded_rectangle([MARGIN, MARGIN, MARGIN + hw + 50, MARGIN + 70], 35, fill=(255, 255, 255, 215))
        d.text((MARGIN + 25, MARGIN + 35), handle, font=hf, fill=(30, 30, 30), anchor="lm")
    return Image.alpha_composite(im, ov)


def stack(d, blocks, bottom):
    """글씨 덩어리들을 아래(bottom)에 맞춰 위에서부터 가운데 정렬로 그린다.

    blocks: [(줄 목록, 글꼴, 색, 줄 간격 배수, 덩어리 아래 여백, 강조어)]
    """
    heights = [int(f.size * gap) * len(lines) + after for lines, f, _, gap, after, _ in blocks]
    y = bottom - sum(heights)
    for (lines, f, color, gap, after, hl), h in zip(blocks, heights):
        draw_lines(d, lines, 0, y, f, color, hl, A_DARK, A_YELLOW, gap, center=True)
        y += h


def l_cover(c, photo, total):
    im = l_frame(photo, 1, 1, total, c["handle"])
    d = ImageDraw.Draw(im)
    width = W - 2 * MARGIN
    tf = fit(d, c["title"], "Black", 100, width)
    blocks = [
        (c["title"], tf, "white", 1.22, 20, c.get("highlight", "")),
        ([c["subtitle"]], fit(d, [c["subtitle"]], "Medium", 46, width), "white", 1.3, 50, ""),
        (["넘겨서 확인하기 →"], font("SemiBold", 36), A_YELLOW, 1.2, 0, ""),
    ]
    stack(d, blocks, H - 70)
    lf = font("Bold", 32)  # 표지 라벨(가전 꿀팁 등)은 제목 위 가운데
    lw = d.textlength(c["label"], font=lf)
    top = H - 70 - sum(int(f.size * g) * len(ls) + a for ls, f, _, g, a, _ in blocks) - 80
    d.rounded_rectangle([(W - lw) / 2 - 25, top, (W + lw) / 2 + 25, top + 56], 12, fill=A_RED)
    d.text((W / 2, top + 28), c["label"], font=lf, fill="white", anchor="mm")
    return im


def l_tip(c, t, i, n, photo, total):
    im = l_frame(photo, n, n, total, c["handle"])
    d = ImageDraw.Draw(im)
    width = W - 2 * MARGIN
    blocks = [
        ([f"{i:02d}"], font("Black", 96), A_YELLOW, 1.1, 5, ""),
        ([t["title"]], fit(d, [t["title"]], "Black", 92, width), "white", 1.25, 25, ""),
        (t["lines"], fit(d, t["lines"], "Medium", 46, width), "white", 1.45, 0, ""),
    ]
    if t.get("note"):
        blocks[-1] = blocks[-1][:4] + (25, "")
        blocks.append(([t["note"]], fit(d, [t["note"]], "Medium", 34, width), L_GRAY, 1.3, 0, ""))
    stack(d, blocks, H - 90)
    return im


def l_end(c, w, n, photo, total):
    im = l_frame(photo, n, n, total, c["handle"])
    d = ImageDraw.Draw(im)
    width = W - 2 * MARGIN
    blocks = [
        ([w["title"]], fit(d, [w["title"]], "Black", 84, width), "white", 1.25, 25, ""),
        (w["lines"], fit(d, w["lines"], "Medium", 38, width), "white", 1.5, 45, ""),
        ([c["slogan"]], font("Medium", 32), L_GRAY, 1.3, 20, ""),
        ([c["save_line"]], fit(d, [c["save_line"]], "Bold", 42, width), A_YELLOW, 1.2, 0, ""),
    ]
    stack(d, blocks, H - 80)
    return im


def render_list(card, photos, out_dir):
    """목록형 카드(표지 + 팁 N장 + 마무리)를 out_dir/card1.jpg ~ 로 저장하고 경로 목록을 돌려준다.

    card: {"label", "title", "highlight", "subtitle", "tips": [{"title", "lines", "note"}],
           "warning": {"title", "lines"}, "save_line", "slogan", "handle"}
    photos: 장마다 배경 사진 경로 (None이면 시험용 흐린 배경).
    """
    tips = card["tips"]
    total = len(tips) + 2
    photos = list(photos) + [None] * (total - len(photos))
    images = [l_cover(card, photos[0], total)]
    for i, t in enumerate(tips, 1):
        images.append(l_tip(card, t, i, i + 1, photos[i], total))
    images.append(l_end(card, card["warning"], total, photos[-1], total))

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("card*.jpg"):  # 장수가 줄었을 때 남는 옛 카드 지우기
        old.unlink()
    paths = []
    for i, im in enumerate(images, 1):
        p = out / f"card{i}.jpg"
        im.convert("RGB").save(p, "JPEG", quality=92)  # 인스타 API는 JPG만 받음
        paths.append(p)
    return paths


LIST_SAMPLE = {
    "label": "가전 꿀팁",
    "title": ["기름때 확 줄이는", "에어프라이어 관리법 6"],
    "highlight": "기름때",
    "subtitle": "굽기만 하고 청소는 미루셨죠?",
    "tips": [
        {"title": "바스켓 불리기", "lines": ["뜨거운 물에 주방세제 한 방울, 10분", "박박 문지르지 않아도 기름이 녹아요"],
         "note": "철수세미는 코팅이 벗겨져요"},
        {"title": "종이호일 깔기", "lines": ["바스켓 크기에 맞춰 구멍 난 걸로", "공기가 돌아서 바삭함은 그대로예요"],
         "note": ""},
        {"title": "열선 닦기", "lines": ["전원 뽑고 식힌 뒤 마른 솔로", "탄 냄새가 확 줄어요"], "note": ""},
        {"title": "냄새 빼기", "lines": ["물 1컵 + 식초 2큰술, 180도 5분", "생선 냄새가 남지 않아요"], "note": ""},
        {"title": "겉면 닦기", "lines": ["물기 꽉 짠 행주로 한 번", "손때가 쌓이지 않아요"], "note": ""},
        {"title": "말려서 넣기", "lines": ["씻은 바스켓은 30분 말리기", "녹과 곰팡이를 막아요"], "note": ""},
    ],
    "warning": {"title": "이건 절대 하지 마세요",
                "lines": ["바스켓 없이 돌리기, 본체 물에 담그기는 고장 나요",
                          "알루미늄 호일은 열선에 닿지 않게 깔아 주세요"]},
    "save_line": "저장해두고 청소할 때 꺼내보세요",
    "slogan": "주방의 질을 높이는 살림 꿀팁",
    "handle": "@kingreview0669",
}


# ---------- 인포그래픽형 (2026-10-30~, 하루 1번) ----------
# 1장: 크림 배경 한 장짜리 총정리표. 저장 배지 → 큰 제목(강조어 주황) → 기준 한 줄 → 3열 번호 칸
#      (칸마다 번호·이름·만화 그림·숫자 배지, 5번째 칸은 '저장!', 마지막 칸은 '체크') → 아래 저장 유도 한 줄
# 2장: 같은 배경에 책갈피 + 경고 + 저장 유도

I_CREAM, I_YELLOW, I_PALE = (255, 248, 230), (255, 205, 60), (255, 241, 196)
I_ORANGE, I_DARK, I_LINE, I_GRAY = (245, 120, 20), (45, 36, 28), (240, 210, 140), (120, 110, 100)
I_GAP = 14
EMOJI_FONT = Path("/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf")


def pill(d, cx, top, text, f, fill, color, pad=28, h=None):
    """가운데 cx에 알약 모양 상자 + 글씨. 상자 아래 y를 돌려준다."""
    h = h or int(f.size * 1.7)
    w = d.textlength(text, font=f) + 2 * pad
    d.rounded_rectangle([cx - w / 2, top, cx + w / 2, top + h], h // 2, fill=fill)
    d.text((cx, top + h / 2), text, font=f, fill=color, anchor="mm")
    return top + h


def emoji_icon(ch, size):
    """그림이 없을 때 이모지를 size 크기 그림으로 (글꼴이 없으면 None)."""
    if not ch or not EMOJI_FONT.exists():
        return None
    try:
        f = ImageFont.truetype(str(EMOJI_FONT), 109)  # 컬러 이모지 글꼴은 109 크기만 됨
        im = Image.new("RGBA", (136, 128), (0, 0, 0, 0))
        ImageDraw.Draw(im).text((68, 64), ch, font=f, embedded_color=True, anchor="mm")
        box = im.getbbox()
        return im.crop(box).resize((size, size), Image.LANCZOS) if box else None
    except Exception:
        return None


def icon_image(path, emoji, size):
    if path:
        im = Image.open(path).convert("RGB")
        side = min(im.size)
        left, top = (im.width - side) // 2, (im.height - side) // 2
        return im.crop((left, top, left + side, top + side)).resize((size, size), Image.LANCZOS)
    return emoji_icon(emoji, size)


def i_title(d, lines, hl, top, width):
    """큰 제목: 강조어만 주황색. 제목 아래 y를 돌려준다."""
    f = fit(d, lines, "Black", 92, width)
    y = top
    for ln in lines:
        parts = ln.split(hl, 1) if hl and hl in ln else [ln]
        segs = [(parts[0], I_DARK)] + ([(hl, I_ORANGE), (parts[1], I_DARK)] if len(parts) == 2 else [])
        x = (W - d.textlength(ln, font=f)) / 2
        for text, col in segs:
            d.text((x, y), text, font=f, fill=col)
            x += d.textlength(text, font=f)
        y += int(f.size * 1.18)
    return y


def i_item(im, d, box, n, item, icon):
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    d.rounded_rectangle(box, 24, fill="white", outline=I_LINE, width=3)
    r = 24  # 번호 동그라미
    d.ellipse([x0 + 14, y0 + 14, x0 + 14 + 2 * r, y0 + 14 + 2 * r], fill=I_YELLOW)
    d.text((x0 + 14 + r, y0 + 14 + r), str(n), font=font("Black", 30), fill=I_DARK, anchor="mm")
    nf = fit(d, [item["name"]], "ExtraBold", 34, w - 2 * r - 40)
    d.text((x0 + 2 * r + 26, y0 + 14 + r), item["name"], font=nf, fill=I_DARK, anchor="lm")
    top = y0 + 2 * r + 24
    side = min(h - (top - y0) - 12, int(w * 0.46))
    if icon is not None:
        ic = icon.resize((side, side), Image.LANCZOS)
        im.paste(ic, (x0 + 12, top), ic if ic.mode == "RGBA" else None)
    bx0 = x0 + 12 + side + 6
    bw = x1 - 12 - bx0
    bf = fit(d, [item["badge"]], "Black", 40, bw - 24)
    bh = int(bf.size * 1.7)
    by = top + (side - bh) / 2
    d.rounded_rectangle([bx0, by, bx0 + bw, by + bh], bh // 2, fill=I_PALE)
    d.text((bx0 + bw / 2, by + bh / 2), item["badge"], font=bf, fill=I_ORANGE, anchor="mm")


def i_save_tile(d, box, lines):
    x0, y0, x1, y1 = box
    d.rounded_rectangle(box, 24, fill=I_YELLOW)
    lf = fit(d, lines, "Bold", 34, x1 - x0 - 30)
    sf = font("Black", 72)
    total = int(lf.size * 1.3) * len(lines) + sf.size
    y = y0 + (y1 - y0 - total) / 2
    for ln in lines:
        d.text(((x0 + x1) / 2, y), ln, font=lf, fill=I_DARK, anchor="ma")
        y += int(lf.size * 1.3)
    d.text(((x0 + x1) / 2, y), "저장!", font=sf, fill=(220, 60, 30), anchor="ma")


def i_check_tile(d, box, check):
    x0, y0, x1, y1 = box
    d.rounded_rectangle(box, 24, fill=I_PALE, outline=I_YELLOW, width=3)
    tf = fit(d, ["✓ " + check["title"]], "ExtraBold", 34, x1 - x0 - 30)
    lf = fit(d, check["lines"], "Medium", 28, x1 - x0 - 30)
    total = int(tf.size * 1.5) + int(lf.size * 1.35) * len(check["lines"])
    y = y0 + (y1 - y0 - total) / 2
    d.text(((x0 + x1) / 2, y), "✓ " + check["title"], font=tf, fill=I_ORANGE, anchor="ma")
    y += int(tf.size * 1.5)
    for ln in check["lines"]:
        d.text(((x0 + x1) / 2, y), ln, font=lf, fill=I_DARK, anchor="ma")
        y += int(lf.size * 1.35)


def i_footer(d, line, hl, handle):
    f = fit(d, [line], "ExtraBold", 40, W - 2 * MARGIN)
    y = H - 104
    parts = line.split(hl, 1) if hl and hl in line else [line]
    segs = [(parts[0], I_DARK)] + ([(hl, I_ORANGE), (parts[1], I_DARK)] if len(parts) == 2 else [])
    x = (W - d.textlength(line, font=f)) / 2
    for text, col in segs:
        d.text((x, y), text, font=f, fill=col)
        x += d.textlength(text, font=f)
    if handle:
        d.text((W / 2, H - 42), handle, font=font("SemiBold", 26), fill=I_GRAY, anchor="mm")


def info_sheet(c, icons):
    im = Image.new("RGB", (W, H), I_CREAM)
    d = ImageDraw.Draw(im)
    side = 40
    width = W - 2 * side
    y = pill(d, W / 2, 34, "★ " + c["top_badge"], font("ExtraBold", 32), I_YELLOW, I_DARK)
    y = i_title(d, c["title"], c.get("highlight", ""), y + 18, width)
    y = pill(d, W / 2, y + 6, c["basis"], fit(d, [c["basis"]], "SemiBold", 28, width - 60),
             "white", I_GRAY, h=50) + 18

    items = c["items"]
    cells = len(items) + 2
    cols = 3
    rows = -(-cells // cols)
    save_at = 4 if rows > 1 else 1
    order = list(range(len(items)))
    order.insert(save_at, "save")
    order.append("check")
    cw = (width - (cols - 1) * I_GAP) / cols
    ch = (H - 128 - y - (rows - 1) * I_GAP) / rows
    for k, what in enumerate(order):
        r, col = divmod(k, cols)
        x0 = side + col * (cw + I_GAP)
        y0 = y + r * (ch + I_GAP)
        box = (int(x0), int(y0), int(x0 + cw), int(y0 + ch))
        if what == "save":
            i_save_tile(d, box, c["save_tile"])
        elif what == "check":
            i_check_tile(d, box, c["check"])
        else:
            i_item(im, d, box, what + 1, items[what], icons[what])
    i_footer(d, c["footer_line"], c.get("footer_highlight", ""), c.get("handle", ""))
    return im


def info_end(c):
    im = Image.new("RGB", (W, H), I_CREAM)
    d = ImageDraw.Draw(im)
    width = W - 2 * MARGIN
    bx, by, bw, bh = W / 2 - 70, 230, 140, 190  # 책갈피
    d.polygon([(bx, by), (bx + bw, by), (bx + bw, by + bh), (bx + bw / 2, by + bh - 50), (bx, by + bh)],
              fill=I_YELLOW)
    d.text((W / 2, by + 75), "SAVE", font=font("Black", 40), fill=I_DARK, anchor="mm")
    w = c["warning"]
    tf = fit(d, [w["title"]], "Black", 80, width)
    y = 510
    d.text((W / 2, y), w["title"], font=tf, fill=I_DARK, anchor="ma")
    y += int(tf.size * 1.5)
    lf = fit(d, w["lines"], "Medium", 40, width - 60)
    lh = int(lf.size * 1.6)
    box_h = lh * len(w["lines"]) + 70
    d.rounded_rectangle([MARGIN, y, W - MARGIN, y + box_h], 30, fill="white", outline=I_LINE, width=3)
    yy = y + 35
    for ln in w["lines"]:
        d.text((W / 2, yy), ln, font=lf, fill=I_DARK, anchor="ma")
        yy += lh
    y += box_h + 70
    sf = fit(d, [c["save_line"]], "ExtraBold", 50, width)
    pill(d, W / 2, y, c["save_line"], sf, I_YELLOW, I_DARK, pad=40)
    d.text((W / 2, H - 150), c["slogan"], font=font("Medium", 32), fill=I_GRAY, anchor="mm")
    if c.get("handle"):
        d.text((W / 2, H - 95), c["handle"], font=font("SemiBold", 30), fill=I_GRAY, anchor="mm")
    return im


def render_info(card, icons, out_dir):
    """인포그래픽형 2장(총정리표 + 저장·주의)을 out_dir/card1.jpg, card2.jpg로 저장하고 경로 목록을 돌려준다.

    card: {"top_badge", "title", "highlight", "basis", "items": [{"name", "badge", "emoji"}],
           "save_tile", "check": {"title", "lines"}, "footer_line", "footer_highlight",
           "warning": {"title", "lines"}, "save_line", "slogan", "handle"}
    icons: 항목마다 그림 경로 (None이면 이모지로 대신).
    """
    items = card["items"]
    icons = list(icons) + [None] * (len(items) - len(icons))
    side = 200
    pics = [icon_image(p, it.get("emoji", ""), side) for p, it in zip(icons, items)]
    images = [info_sheet(card, pics), info_end(card)]

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("card*.jpg"):
        old.unlink()
    paths = []
    for i, im in enumerate(images, 1):
        p = out / f"card{i}.jpg"
        im.convert("RGB").save(p, "JPEG", quality=94)
        paths.append(p)
    return paths


INFO_SAMPLE = {
    "top_badge": "장보기 전 저장하세요!",
    "title": ["버리기 아까운 식재료", "냉장 보관기한 10"],
    "highlight": "냉장 보관기한",
    "basis": "개봉 전·냉장(0~5도) 기준 · 일반 권장 기간",
    "items": [
        {"name": "달걀", "badge": "3~5주", "emoji": "🥚"},
        {"name": "우유", "badge": "개봉 3일", "emoji": "🥛"},
        {"name": "두부", "badge": "2~3일", "emoji": "🧈"},
        {"name": "다진 고기", "badge": "1~2일", "emoji": "🥩"},
        {"name": "생선", "badge": "1~2일", "emoji": "🐟"},
        {"name": "버섯", "badge": "5~7일", "emoji": "🍄"},
        {"name": "당근", "badge": "2~3주", "emoji": "🥕"},
        {"name": "식빵", "badge": "냉동 권장", "emoji": "🍞"},
        {"name": "치즈", "badge": "개봉 3주", "emoji": "🧀"},
        {"name": "대파", "badge": "1~2주", "emoji": "🥬"},
    ],
    "save_tile": ["장볼 때", "꺼내 보는 표"],
    "check": {"title": "보관 전 체크", "lines": ["냄새·색이", "변하면 버려요"]},
    "footer_line": "저장해두고 장보기 전 꺼내보세요",
    "footer_highlight": "장보기 전",
    "warning": {"title": "이건 절대 하지 마세요",
                "lines": ["녹은 고기를 다시 얼리기", "세균이 늘어 맛도 안전도 떨어져요",
                          "뜨거운 음식은 식혀서 넣어 주세요"]},
    "save_line": "저장해두고 장보기 전 꺼내보세요",
    "slogan": "주방의 질을 높이는 살림 꿀팁",
    "handle": "@salim.kkultip",
}


SAMPLE = {
    "label": "가전 꿀팁",
    "title": ["에어프라이어 냄새", "식초 2큰술로 끝"],
    "highlight": "식초 2큰술",
    "body": [
        {"head": "핵심 1", "lines": ["모르고 지나가면", "한 달에 만 원 넘게", "더 낼 수도 있어요."],
         "highlight": "만 원 넘게"},
        {"head": "핵심 2", "lines": ["바뀌는 건", "딱 한 줄인데", "이게 제일 중요해요."],
         "highlight": "딱 한 줄"},
        {"head": "핵심 3", "lines": ["고지서 받으면", "이 칸부터", "꼭 확인하세요."],
         "highlight": "이 칸부터"},
    ],
    "cta": ["저장해두고", "가족한테도 알려주세요"],
    "handle": "@계정이름",
}

if __name__ == "__main__":
    import sys

    theme = sys.argv[1] if len(sys.argv) > 1 else "L"
    out = sys.argv[2] if len(sys.argv) > 2 else f"sample_{theme}"
    if theme == "L":
        paths = render_list(LIST_SAMPLE, [], out)
    elif theme == "I":
        paths = render_info(INFO_SAMPLE, [], out)
    else:
        paths = render(SAMPLE, [], out, theme)
    for p in paths:
        print(p)
