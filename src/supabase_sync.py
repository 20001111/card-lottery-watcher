"""Synchronise lottery review decisions with Supabase.

Supabase is the source of truth for an officer's publish / pending / suppress
decision.  The collector may update the facts of a listing, but it must never
silently overwrite that decision.
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Iterable

import requests

from .models import Lottery, canonical_application_url


def configured() -> bool:
    return bool(os.getenv("SUPABASE_URL") and os.getenv("SUPABASE_SECRET_KEY"))


def _headers() -> dict[str, str]:
    key = os.environ["SUPABASE_SECRET_KEY"]
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }


def _endpoint() -> str:
    return os.environ["SUPABASE_URL"].rstrip("/") + "/rest/v1/lottery_listings"


def known_application_urls() -> set[str]:
    """Return every URL already stored in the review database.

    This is intentionally a very cheap request.  It runs *before* OpenAI is
    called so recurring links from aggregation sites do not consume AI calls.
    """
    if not configured():
        return set()
    response = requests.get(
        _endpoint(),
        params={"select": "application_url"},
        headers=_headers(),
        timeout=20,
    )
    response.raise_for_status()
    return {
        canonical_application_url(row.get("application_url", ""))
        for row in response.json()
        if row.get("application_url")
    }


def manual_review_sources(limit: int = 8) -> list[dict]:
    """Return staff-submitted URLs that should be fact-checked by AI.

    Officers can submit only an application URL in the private dashboard.  A
    later production collection visits that URL and fills title, store, dates,
    and conditions before anyone publishes it. Pending rows remain private;
    published staff entries are also revisited so they stay in the public
    collection on the next scheduled rebuild.
    """
    if not configured():
        return []
    response = requests.get(
        _endpoint(),
        params={
            "select": "application_url,listing",
            "status": "in.(pending,published)",
            "order": "created_at.asc",
            "limit": str(limit),
        },
        headers=_headers(),
        timeout=20,
    )
    response.raise_for_status()
    sources = []
    for row in response.json():
        listing = row.get("listing") or {}
        url = canonical_application_url(row.get("application_url", ""))
        if not url or listing.get("source_kind") not in {"manual", "lead"}:
            continue
        sources.append(
            {
                "name": "確認待ちの応募URL",
                "store_key": "manual_submission",
                "kind": "manual",
                "category": listing.get("category") or "both",
                "url": url,
            }
        )
    return sources


def record_source_failure(source: dict, error: Exception | str) -> None:
    """Persist a safe, short failure record for the officers.

    A source outage must not silently look like "there were no lotteries".
    Failure recording is best effort so an unavailable diagnostics table never
    prevents the normal collection and review queue from working.
    """
    if not configured():
        return
    message = str(error).replace("\n", " ")[:500]
    payload = {
        "source_name": str(source.get("name", "unknown"))[:160],
        "source_url": str(source.get("url", ""))[:1000],
        "error_type": type(error).__name__ if isinstance(error, Exception) else "Error",
        "message": message,
    }
    try:
        response = requests.post(
            os.environ["SUPABASE_URL"].rstrip("/") + "/rest/v1/collection_failures",
            headers={**_headers(), "Prefer": "return=minimal"},
            json=payload,
            timeout=12,
        )
        response.raise_for_status()
    except requests.RequestException as logging_error:
        print(f"WARN failure log: {logging_error}")


def _expired(listing: dict, now: datetime | None) -> bool:
    if now is None or not listing.get("deadline"):
        return False
    try:
        deadline = datetime.fromisoformat(str(listing["deadline"]).replace("Z", "+00:00"))
        deadline = deadline.replace(tzinfo=now.tzinfo) if deadline.tzinfo is None else deadline
        return deadline <= now
    except ValueError:
        return False


def _listing_quality(listing: dict) -> int:
    """Prefer the most complete version when sources share one entry URL."""
    fields = ("title", "store", "start_at", "deadline", "conditions", "region")
    score = sum(bool(listing.get(field)) for field in fields)
    if listing.get("source_kind") == "official":
        score += 1
    return score


def build_sync_rows(items: Iterable[Lottery], existing: dict[str, dict], now: datetime | None = None) -> list[dict]:
    """Prepare rows while preserving a staff decision and its memo."""
    # PostgREST rejects an upsert payload that contains the same conflict key
    # more than once.  A source can describe the exact same application URL
    # with slightly different titles, so enforce URL uniqueness here as the
    # final safety net after crawler-level deduplication.
    rows_by_url: dict[str, dict] = {}
    for item in items:
        url = canonical_application_url(item.application_url)
        if not url:
            continue
        before = existing.get(url, {})
        listing = item.to_dict()
        # Do not downgrade a staff-reviewed listing when a later scan finds
        # the same URL but cannot read a date or condition from the page.
        # Missing crawler facts should stay available for review, not erase
        # previously confirmed facts.
        previous_listing = before.get("listing") or {}
        for field in ("title", "store", "deadline", "start_at", "conditions"):
            value = listing.get(field)
            if (value is None or value == "" or value == []) and previous_listing.get(field):
                listing[field] = previous_listing[field]
        listing["application_url"] = url
        overrides = before.get("overrides") or {}
        for field in ("title", "store", "start_at", "deadline", "conditions", "region"):
            if field in overrides:
                listing[field] = overrides[field]
        current_status = before.get("status", "pending")
        # Published records are kept as history, but are automatically removed
        # from the public Website once their deadline passes.
        if current_status == "published" and _expired(listing, now):
            current_status = "expired"
        row = {
            "application_url": url,
            "listing": listing,
            # New discoveries require approval. Existing decisions win.
            "status": current_status,
            "overrides": overrides,
            "note": before.get("note", ""),
        }
        previous_row = rows_by_url.get(url)
        if previous_row is None or _listing_quality(listing) > _listing_quality(previous_row["listing"]):
            rows_by_url[url] = row
    return list(rows_by_url.values())


def sync_statuses(items: Iterable[Lottery], now: datetime | None = None) -> dict[str, str] | None:
    """Upsert collected listings and return their current publication states.

    ``None`` means that Supabase is not configured; this keeps the old
    Website behaviour until the secret is added to GitHub Actions.
    """
    if not configured():
        return None

    endpoint = _endpoint()
    headers = _headers()
    # ``listing`` is required here too: it preserves staff-confirmed facts and
    # lets us expire a published entry even when its source later disappears.
    response = requests.get(
        endpoint,
        params={"select": "application_url,status,note,overrides,listing"},
        headers=headers,
        timeout=20,
    )
    response.raise_for_status()
    existing = {
        canonical_application_url(row["application_url"]): row
        for row in response.json()
        if row.get("application_url")
    }
    rows = build_sync_rows(items, existing, now)
    seen_urls = {row["application_url"] for row in rows}
    # A listing can disappear from its source after the deadline.  Preserve it
    # as history anyway, instead of requiring a later crawler match in order
    # to mark it expired.
    for url, before in existing.items():
        listing = before.get("listing") or {}
        if (
            url not in seen_urls
            and before.get("status") == "published"
            and _expired(listing, now)
        ):
            rows.append(
                {
                    "application_url": url,
                    "listing": listing,
                    "status": "expired",
                    "overrides": before.get("overrides") or {},
                    "note": before.get("note", ""),
                }
            )
    if rows:
        upsert_headers = {**headers, "Prefer": "resolution=merge-duplicates"}
        response = requests.post(endpoint, params={"on_conflict": "application_url"}, headers=upsert_headers, json=rows, timeout=20)
        response.raise_for_status()
    return {row["application_url"]: row["status"] for row in rows}
