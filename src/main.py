import json
import os
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import requests
import yaml
from bs4 import BeautifulSoup

from .ai_extract import extract_with_ai, page_document
from .calendar import build_calendar
from .discord_notify import send_heading, send_or_update
from .eligibility import evaluate
from .models import Lottery, lottery_identity
from .x_discovery import candidate_sources

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "data" / "lotteries.json"


def official_detail_urls(html: str, page_url: str, source: dict, limit: int) -> list[str]:
    """Pick a small number of card-lottery detail pages from an official listing."""
    category_terms = {
        "pokemon": ("ポケモン", "ポケカ"),
        "onepiece": ("one piece", "ワンピース", "ワンピ"),
        "both": ("ポケモン", "ポケカ", "one piece", "ワンピース", "ワンピ"),
    }.get(source.get("category"), ())
    soup = BeautifulSoup(html, "html.parser")
    urls = []
    seen = set()
    for link in soup.find_all("a", href=True):
        label = " ".join(link.get_text(" ", strip=True).split())
        url = urljoin(page_url, link["href"])
        haystack = f"{label} {url}".lower()
        if (
            url.startswith("http")
            and any(term.lower() in haystack for term in category_terms)
            and any(term in label for term in ("抽選", "応募", "販売"))
            and url not in seen
        ):
            seen.add(url)
            urls.append(url)
            if len(urls) >= limit:
                break
    return urls


def load_state():
    if not STATE.exists():
        return {}
    return {x["id"]: x for x in json.loads(STATE.read_text(encoding="utf-8"))}


def main():
    config_path = Path(os.getenv("CONFIG_PATH", ROOT / "config.yaml"))
    if not config_path.exists():
        config_path = ROOT / "config.example.yaml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    now = datetime.now(ZoneInfo(config.get("timezone", "Asia/Tokyo")))
    old = load_state()
    collected = {}

    headers = {"User-Agent": "CardLotteryWatcher/1.0 (+personal notification bot)"}
    detail_limit = int(config.get("official_detail_link_limit", 2))
    sources = list(config["sources"])
    try:
        sources.extend(candidate_sources(config.get("x_discovery", {})))
    except Exception as exc:
        print(f"WARN X discovery: {exc}")

    for source in sources:
        try:
            response = requests.get(source["url"], headers=headers, timeout=config.get("request_timeout_seconds", 20))
            response.raise_for_status()
            pages = [(source, response.text)]
            if source.get("kind") == "official":
                detail_pages = official_detail_urls(response.text, source["url"], source, detail_limit)
                if detail_pages:
                    pages = []
                    for detail_url in detail_pages:
                        detail_response = requests.get(detail_url, headers=headers, timeout=config.get("request_timeout_seconds", 20))
                        detail_response.raise_for_status()
                        pages.append(({**source, "url": detail_url, "name": f"{source['name']} 詳細"}, detail_response.text))
            for page_source, html in pages:
                document, allowed_links = page_document(html, page_source["url"])
                extracted = extract_with_ai(page_source, document, allowed_links, now, config)
                for raw in extracted:
                    identity = lottery_identity(raw["store"], raw["title"], raw["application_url"], raw.get("deadline"))
                    conditions = list(raw.get("requirements") or [])
                    item = Lottery(
                        id=identity,
                        title=raw["title"],
                        category=raw["card_type"],
                        store=raw["store"],
                        store_key=page_source.get("store_key", "unknown"),
                        source_url=page_source["url"],
                        application_url=raw["application_url"],
                        deadline=raw["deadline"],
                        start_at=raw.get("start_at"),
                        conditions=conditions,
                        source_kind=page_source.get("kind", "discovery"),
                        official_confirmed=page_source.get("kind") == "official" or bool(raw.get("official_confirmed")),
                    )
                    collected[item.id] = evaluate(item, config.get("eligibility", {}))
        except Exception as exc:
            print(f"WARN {source['name']}: {exc}")

    for item in collected.values():
        item.discord_message_id = old.get(item.id, {}).get("discord_message_id")
    items = list(collected.values())
    items.sort(key=lambda x: (x.eligibility not in ("eligible", "check"), x.deadline or "9999"))

    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps([x.to_dict() for x in items], ensure_ascii=False, indent=2), encoding="utf-8")
    build_calendar([x.to_dict() for x in items], ROOT / "docs", config.get("timezone", "Asia/Tokyo"))

    webhook = os.getenv("DISCORD_WEBHOOK_URL")
    if not webhook:
        print(f"Collected {len(items)} items. DISCORD_WEBHOOK_URL is not configured; notification skipped.")
        return
    digest = [x for x in items if x.eligibility != "ineligible"]
    heading = f"📅 本日のカード抽選（締切順） {now:%Y/%m/%d}"
    calendar_url = os.getenv("CALENDAR_URL")
    send_heading(webhook, heading)
    for item in digest[:25]:
        try:
            item.discord_message_id = send_or_update(webhook, item)
        except Exception as exc:
            print(f"WARN Discord {item.title}: {exc}")
    if calendar_url:
        send_heading(webhook, f"📅 締切カレンダー: {calendar_url}")


if __name__ == "__main__":
    main()
