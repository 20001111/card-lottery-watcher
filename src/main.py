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
from .admin_queue import send_candidate
from .calendar import build_calendar
from .discord_notify import send_review_queue_update, send_site_update
from .eligibility import evaluate
from .models import Lottery, canonical_application_url, deduplicate_lotteries, lottery_identity, notification_identity
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
    # Keep these as Unicode escapes: this file is edited on Windows systems
    # with different console encodings, but the matching terms must stay exact.
    category_terms = {
        "pokemon": ("\u30dd\u30b1\u30e2\u30f3", "\u30dd\u30b1\u30ab"),
        "onepiece": ("one piece", "\u30ef\u30f3\u30d4\u30fc\u30b9"),
        "both": ("\u30dd\u30b1\u30e2\u30f3", "\u30dd\u30b1\u30ab", "one piece", "\u30ef\u30f3\u30d4\u30fc\u30b9"),
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
            and any(term in label for term in ("\u62bd\u9078", "\u5fdc\u52df", "\u8ca9\u58f2"))
            and url not in seen
        ):
            seen.add(url)
            urls.append(url)
            if len(urls) >= limit:
                break
            continue
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
    old_by_notification = {}
    for previous in old.values():
        if not previous.get("application_url"):
            continue
        key = notification_identity(previous.get("store", ""), previous.get("title", ""), previous["application_url"])
        existing = old_by_notification.get(key)
        if not existing or (previous.get("discord_message_id") and not existing.get("discord_message_id")):
            old_by_notification[key] = previous
    collected = {}
    queued_for_review = 0
    source_count = 0
    extracted_count = 0

    headers = {"User-Agent": "CardLotteryWatcher/1.0 (+personal notification bot)"}
    detail_limit = int(config.get("official_detail_link_limit", 2))
    sources = list(config["sources"])
    try:
        sources.extend(candidate_sources(config.get("x_discovery", {})))
    except Exception as exc:
        print(f"WARN X discovery: {exc}")

    for source in sources:
        source_count += 1
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
                document, allowed_links = page_document(
                    html,
                    page_source["url"],
                    max_chars=int(config.get("ai_page_max_chars", 18000)),
                )
                extracted = extract_with_ai(page_source, document, allowed_links, now, config)
                extracted_count += len(extracted)
                print(f"EXTRACTED {page_source['name']}: {len(extracted)} candidate(s)")
                for raw in extracted:
                    if not raw.get("start_at") or not raw.get("deadline"):
                        if send_candidate(raw, page_source):
                            queued_for_review += 1
                            print(f"QUEUED for review: {raw.get('title', '')}")
                        else:
                            print("WARN incomplete candidate skipped: ADMIN_QUEUE_URL or ADMIN_QUEUE_KEY is not configured")
                        continue
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
                        application_method=raw.get("application_method", "unknown"),
                        receipt_method=raw.get("receipt_method", "unknown"),
                        source_kind=page_source.get("kind", "discovery"),
                        official_confirmed=page_source.get("kind") == "official" or bool(raw.get("official_confirmed")),
                    )
                    collected[item.id] = item
        except Exception as exc:
            print(f"WARN {source['name']}: {exc}")

    # A temporary source or AI outage must not erase still-open lotteries from
    # the calendar. Freshly verified entries replace their previous version.
    fresh_urls = {canonical_application_url(item.application_url) for item in collected.values()}
    for item_id, previous in old.items():
        if canonical_application_url(previous.get("application_url", "")) in fresh_urls:
            continue
        try:
            previous_deadline = datetime.fromisoformat(previous.get("deadline", "").replace("Z", "+00:00"))
            if previous_deadline.tzinfo is None:
                previous_deadline = previous_deadline.replace(tzinfo=now.tzinfo)
            if previous_deadline > now:
                collected[item_id] = Lottery(**previous)
        except (TypeError, ValueError):
            continue

    # Different sources often describe the same form with slightly different
    # titles.  Merge by application page before evaluating and publishing.
    items = deduplicate_lotteries(collected.values())
    for item in items:
        previous = old_by_notification.get(notification_identity(item.store, item.title, item.application_url))
        if previous:
            item.discord_message_id = previous.get("discord_message_id")
        evaluate(item, config.get("eligibility", {}))
    items.sort(key=lambda x: (x.eligibility not in ("eligible", "check"), x.deadline or "9999"))

    notified = set(old_by_notification)
    new_items = []
    started_items = []
    calendar_items = []
    for item in items:
        key = notification_identity(item.store, item.title, item.application_url)
        previous = old_by_notification.get(key)
        if previous:
            # Entries collected before this update have no first_seen_at. They
            # are existing information, not a fresh announcement.
            item.first_seen_at = previous.get("first_seen_at") or (now - timedelta(days=2)).isoformat()
        else:
            item.first_seen_at = now.isoformat()
        first_seen = datetime.fromisoformat(item.first_seen_at)
        is_new = first_seen >= now - timedelta(days=1)
        start_time = datetime.fromisoformat(item.start_at.replace("Z", "+00:00")) if item.start_at else None
        if start_time and start_time.tzinfo is None:
            start_time = start_time.replace(tzinfo=now.tzinfo)
        if previous and "start_notified_at" in previous:
            item.start_notified_at = previous.get("start_notified_at")
            if not item.start_notified_at and start_time and start_time <= now:
                started_items.append(item)
                item.start_notified_at = now.isoformat()
        elif start_time and start_time <= now:
            # Existing entries from before this feature are marked as already
            # started once, so enabling it never sends a backlog of alerts.
            item.start_notified_at = now.isoformat()
        if is_new and item.eligibility != "ineligible" and item.start_at and item.deadline:
            new_items.append(item)
        item_for_calendar = item.to_dict()
        item_for_calendar["is_new"] = is_new
        calendar_items.append(item_for_calendar)

    publish_public = os.getenv("PUBLISH_PUBLIC", "true").lower() == "true"
    if publish_public:
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps([x.to_dict() for x in items], ensure_ascii=False, indent=2), encoding="utf-8")
        build_calendar(calendar_items, ROOT / "docs", config.get("timezone", "Asia/Tokyo"))

    webhook = os.getenv("DISCORD_WEBHOOK_URL")
    admin_webhook = os.getenv("ADMIN_DISCORD_WEBHOOK_URL")
    admin_dashboard_url = os.getenv("ADMIN_DASHBOARD_URL")
    calendar_url = os.getenv("CALENDAR_URL")
    daily_site_update = os.getenv("DAILY_SITE_UPDATE", "").lower() == "true"
    if webhook and (new_items or daily_site_update):
        try:
            send_site_update(
                webhook,
                len(new_items),
                calendar_url,
                daily=daily_site_update,
                development=not publish_public,
                started_count=len(started_items),
            )
        except Exception as exc:
            print(f"WARN Discord site update: {exc}")
        print(
            f"Collected {len(items)} items. Sent one site-update notification for "
            f"{len(new_items)} new lotteries and {len(started_items)} started lotteries."
        )
    elif webhook:
        print(f"Collected {len(items)} items. No new lotteries; Discord notification skipped.")
    else:
        print(f"Collected {len(items)} items. DISCORD_WEBHOOK_URL is not configured; notification skipped.")
    if admin_webhook and queued_for_review:
        try:
            send_review_queue_update(admin_webhook, queued_for_review, admin_dashboard_url)
        except Exception as exc:
            print(f"WARN Discord review-queue update: {exc}")
    print(
        f"SUMMARY sources={source_count} extracted={extracted_count} "
        f"public={len(items)} new={len(new_items)} started={len(started_items)} review_needed={queued_for_review}"
    )
    return

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
