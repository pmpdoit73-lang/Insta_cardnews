"""가전·주방 살림 주제 후보를 여러 출처에서 모은다.

- 구글 뉴스 검색: 가전·주방 키워드로 최근 기사 (키 불필요)
- 네이버 뉴스 검색 (NAVER_CLIENT_ID / NAVER_CLIENT_SECRET 있을 때만)

한 출처가 실패해도 나머지로 계속 진행한다. 모두 실패해도 꿀팁은 언제든 쓸 수 있으므로
빈 목록으로 진행한다 (writer가 계절에 맞는 꿀팁을 고른다).
"""

import html
import os
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

from urllib.parse import quote

import requests

HEADERS = {"User-Agent": "Mozilla/5.0 (insta-cardnews)"}
TIMEOUT = 15


MAX_AGE_HOURS = 36  # 이보다 오래된 뉴스는 빼서 '지나간 이슈'를 막음
HT = "{https://trends.google.com/trending/rss}"


def _age_label(pub, max_hours=MAX_AGE_HOURS):
    """발행 시각 → '3시간 전' 같은 표시. 너무 오래됐으면 None."""
    if not pub:
        return ""
    try:
        when = parsedate_to_datetime(pub)
    except (TypeError, ValueError):
        return ""
    hours = (datetime.now(timezone.utc) - when).total_seconds() / 3600
    if hours > max_hours:
        return None
    if hours >= 48:
        return f"{int(hours // 24)}일 전"
    return f"{max(int(hours), 0)}시간 전"


def _rss_titles(url, limit, max_hours=MAX_AGE_HOURS):
    resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    resp.raise_for_status()
    root = ET.fromstring(resp.content)
    titles = []
    for item in root.iter("item"):
        title = item.findtext("title")
        age = _age_label(item.findtext("pubDate"), max_hours)
        if not title or age is None:
            continue
        line = html.unescape(title.strip())
        news = item.findtext(f"{HT}news_item/{HT}news_item_title")  # 구글 트렌드: 관련 기사 제목
        if news:
            line += f" ← {html.unescape(news.strip())}"
        traffic = item.findtext(f"{HT}approx_traffic")
        if traffic:
            line += f" [검색 {traffic}]"
        titles.append(f"{line} ({age})" if age else line)
        if len(titles) >= limit:
            break
    return titles


# 가전·주방 기사는 뉴스보다 천천히 나오므로 일주일 안 기사까지 본다
TOPIC_MAX_HOURS = 24 * 7
TOPIC_QUERIES = ["주방 꿀팁", "가전 꿀팁", "살림 꿀팁", "에어프라이어", "식기세척기", "김치냉장고",
                 "전기요금 절약 가전", "가전 리콜", "주방가전 신제품", "냉장고 보관법"]


def google_news(limit=5):
    titles, seen = [], set()
    for query in TOPIC_QUERIES:
        url = f"https://news.google.com/rss/search?q={quote(query)}&hl=ko&gl=KR&ceid=KR:ko"
        try:
            found = _rss_titles(url, limit, TOPIC_MAX_HOURS)
        except Exception as e:
            print(f"[trends] 구글 뉴스 '{query}' 실패: {e}")
            continue
        for t in found:
            # "제목 - 언론사 (3시간 전)" 형태에서 언론사 이름을 뗀다
            t = re.sub(r"\s+-\s+[^-()]+(?= \(\d+(시간|일) 전\)$|$)", "", t)
            if t not in seen:
                seen.add(t)
                titles.append(t)
    return titles


NAVER_QUERIES = TOPIC_QUERIES


def naver_news(limit=8):
    client_id = os.environ.get("NAVER_CLIENT_ID", "").strip()
    client_secret = os.environ.get("NAVER_CLIENT_SECRET", "").strip()
    if not (client_id and client_secret):
        return []
    result, seen = [], set()
    for query in NAVER_QUERIES:
        try:
            resp = requests.get(
                "https://openapi.naver.com/v1/search/news.json",
                params={"query": query, "display": limit, "sort": "date"},
                headers={"X-Naver-Client-Id": client_id, "X-Naver-Client-Secret": client_secret},
                timeout=TIMEOUT,
            )
            resp.raise_for_status()
        except Exception as e:
            print(f"[trends] 네이버 '{query}' 실패: {e}")
            continue
        for i in resp.json().get("items", []):
            age = _age_label(i.get("pubDate"), TOPIC_MAX_HOURS)
            title = re.sub(r'<[^>]+>', '', html.unescape(i['title']))
            if age is None or title in seen:
                continue
            seen.add(title)
            result.append(f"{title} ({age})")
    return result


SOURCES = {
    "가전·주방 뉴스 (구글)": google_news,
    "가전·주방 뉴스 (네이버)": naver_news,
}


def collect():
    """{출처 이름: [제목, ...]} 를 돌려준다. 실패한 출처는 빠진다."""
    result = {}
    for name, fn in SOURCES.items():
        try:
            items = fn()
        except Exception as e:  # 한 출처 실패가 전체를 멈추지 않게
            print(f"[trends] {name} 실패: {e}")
            continue
        if items:
            result[name] = items
    if not result:
        print("[trends] 기사를 하나도 못 가져옴 → 계절 꿀팁으로 진행")
    return result
