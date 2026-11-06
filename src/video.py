"""카드 사진들을 릴스용 세로 영상(MP4)으로 만든다. 배경음악은 넣지 않는다 (2026-11-04 gil 요청).

- 화면: 1080×1920 (9:16). 카드(1080×1350)는 가운데보다 조금 위(아래쪽 캡션·버튼에 글씨가 덜 가리게),
  위아래 빈 곳은 같은 카드를 흐리게 키워서 채움
- 길이: 표지 2.5초, 팁 카드 3.5초, 마지막 카드 4초, 장 사이 0.4초 부드럽게 넘어감
- 소리: 무음 트랙만 넣음 (소리 트랙이 아예 없으면 거절하는 기기·앱이 있어서)
- 첫 장면이 표지 그대로라 릴스 썸네일도 표지가 됨

ffmpeg는 서버에 깔린 게 있으면 쓰고, 없으면 imageio-ffmpeg 패키지에 든 것을 쓴다
(GitHub Actions 서버에 ffmpeg가 없어 11/05·11/06 릴스가 실패함).
실행: python src/video.py drafts/20261105-0700  → 그 폴더에 reel.mp4 생성
"""

import shutil
import subprocess
import sys
from pathlib import Path

W, H, FPS = 1080, 1920, 30
FADE = 0.4  # 장 사이 넘어가는 시간(초)
TOP = 150   # 카드 윗변 위치(px). 가운데(285)보다 위로 올려 릴스 아래쪽 캡션 영역을 피함
COVER_SEC, TIP_SEC, LAST_SEC = 2.5, 3.5, 4.0


def ffmpeg():
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    import imageio_ffmpeg  # pip 패키지에 든 ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def durations(n):
    """카드 n장의 화면 시간(초)."""
    if n == 1:
        return [LAST_SEC]
    return [COVER_SEC] + [TIP_SEC] * (n - 2) + [LAST_SEC]


def make_reel(card_paths, out_path):
    """카드 사진 경로 목록 → 릴스 MP4. 만든 파일 경로를 돌려준다."""
    cards = [str(p) for p in card_paths]
    if not cards:
        raise RuntimeError("영상으로 만들 카드가 없어요")
    secs = durations(len(cards))
    # 넘어가는 동안 겹치는 시간만큼 앞뒤 장면을 조금 더 길게 둔다
    lens = [s + (FADE if i < len(cards) - 1 else 0) for i, s in enumerate(secs)]
    total = sum(secs)

    cmd = [ffmpeg(), "-y", "-loglevel", "error"]
    for path, length in zip(cards, lens):
        cmd += ["-loop", "1", "-framerate", str(FPS), "-t", f"{length:.2f}", "-i", path]
    cmd += ["-f", "lavfi", "-t", f"{total:.2f}", "-i", "anullsrc=r=48000:cl=stereo"]

    parts = []
    for i in range(len(cards)):
        parts.append(
            f"[{i}:v]scale={W}:-2,setsar=1,split[c{i}][b{i}];"
            f"[b{i}]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
            f"boxblur=40:2,eq=brightness=-0.06[g{i}];"
            f"[g{i}][c{i}]overlay=(W-w)/2:{TOP},fps={FPS},format=yuv420p,setpts=PTS-STARTPTS[v{i}]"
        )
    last = "v0"
    elapsed = 0.0
    for i in range(1, len(cards)):
        elapsed += secs[i - 1]
        out = f"x{i}"
        parts.append(f"[{last}][v{i}]xfade=transition=fade:duration={FADE}:offset={elapsed:.2f}[{out}]")
        last = out

    audio = len(cards)
    cmd += ["-filter_complex", ";".join(parts), "-map", f"[{last}]", "-map", f"{audio}:a",
            "-c:v", "libx264", "-profile:v", "high", "-preset", "medium", "-crf", "21",
            "-pix_fmt", "yuv420p", "-r", str(FPS),
            "-c:a", "aac", "-b:a", "128k", "-ar", "48000",
            "-t", f"{total:.2f}", "-movflags", "+faststart", str(out_path)]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"릴스 영상 만들기 실패: {result.stderr.strip()[-300:]}")
    return Path(out_path)


if __name__ == "__main__":
    folder = Path(sys.argv[1])
    paths = sorted(folder.glob("card*.jpg"), key=lambda p: int(p.stem[4:]))
    out = make_reel(paths, folder / "reel.mp4")
    print(f"{out} ({out.stat().st_size / 1e6:.1f}MB, 카드 {len(paths)}장, {sum(durations(len(paths))):.1f}초)")
