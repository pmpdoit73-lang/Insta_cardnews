"""릴스 배경음악 (2026-11-06 gil 요청: 무료 사이트에서 받아 쓰기).

음악은 인터넷 아카이브(archive.org)에서 퍼블릭 도메인(CC0) 표시가 된 곡만 받는다.
CC0 곡은 상업 이용·수정이 자유롭고 출처 표기도 필요 없다 (인스타 음악 저작권 걱정 없음).
(처음엔 FreePD를 쓰려 했는데 2026-11 기준 사이트가 문을 닫음)

- music/*.m4a: 릴스에 맞게 20초로 잘라 소리 크기를 맞춘 곡들 (저장소에 넣어 둠)
- music/LIST.md: 곡 이름과 원본 주소

받기(곡을 바꿀 때만): GitHub Actions의 '배경음악 받기' 실행 (= python src/music.py fetch)
고르기: pick(초안 id) → 초안마다 정해진 곡 (텔레그램 미리보기와 실제 게시 영상이 같은 곡)
"""

import random
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote, unquote

import requests

MUSIC_DIR = Path(__file__).resolve().parent.parent / "music"
WANT = 12          # 받을 곡 수
CLIP_SEC = 20      # 잘라 둘 길이 (릴스는 12~15초)
HEADERS = {"User-Agent": "Mozilla/5.0 (insta-cardnews music fetch)"}


def tracks():
    return sorted(MUSIC_DIR.glob("*.m4a"))


def pick(key):
    """초안 id로 곡을 하나 고른다. 곡이 없으면 None (그러면 무음)."""
    found = tracks()
    if not found:
        return None
    return random.Random(key).choice(found)


def title(path):
    return path.stem.replace("_", " ") if path else ""


SEARCHES = ["freepd AND mediatype:audio"]  # 인터넷 아카이브(archive.org)에 남은 FreePD 곡 묶음
# 살림 꿀팁 분위기(밝고 가벼움)에 맞는 곡 이름 낱말. 이런 곡을 먼저 고른다
BRIGHT = re.compile(r"happy|ukulele|cheer|bright|sunny|sunday|picnic|morning|kawaii|cute|fun|bounc|whistl|joy|"
                    r"light|breez|summer|walk|coffee|cafe|swing|smile|sweet|play|carefree|positive|upbeat|kitchen",
                    re.I)
BLOCK = re.compile(r"bbc|disney|official|remix|cover|trailer|horror|scary|sad|dark|epic|battle|funeral", re.I)


def _links():
    """FreePD 곡 묶음(CC0)에서 mp3 주소를 모은다. 밝은 분위기 이름을 앞에. [(url, 곡 이름, 묶음, 라이선스)]"""
    found, seen = [], set()
    for q in SEARCHES:
        try:
            docs = requests.get("https://archive.org/advancedsearch.php", headers=HEADERS, timeout=30,
                                params={"q": q, "fl[]": ["identifier", "title"], "rows": 40,
                                        "output": "json"}).json()["response"]["docs"]
        except (requests.RequestException, ValueError, KeyError) as e:
            print(f"[music] 검색 실패 {q}: {e}")
            continue
        for doc in docs:
            ident = doc["identifier"]
            if ident in seen:
                continue
            seen.add(ident)
            try:
                meta = requests.get(f"https://archive.org/metadata/{ident}", headers=HEADERS, timeout=30).json()
            except (requests.RequestException, ValueError) as e:
                print(f"[music] {ident} 정보 실패: {e}")
                continue
            md = meta.get("metadata", {})
            text = f"{ident} {md.get('title', '')} {md.get('description', '')}".lower()
            lic = str(md.get("licenseurl", ""))
            if "freepd" not in text and "publicdomain" not in lic:
                continue
            n = 0
            for f in meta.get("files", []):
                name = f.get("name", "")
                size = int(f.get("size", 0) or 0)
                stem = name.rsplit("/", 1)[-1].rsplit(".", 1)[0]
                if name.lower().endswith(".mp3") and 300_000 < size < 15_000_000 and not BLOCK.search(stem):
                    found.append((f"https://archive.org/download/{ident}/{quote(name)}", stem,
                                  str(md.get("title", ident)), lic or "FreePD (CC0)"))
                    n += 1
            print(f"[music] {ident}: {n}곡 ({lic or 'FreePD'})")
    bright = [x for x in found if BRIGHT.search(x[1])]
    print(f"[music] 후보 {len(found)}곡, 밝은 이름 {len(bright)}곡")
    return found, bright


def _name(url):
    stem = unquote(url)
    return re.sub(r"[^0-9A-Za-z]+", "_", stem).strip("_")


def fetch():
    import video  # ffmpeg 위치
    MUSIC_DIR.mkdir(exist_ok=True)
    found, bright = _links()
    rng = random.Random(20261106)
    rng.shuffle(bright)
    rest = [x for x in found if x not in bright]
    rng.shuffle(rest)
    for old in tracks():  # 새 곡 묶음으로 바꿈
        old.unlink()
    done = []
    for url, stem, item, lic in bright + rest:
        if len(done) >= WANT:
            break
        name = _name(stem)
        out = MUSIC_DIR / f"{name}.m4a"
        if out.exists():
            continue
        try:
            resp = requests.get(url, headers=HEADERS, timeout=90)
        except requests.RequestException as e:
            print(f"[music] 받기 실패 {stem}: {e}")
            continue
        if not resp.ok or len(resp.content) < 200_000:
            print(f"[music] 못 받음 {stem}: 응답 {resp.status_code}, {len(resp.content)}바이트")
            continue
        src = MUSIC_DIR / "_tmp.mp3"
        src.write_bytes(resp.content)
        # 앞 3초(조용한 도입부)를 건너뛰고 20초, 소리 크기를 일정하게, 끝은 부드럽게 줄임.
        # -vn: mp3 안에 든 앨범 그림은 버림 (그림이 있으면 m4a 만들기가 실패함)
        cmd = [video.ffmpeg(), "-y", "-loglevel", "error", "-i", str(src), "-ss", "3", "-t", str(CLIP_SEC), "-vn",
               "-af", f"loudnorm=I=-16:TP=-1.5:LRA=11,afade=t=out:st={CLIP_SEC - 2}:d=2",
               "-ar", "48000", "-ac", "2", "-c:a", "aac", "-b:a", "128k", str(out)]
        r = subprocess.run(cmd, capture_output=True, text=True)
        src.unlink(missing_ok=True)
        if r.returncode != 0 or not out.exists() or out.stat().st_size < 100_000:
            out.unlink(missing_ok=True)
            print(f"[music] 자르기 실패 {stem}: {r.stderr[-200:]}")
            continue
        done.append((name, url, item, lic))
        print(f"[music] 받음: {stem} ({out.stat().st_size // 1000}KB)")
    lines = ["# 릴스 배경음악", "",
             "출처: FreePD.com 곡 (모두 퍼블릭 도메인 CC0, 상업 이용 가능, 출처 표기 불필요).",
             "FreePD 사이트는 문을 닫아서 인터넷 아카이브(archive.org)에 보관된 사본에서 받았어요.",
             "각 곡은 앞 3초를 빼고 20초로 잘라 소리 크기를 맞췄어요. 마음에 안 드는 곡은 파일을 지우면 돼요.", ""]
    lines += [f"- {n}.m4a ← {u}" for n, u, item, lic in done]
    (MUSIC_DIR / "LIST.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"[music] 총 {len(done)}곡")
    if not done:
        sys.exit(1)


if __name__ == "__main__":
    if sys.argv[1:2] == ["fetch"]:
        fetch()
    else:
        print("\n".join(str(p) for p in tracks()) or "음악 없음")
