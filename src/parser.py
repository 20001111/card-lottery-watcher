import hashlib
import re
from datetime import datetime
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from dateutil import parser as date_parser

from .models import Lottery

KEYWORDS = ("抽選", "予約", "応募", "受付")
CARD_WORDS = ("ポケモンカード", "ポケカ", "ONE PIECE", "ワンピースカード", "ワンピカード")
CONDITION_PATTERNS = {
    "購入履歴": r"購入履歴|購入実績|購入歴",
    "会員登録": r"会員登録|会員限定|会員証",
    "アプリ": r"アプリ(?:会員|登録|必須)?",
    "本人確認": r"本人確認|身分証|マイナンバー",
    "店舗受取": r"店頭受取|店舗受取|受取店舗",
    "フォロー": r"フォロー(?:が必要|必須|条件)?",
    "クレジットカード": r"クレジットカード|クレカ",
}
DATE_RE = re.compile(r"(?:(20\d{2})[年./-])?(\d{1,2})[月./-](\d{1,2})日?(?:\([^)]+\))?\s*(\d{1,2})?(?:[:時](\d{2})?)?")


def _iso_date(match, now):
    year = int(match.group(1) or now.year)
    month, day = int(match.group(2)), int(match.group(3))
    hour = int(match.group(4) or 23)
    minute = int(match.group(5) or 59)
    try:
        return datetime(year, month, day, hour, minute, tzinfo=now.tzinfo).isoformat()
    except ValueError:
        return None


def parse_source(html: str, source: dict, now: datetime) -> list[Lottery]:
    soup = BeautifulSoup(html, "html.parser")
    results = []
    seen = set()
    for node in soup.select("article, li, section, div"):
        text = " ".join(node.get_text(" ", strip=True).split())
        if len(text) < 15 or len(text) > 1500:
            continue
        if not any(k in text for k in KEYWORDS) or not any(k.lower() in text.lower() for k in CARD_WORDS):
            continue
        link = node.find("a", href=True)
        url = urljoin(source["url"], link["href"]) if link else source["url"]
        title = (link.get_text(" ", strip=True) if link else text[:100]).strip()
        identity = hashlib.sha256(f"{source['name']}|{title}|{url}".encode()).hexdigest()[:20]
        if identity in seen:
            continue
        seen.add(identity)
        dates = [_iso_date(m, now) for m in DATE_RE.finditer(text)]
        dates = [d for d in dates if d]
        conditions = [label for label, pattern in CONDITION_PATTERNS.items() if re.search(pattern, text)]
        official = source.get("kind") == "official"
        results.append(Lottery(
            id=identity,
            title=title[:160],
            category=source.get("category", "unknown"),
            store=source["name"],
            store_key=source.get("store_key", "unknown"),
            source_url=source["url"],
            application_url=url,
            deadline=dates[-1] if dates else None,
            start_at=dates[0] if len(dates) > 1 else None,
            conditions=conditions,
            source_kind=source.get("kind", "discovery"),
            official_confirmed=official,
        ))
    return results

