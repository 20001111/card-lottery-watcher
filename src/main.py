"""Collect, verify, publish, and notify about card-lottery information."""

import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import requests
import yaml
from bs4 import BeautifulSoup

from .ai_extract import extract_with_ai, page_document
from .calendar import build_calendar
from .discord_notify import send_management_dashboard_update, send_review_queue_update, send_site_update
from .eligibility import evaluate
from .models import Lottery, canonical_application_url, deduplicate_lotteries, lottery_identity, notification_identity
from .moderation import suppressed_urls
from .supabase_sync import sync_statuses
from .x_discovery import candidate_sources


ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "data" / "lotteries.json"
HEADERS = {"User-Agent": "CardLotteryWatcher/1.0 (+personal notification bot)"}


def load_config() -> dict:
    path = Path(os.getenv("CONFIG_PATH", ROOT / "config.yaml"))
    if not path.exists():
        path = ROOT / "config.example.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def load_state() -> dict[str, dict]:
    if not STATE.exists():
        return {}
    return {item["id"]: item for item in json.loads(STATE.read_text(encoding="utf-8"))}


def notification_index(items: dict[str, dict]) -> dict[str, dict]:
    """Keep notification history by application page, not mutable AI titles."""
    indexed: dict[str, dict] = {}
    for item in items.values():
        url = item.get("application_url")
        if not url:
            continue
        key = notification_identity(item.get("store", ""), item.get("title", ""), url)
        current = indexed.get(key)
        if not current or (item.get("discord_message_id") and not current.get("discord_message_id")):
            indexed[key] = item
    return indexed


def official_detail_urls(html: str, page_url: str, source: dict, limit: int) -> list[str]:
    """Pick a few relevant detail pages from an official announcement list."""
    terms = {
        "pokemon": ("\u30dd\u30b1\u30e2\u30f3", "\u30dd\u30b1\u30ab"),
        "onepiece": ("one piece", "\u30ef\u30f3\u30d4\u30fc\u30b9"),
        "both": ("\u30dd\u30b1\u30e2\u30f3", "\u30dd\u30b1\u30ab", "one piece", "\u30ef\u30f3\u30d4\u30fc\u30b9"),
    }.get(source.get("category"), ())
    labels = ("\u62bd\u9078", "\u5fdc\u52df", "\u8ca9\u58f2")
    soup = BeautifulSoup(html, "html.parser")
    urls: list[str] = []
    for link in soup.find_all("a", href=True):
        label = " ".join(link.get_text(" ", strip=True).split())
        url = urljoin(page_url, link["href"])
        haystack = f"{label} {url}".lower()
        if url.startswith("http") and url not in urls and any(term.lower() in haystack for term in terms) and any(term in label for term in labels):
            urls.append(url)
            if len(urls) == limit:
                break
    return urls


def source_pages(source: dict, config: dict) -> list[tuple[dict, str]]:
    """Fetch a source, following a small number of official detail links."""
    timeout = config.get("request_timeout_seconds", 20)
    response = requests.get(source["url"], headers=HEADERS, timeout=timeout)
    response.raise_for_status()
    if source.get("kind") != "official":
        return [(source, response.text)]

    detail_urls = official_detail_urls(response.text, source["url"], source, int(config.get("official_detail_link_limit", 2)))
    if not detail_urls:
        return [(source, response.text)]
    pages = []
    for detail_url in detail_urls:
        detail = requests.get(detail_url, headers=HEADERS, timeout=timeout)
        detail.raise_for_status()
        pages.append(({**source, "url": detail_url, "name": f"{source['name']} detail"}, detail.text))
    return pages


def lottery_from_raw(raw: dict, source: dict) -> Lottery:
    """Convert every AI candidate with an application link into one record.

    A missing date is not a reason to lose a useful lead.  It remains a
    ``pending`` record in the staff dashboard until an officer fills in the
    missing facts and approves it.
    """
    url = raw["application_url"]
    return Lottery(
        id=lottery_identity(raw["store"], raw["title"], url, raw.get("deadline")),
        title=raw["title"],
        category=raw["card_type"],
        store=raw["store"],
        store_key=source.get("store_key", "unknown"),
        source_url=source["url"],
        application_url=url,
        deadline=raw.get("deadline"),
        start_at=raw.get("start_at"),
        conditions=list(raw.get("requirements") or []),
        application_method=raw.get("application_method", "unknown"),
        receipt_method=raw.get("receipt_method", "unknown"),
        source_kind=source.get("kind", "discovery"),
        official_confirmed=source.get("kind") == "official" or bool(raw.get("official_confirmed")),
    )


def collect(config: dict, now: datetime) -> tuple[dict[str, Lottery], int, int, int]:
    sources = list(config["sources"])
    try:
        sources.extend(candidate_sources(config.get("x_discovery", {})))
    except Exception as exc:
        print(f"WARN X discovery: {exc}")

    collected: dict[str, Lottery] = {}
    queued = extracted_count = 0
    for source in sources:
        try:
            for page_source, html in source_pages(source, config):
                document, allowed_links = page_document(html, page_source["url"], max_chars=int(config.get("ai_page_max_chars", 18000)))
                extracted = extract_with_ai(page_source, document, allowed_links, now, config)
                extracted_count += len(extracted)
                print(f"EXTRACTED {page_source['name']}: {len(extracted)} candidate(s)")
                for raw in extracted:
                    # The AI extractor only returns an actual page link.  Keep
                    # incomplete candidates too: staff can correct the dates
                    # in the dashboard, publish them, or reject them.
                    item = lottery_from_raw(raw, page_source)
                    if not raw.get("start_at") or not raw.get("deadline"):
                        item.status = "pending"
                        queued += 1
                    collected[item.id] = item
        except Exception as exc:
            print(f"WARN {source['name']}: {exc}")
    return collected, len(sources), extracted_count, queued


def retain_open_previous(collected: dict[str, Lottery], old: dict[str, dict], now: datetime) -> None:
    """Keep previous listings when a temporary source outage occurs."""
    fresh_urls = {canonical_application_url(item.application_url) for item in collected.values()}
    for item_id, previous in old.items():
        if canonical_application_url(previous.get("application_url", "")) in fresh_urls:
            continue
        try:
            deadline = datetime.fromisoformat(previous.get("deadline", "").replace("Z", "+00:00"))
            deadline = deadline.replace(tzinfo=now.tzinfo) if deadline.tzinfo is None else deadline
            if deadline > now:
                collected[item_id] = Lottery(**previous)
        except (TypeError, ValueError):
            continue


def prepare_items(collected: dict[str, Lottery], old_by_url: dict[str, dict], config: dict) -> list[Lottery]:
    """Apply URL deduplication, moderator decisions, and eligibility checks."""
    blocked = suppressed_urls()
    items = [item for item in deduplicate_lotteries(collected.values()) if canonical_application_url(item.application_url) not in blocked]
    for item in items:
        previous = old_by_url.get(notification_identity(item.store, item.title, item.application_url))
        if previous:
            item.discord_message_id = previous.get("discord_message_id")
        evaluate(item, config.get("eligibility", {}))
    return sorted(items, key=lambda item: (item.eligibility not in ("eligible", "check"), item.deadline or "9999"))


def mark_new_and_started(items: list[Lottery], old_by_url: dict[str, dict], now: datetime) -> tuple[list[Lottery], list[Lottery], list[dict]]:
    new_items: list[Lottery] = []
    started_items: list[Lottery] = []
    calendar_items: list[dict] = []
    for item in items:
        previous = old_by_url.get(notification_identity(item.store, item.title, item.application_url))
        item.first_seen_at = (previous or {}).get("first_seen_at") or (now - timedelta(days=2)).isoformat() if previous else now.isoformat()
        is_new = datetime.fromisoformat(item.first_seen_at) >= now - timedelta(days=1)
        start = datetime.fromisoformat(item.start_at.replace("Z", "+00:00")) if item.start_at else None
        if start and start.tzinfo is None:
            start = start.replace(tzinfo=now.tzinfo)
        if previous and "start_notified_at" in previous:
            item.start_notified_at = previous.get("start_notified_at")
            if not item.start_notified_at and start and start <= now:
                started_items.append(item)
                item.start_notified_at = now.isoformat()
        elif start and start <= now:
            item.start_notified_at = now.isoformat()
        if is_new and item.eligibility != "ineligible" and item.start_at and item.deadline:
            new_items.append(item)
        calendar_item = item.to_dict()
        calendar_item["is_new"] = is_new
        calendar_items.append(calendar_item)
    return new_items, started_items, calendar_items


def publish(items: list[Lottery], calendar_items: list[dict], config: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps([item.to_dict() for item in items], ensure_ascii=False, indent=2), encoding="utf-8")
    build_calendar(calendar_items, ROOT / "docs", config.get("timezone", "Asia/Tokyo"))


def notify(new_items: list[Lottery], started_items: list[Lottery], queued: int, publish_public: bool) -> None:
    webhook = os.getenv("DISCORD_WEBHOOK_URL")
    daily = os.getenv("DAILY_SITE_UPDATE", "").lower() == "true"
    # A manual development run is an explicit test request, so it must always
    # acknowledge completion even when the scan finds zero new listings.
    # Production reports its refreshed Website in the same way.
    if webhook:
        send_site_update(
            webhook,
            len(new_items),
            os.getenv("CALENDAR_URL"),
            daily=daily,
            development=not publish_public,
            started_count=len(started_items),
        )
    if admin_webhook := os.getenv("ADMIN_DISCORD_WEBHOOK_URL"):
        dashboard_url = os.getenv("ADMIN_DASHBOARD_URL")
        # The private management channel receives its dashboard link on every run,
        # including manual development checks. This makes webhook setup testable.
        send_management_dashboard_update(admin_webhook, dashboard_url, queued)
        if queued and not daily:
            send_review_queue_update(admin_webhook, queued, dashboard_url)


def main() -> None:
    config = load_config()
    now = datetime.now(ZoneInfo(config.get("timezone", "Asia/Tokyo")))
    old = load_state()
    old_by_url = notification_index(old)
    collected, source_count, extracted_count, queued = collect(config, now)
    retain_open_previous(collected, old, now)
    items = prepare_items(collected, old_by_url, config)
    new_items, started_items, calendar_items = mark_new_and_started(items, old_by_url, now)
    publish_public = os.getenv("PUBLISH_PUBLIC", "true").lower() == "true"
    # A staff member decides which listings are public.  The saved crawler
    # state still keeps all candidates, so they remain available in the admin
    # dashboard instead of disappearing after one collection run. Development
    # runs deliberately do not change the real approval queue.
    try:
        statuses = sync_statuses(items) if publish_public else None
    except Exception as exc:
        # Do not replace the Website with an empty page if Supabase is down.
        # The next run will retry and the previous published Website remains.
        print(f"WARN Supabase sync: {exc}")
        statuses = None
    if statuses is None:
        public_calendar_items = calendar_items
    else:
        public_calendar_items = [
            item for item in calendar_items
            if statuses.get(canonical_application_url(item.get("application_url", ""))) == "published"
        ]
    if publish_public:
        publish(items, public_calendar_items, config)
    notify(new_items, started_items, queued, publish_public)
    print(f"SUMMARY sources={source_count} extracted={extracted_count} public={len(items)} new={len(new_items)} started={len(started_items)} review_needed={queued}")


if __name__ == "__main__":
    main()
