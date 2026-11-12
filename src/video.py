"""카드 사진들을 릴스용 세로 영상(MP4)으로 만든다.

2026-11-06 gil 요청(조회수 개선 3단계)으로 바뀜:
- 길이: 31초 → 약 12~15초. 표지 2초, 팁 카드는 15초 안에 들어가게 1.2~1.6초씩, 마지막 카드 2.2초.
  짧으면 끝까지 보는 비율이 높아지고, 끝나면 처음부터 다시 돌아 한 번 더 보게 됨
- 첫 화면 문구: 영상 맨 위에 노란 띠로 질문형 한 줄(hook)을 처음부터 끝까지 띄움
- 배경음악: music/ 폴더의 무료(CC0) 곡을 초안마다 하나 골라 넣음 (music.py). 곡이 없으면 무음

- 화면: 2026-11-12 gil 요청으로 카드 사진 크기 그대로 1080×1350 (4:5).
  예전엔 1080×1920(9:16)에 카드를 줄여 넣고 빈 곳을 흐린 배경으로 채웠는데, 이제는 카드가 화면 전체를 채움.
  문구 띠는 카드 위쪽(계정 이름 아래, 사진 부분)에 얹음. 글씨는 카드 아래쪽이라 가리지 않음
- 첫 장면이 표지 그대로라 릴스 썸네일도 표지가 됨

2026-11-12 gil 요청 (공개 인스타 스킬 규칙 반영):
- 2번 '왜 알아야 할까요' 카드 1.6초, 끝에서 두 번째 '한눈에 정리' 카드 2.2초 (extra=True일 때)
- 마지막 카드 동안은 맨 위 문구가 hook 대신 loop 문구로 바뀜. hook 낱말을 다시 말해서
  영상이 처음으로 돌아갈 때 자연스럽게 이어지고 한 번 더 보게 됨

ffmpeg는 서버에 깔린 게 있으면 쓰고, 없으면 imageio-ffmpeg 패키지에 든 것을 쓴다.
실행: python src/video.py drafts/20261105-0700 ["첫 화면 문구"]  → 그 폴더에 reel.mp4 생성
"""

import shutil
import subprocess
import sys
from pathlib import Path

W, H, FPS = 1080, 1350, 30  # 릴스 화면 = 카드 사진 크기(4:5)
STORY_H = 1920  # 스토리 사진은 세로 꽉 찬 9:16 그대로
FADE = 0.25  # 장 사이 넘어가는 시간(초)
CARD_W = 950  # 스토리 사진 안에 넣는 카드 너비(px)
HOOK_Y = 150  # 문구 띠 윗변 (카드 맨 위 계정 이름·쪽번호 아래)
TARGET = 15.0                      # 목표 길이(초)
COVER_SEC, LAST_SEC = 2.0, 2.2
TIP_MIN, TIP_MAX = 1.2, 1.6
STAKE_SEC, RECAP_SEC = 1.6, 2.2    # extra 카드 (2번 '왜', 끝에서 두 번째 '정리')
TARGET_EXTRA = 16.5                # extra 카드가 있을 때 목표 길이


def ffmpeg():
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    import imageio_ffmpeg  # pip 패키지에 든 ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def durations(n, extra=False):
    """카드 n장의 화면 시간(초). 팁 카드는 전체가 약 15초가 되게 1.2~1.6초 사이로 맞춘다.
    extra: 표지 다음 '왜' 카드와 마지막 앞 '정리' 카드가 있는 새 구성(2026-11-12~)."""
    if n == 1:
        return [LAST_SEC]
    if extra and n >= 5:
        tips = n - 4
        fixed = COVER_SEC + STAKE_SEC + RECAP_SEC + LAST_SEC
        tip = min(TIP_MAX, max(TIP_MIN, (TARGET_EXTRA - fixed) / tips))
        return [COVER_SEC, STAKE_SEC] + [round(tip, 2)] * tips + [RECAP_SEC, LAST_SEC]
    tips = n - 2
    tip = min(TIP_MAX, max(TIP_MIN, (TARGET - COVER_SEC - LAST_SEC) / tips)) if tips else 0
    return [COVER_SEC] + [round(tip, 2)] * tips + [LAST_SEC]


def hook_image(text, out_path):
    """첫 화면 문구를 노란 띠 그림(투명 배경 PNG, 1080 너비)으로 만든다."""
    from PIL import Image, ImageDraw
    import render
    text = " ".join((text or "").split())
    size = 70
    while size > 44:
        f = render.font("ExtraBold", size)
        if f.getlength(text) <= W - 140:
            break
        size -= 4
    lines = [text]
    if f.getlength(text) > W - 140:  # 그래도 길면 두 줄로
        words = text.split(" ")
        best = min(range(1, len(words)), key=lambda i: abs(f.getlength(" ".join(words[:i]))
                                                               - f.getlength(" ".join(words[i:]))), default=1)
        lines = [" ".join(words[:best]), " ".join(words[best:])]
    line_h = int(size * 1.25)
    box_w = int(max(f.getlength(ln) for ln in lines)) + 80
    box_h = line_h * len(lines) + 44
    im = Image.new("RGBA", (W, box_h + 20), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    x0 = (W - box_w) // 2
    d.rounded_rectangle([x0 + 6, 10, x0 + box_w + 6, box_h + 10], radius=28, fill=(0, 0, 0, 90))  # 그림자
    d.rounded_rectangle([x0, 4, x0 + box_w, box_h + 4], radius=28, fill=(255, 212, 59, 255))
    y = 4 + 22
    for ln in lines:
        d.text(((W - f.getlength(ln)) / 2, y), ln, font=f, fill=(34, 30, 28, 255))
        y += line_h
    im.save(out_path)
    return out_path


def story_image(card_path, out_path, text="새 게시물이 올라왔어요"):
    """새 게시물 알림용 스토리 사진(1080×1920 JPG): 흐린 배경 + 카드 + 위쪽 노란 띠 문구."""
    from PIL import Image, ImageEnhance, ImageFilter
    H = STORY_H
    card = Image.open(card_path).convert("RGB")
    scale = max(W / card.width, H / card.height)
    bg = card.resize((round(card.width * scale), round(card.height * scale)))
    left, top = (bg.width - W) // 2, (bg.height - H) // 2
    bg = bg.crop((left, top, left + W, top + H)).filter(ImageFilter.GaussianBlur(40))
    bg = ImageEnhance.Brightness(bg).enhance(0.85)
    small = card.resize((CARD_W, round(card.height * CARD_W / card.width)))
    bg.paste(small, ((W - CARD_W) // 2, (H - small.height) // 2 + 60))
    band = Image.open(hook_image(text, Path(out_path).with_name("story_band.png")))
    bg.paste(band, (0, (H - small.height) // 2 + 60 - band.height - 30), band)
    bg.save(out_path, quality=92)
    return Path(out_path)


def make_reel(card_paths, out_path, hook="", music=None, loop="", extra=False):
    """카드 사진 경로 목록 → 릴스 MP4. hook: 맨 위 문구(없으면 생략), music: 배경음악 파일(없으면 무음),
    loop: 마지막 카드 동안 hook 대신 띄울 문구(없으면 hook 그대로), extra: durations 참고.
    만든 파일 경로를 돌려준다."""
    cards = [str(p) for p in card_paths]
    if not cards:
        raise RuntimeError("영상으로 만들 카드가 없어요")
    secs = durations(len(cards), extra)
    # 넘어가는 동안 겹치는 시간만큼 앞뒤 장면을 조금 더 길게 둔다
    lens = [s + (FADE if i < len(cards) - 1 else 0) for i, s in enumerate(secs)]
    total = sum(secs)

    cmd = [ffmpeg(), "-y", "-loglevel", "error"]
    for path, length in zip(cards, lens):
        cmd += ["-loop", "1", "-framerate", str(FPS), "-t", f"{length:.2f}", "-i", path]
    audio = len(cards)
    if music:
        cmd += ["-stream_loop", "-1", "-i", str(music)]
    else:
        cmd += ["-f", "lavfi", "-t", f"{total:.2f}", "-i", "anullsrc=r=48000:cl=stereo"]
    hook_in = None
    if hook:
        hook_in = len(cards) + 1
        cmd += ["-i", str(hook_image(hook, Path(out_path).with_name("hook.png")))]
    loop_in = None
    if hook and loop and len(cards) > 1:
        loop_in = len(cards) + 2
        cmd += ["-i", str(hook_image(loop, Path(out_path).with_name("loop.png")))]
    last_start = total - secs[-1]

    parts = []
    for i in range(len(cards)):
        parts.append(
            f"[{i}:v]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
            f"fps={FPS},format=yuv420p,setsar=1,setpts=PTS-STARTPTS[v{i}]"
        )
    last = "v0"
    elapsed = 0.0
    for i in range(1, len(cards)):
        elapsed += secs[i - 1]
        out = f"x{i}"
        parts.append(f"[{last}][v{i}]xfade=transition=fade:duration={FADE}:offset={elapsed:.2f}[{out}]")
        last = out
    if hook_in is not None:
        until = f":enable='lt(t,{last_start:.2f})'" if loop_in is not None else ""
        parts.append(f"[{last}][{hook_in}:v]overlay=0:{HOOK_Y}:format=auto{until},format=yuv420p,setsar=1[hk]")
        last = "hk"
    if loop_in is not None:
        parts.append(f"[{last}][{loop_in}:v]overlay=0:{HOOK_Y}:format=auto:enable='gte(t,{last_start:.2f})',"
                     f"format=yuv420p,setsar=1[lp]")
        last = "lp"
    if music:  # 처음은 살짝 키우고, 끝 1초는 줄여서 다시 처음으로 돌 때 어색하지 않게
        parts.append(f"[{audio}:a]atrim=0:{total:.2f},asetpts=PTS-STARTPTS,volume=0.85,"
                     f"afade=t=in:d=0.2,afade=t=out:st={max(0, total - 1):.2f}:d=1[au]")
        amap = "[au]"
    else:
        amap = f"{audio}:a"
    cmd += ["-filter_complex", ";".join(parts), "-map", f"[{last}]", "-map", amap,
            "-c:v", "libx264", "-profile:v", "high", "-preset", "medium", "-crf", "21",
            "-pix_fmt", "yuv420p", "-r", str(FPS),
            "-c:a", "aac", "-b:a", "128k", "-ar", "48000",
            "-t", f"{total:.2f}", "-movflags", "+faststart", str(out_path)]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"릴스 영상 만들기 실패: {result.stderr.strip()[-300:]}")
    return Path(out_path)


if __name__ == "__main__":
    import music as music_lib
    folder = Path(sys.argv[1])
    paths = sorted(folder.glob("card*.jpg"), key=lambda p: int(p.stem[4:]))
    out = make_reel(paths, folder / "reel.mp4", sys.argv[2] if len(sys.argv) > 2 else "",
                    music_lib.pick(folder.name))
    print(f"{out} ({out.stat().st_size / 1e6:.1f}MB, 카드 {len(paths)}장, {sum(durations(len(paths), len(paths) >= 9)):.1f}초)")
