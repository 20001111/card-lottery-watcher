"""Collect, verify, publish, and notify about card-lottery information."""

import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urljoin, urlsplit
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
from .supabase_sync import configured as supabase_configured
from .supabase_sync import (
    known_application_urls,
    manual_review_sources,
    record_source_failure,
    sync_statuses,
)
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


def discovery_detail_urls(html: str, page_url: str, source: dict, limit: int) -> list[str]:
    """Choose current card-information pages from a discovery site's index.

    Discovery sites are useful for finding leads, but their home pages are
    usually too large for one AI check.  Follow only a few same-site category
    or summary pages.  External links remain in the page document and are
    still required before a lead can be saved.
    """
    terms = {
        "pokemon": ("ポケモン", "ポケカ"),
        "onepiece": ("one piece", "ワンピース"),
        "both": ("ポケモン", "ポケカ", "one piece", "ワンピース"),
    }.get(source.get("category"), ())
    source_host = urlsplit(page_url).netloc.lower()
    soup = BeautifulSoup(html, "html.parser")
    urls: list[str] = []
    for link in soup.find_all("a", href=True):
        label = " ".join(link.get_text(" ", strip=True).split())
        url = urljoin(page_url, link["href"])
        haystack = f"{label} {url}".lower()
        if (
            not url.startswith("http")
            or urlsplit(url).netloc.lower() != source_host
            or url.rstrip("/") == page_url.rstrip("/")
            or url in urls
            or not any(term.lower() in haystack for term in terms)
        ):
            continue
        urls.append(url)
        if len(urls) >= limit:
            break
    return urls


def discovery_outbound_links(html: str, page_url: str, source: dict, limit: int) -> list[tuple[str, str]]:
    """Find likely application links without asking AI to interpret the index.

    An aggregation page is a lead source, not proof.  We only retain external
    links whose surrounding text mentions both a supported card game and an
    entry-related word.  The link is then checked separately by AI on a later
    production run before an officer can publish it.
    """
    card_terms = {
        "pokemon": ("ポケモン", "ポケカ"),
        "onepiece": ("one piece", "ワンピース"),
        "both": ("ポケモン", "ポケカ", "one piece", "ワンピース"),
    }.get(source.get("category"), ())
    entry_terms = ("抽選", "応募", "予約", "販売")
    blocked_hosts = (
        "appollo.jp", "amazon.co.jp", "amazon.com", "amzn.to", "facebook.com", "threads.net",
        "timeline.line.me", "lin.ee", "x.com", "twitter.com", "instagram.com", "youtube.com",
        "rakuten.co.jp", "rakuten.ne.jp", "af.moshimo.com", "shopping.yahoo.co.jp", "t.co",
        "wordpress.org", "fit-jp.com", "ebay.us", "aliexpress.com",
    )
    source_host = urlsplit(page_url).netloc.lower()
    soup = BeautifulSoup(html, "html.parser")
    page_scope = " ".join(
        element.get_text(" ", strip=True)
        for element in soup.find_all(["title", "h1", "h2"], limit=8)
    ).lower()
    scoped_card_page = any(term.lower() in page_scope for term in card_terms)
    scoped_entry_page = any(term in page_scope for term in entry_terms)
    results: list[tuple[str, str]] = []
    for link in soup.find_all("a", href=True):
        url = canonical_application_url(urljoin(page_url, link["href"]))
        host = urlsplit(url).netloc.lower()
        if (
            not url.startswith("http")
            or "." not in host
            or host == source_host
            or any(host == blocked or host.endswith(f".{blocked}") for blocked in blocked_hosts)
        ):
            continue
        label = " ".join(link.get_text(" ", strip=True).split())
        container = link.find_parent(["tr", "li", "p", "article", "section", "div"])
        context = " ".join(container.get_text(" ", strip=True).split()) if container else label
        haystack = f"{label} {context} {url}".lower()
        local_card = any(term.lower() in haystack for term in card_terms)
        local_entry = any(term in haystack for term in entry_terms)
        # Individual summary pages often say only "こちら" next to a shop
        # link. Their page title already establishes the card and lottery
        # context, so accept those links after excluding ad/social domains.
        if not ((local_card and local_entry) or (scoped_card_page and scoped_entry_page and (local_card or local_entry))):
            continue
        title = context if len(context) >= 8 else label
        title = title[:180] or "内容確認待ちの応募URL"
        if url not in {existing_url for existing_url, _ in results}:
            results.append((url, title))
        if len(results) >= limit:
            break
    return results


def source_pages(source: dict, config: dict) -> list[tuple[dict, str]]:
    """Fetch a source, following a small number of relevant detail pages."""
    timeout = config.get("request_timeout_seconds", 20)
    response = requests.get(source["url"], headers=HEADERS, timeout=timeout)
    response.raise_for_status()
    if source.get("kind") == "official":
        detail_urls = official_detail_urls(
            response.text, source["url"], source, int(config.get("official_detail_link_limit", 2))
        )
    elif source.get("kind") == "discovery":
        detail_urls = discovery_detail_urls(
            response.text, source["url"], source, int(config.get("discovery_detail_link_limit", 3))
        )
    else:
        detail_urls = []
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


def _source_priority(source: dict) -> tuple[int, str]:
    """Use the limited AI budget on direct pages before aggregation indexes."""
    return ({"manual": 0, "official": 1, "discovery": 2}.get(source.get("kind"), 3), source.get("name", ""))


def collect(config: dict, now: datetime) -> tuple[dict[str, Lottery], int, int, int]:
    sources = list(config["sources"])
    try:
        sources.extend(candidate_sources(config.get("x_discovery", {})))
    except Exception as exc:
        print(f"WARN X discovery: {exc}")
    try:
        manual_sources = manual_review_sources(int(config.get("manual_review_limit", 8)))
        sources.extend(manual_sources)
        if manual_sources:
            print(f"MANUAL REVIEW: {len(manual_sources)} URL(s) queued for AI extraction")
    except Exception as exc:
        print(f"WARN manual review sources: {exc}")

    # Deduplicate known application URLs before any AI request.  This prevents
    # the same link from an X post, a blog, and an official list costing three
    # separate AI checks.
    try:
        known_urls = known_application_urls()
    except Exception as exc:
        print(f"WARN known URL index: {exc}")
        known_urls = set()

    collected: dict[str, Lottery] = {}
    lead_budget = int(config.get("discovery_lead_link_limit", 20))
    queued = extracted_count = 0
    ai_page_budget = int(config.get("ai_max_pages_per_run", 12))
    for source in sorted(sources, key=_source_priority):
        source_lead_budget = (
            min(lead_budget, int(config.get("discovery_lead_per_source_limit", 3)))
            if source.get("kind") == "discovery" else 0
        )
        try:
            for page_source, html in source_pages(source, config):
                # Aggregation pages are link finders only.  Saving their new
                # external URLs as pending leads is free; a later run reads
                # each direct page once with AI.
                if page_source.get("kind") == "discovery" and source_lead_budget > 0:
                    for url, title in discovery_outbound_links(html, page_source["url"], page_source, source_lead_budget):
                        if url in known_urls or any(canonical_application_url(item.application_url) == url for item in collected.values()):
                            continue
                        lead = Lottery(
                            id=lottery_identity("店舗確認待ち", title, url),
                            title=title,
                            category=page_source.get("category", "both"),
                            store="店舗確認待ち",
                            store_key=page_source.get("store_key", "discovery_lead"),
                            source_url=page_source["url"],
                            application_url=url,
                            source_kind="lead",
                            status="pending",
                        )
                        collected[lead.id] = lead
                        known_urls.add(url)
                        queued += 1
                        lead_budget -= 1
                        source_lead_budget -= 1
                        if lead_budget <= 0 or source_lead_budget <= 0:
                            break
                    continue

                page_url = canonical_application_url(page_source["url"])
                # A manually submitted pending URL is intentionally checked
                # once despite already existing in Supabase.
                if page_source.get("kind") != "manual" and page_url in known_urls:
                    print(f"SKIP known page: {page_source['name']}")
                    continue
                if ai_page_budget <= 0:
                    print(f"SKIP AI budget: {page_source['name']}")
                    continue
                ai_page_budget -= 1
                document, allowed_links = page_document(html, page_source["url"], max_chars=int(config.get("ai_page_max_chars", 18000)))
                extracted = extract_with_ai(page_source, document, allowed_links, now, config)
                extracted_count += len(extracted)
                print(f"EXTRACTED {page_source['name']}: {len(extracted)} candidate(s)")
                for raw in extracted:
                    url = canonical_application_url(raw["application_url"])
                    if url in known_urls and page_source.get("kind") != "manual":
                        print(f"SKIP known application URL: {url}")
                        continue
                    raw["application_url"] = url
                    item = lottery_from_raw(raw, page_source)
                    if not raw.get("start_at") or not raw.get("deadline"):
                        item.status = "pending"
                        queued += 1
                    collected[item.id] = item
                    known_urls.add(url)
        except Exception as exc:
            print(f"WARN {source['name']}: {exc}")
            record_source_failure(source, exc)
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
    publish_public = os.getenv("PUBLISH_PUBLIC", "true").lower() == "true"
    # Approval is the safety gate for the public Website.  Do not spend ten
    # minutes collecting data only to silently discard the review queue when
    # the server-side Supabase key has not been registered in GitHub yet.
    if publish_public and not supabase_configured():
        raise RuntimeError(
            "Supabase同期が未設定です。GitHub ActionsのRepository secret "
            "SUPABASE_SECRET_KEY にSupabaseのservice_role keyを登録してください。"
        )
    old = load_state()
    old_by_url = notification_index(old)
    collected, source_count, extracted_count, queued = collect(config, now)
    retain_open_previous(collected, old, now)
    items = prepare_items(collected, old_by_url, config)
    new_items, started_items, calendar_items = mark_new_and_started(items, old_by_url, now)
    # A staff member decides which listings are public.  The saved crawler
    # state still keeps all candidates, so they remain available in the admin
    # dashboard instead of disappearing after one collection run. Development
    # runs deliberately do not change the real approval queue.
    try:
        statuses = sync_statuses(items, now) if publish_public else None
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
        # A start alert is useful only for a listing the officers have already
        # approved for the public Website.
        started_items = [
            item for item in started_items
            if statuses.get(canonical_application_url(item.application_url)) == "published"
        ]
    if publish_public:
        publish(items, public_calendar_items, config)
    notify(new_items, started_items, queued, publish_public)
    print(f"SUMMARY sources={source_count} extracted={extracted_count} public={len(items)} new={len(new_items)} started={len(started_items)} review_needed={queued}")


if __name__ == "__main__":
    main()
