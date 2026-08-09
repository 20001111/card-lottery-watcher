"""Synchronise lottery review decisions with Supabase.

Supabase is the source of truth for an officer's publish / pending / suppress
decision.  The collector may update the facts of a listing, but it must never
silently overwrite that decision.
"""

from __future__ import annotations

import os
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


def manual_review_sources(limit: int = 20) -> list[dict]:
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


def build_sync_rows(items: Iterable[Lottery], existing: dict[str, dict]) -> list[dict]:
    """Prepare rows while preserving a staff decision and its memo."""
    rows = []
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
        rows.append(
            {
                "application_url": url,
                "listing": listing,
                # New discoveries require approval. Existing decisions win.
                "status": before.get("status", "pending"),
                "overrides": overrides,
                "note": before.get("note", ""),
            }
        )
    return rows


def sync_statuses(items: Iterable[Lottery]) -> dict[str, str] | None:
    """Upsert collected listings and return their current publication states.

    ``None`` means that Supabase is not configured; this keeps the old
    Website behaviour until the secret is added to GitHub Actions.
    """
    if not configured():
        return None

    endpoint = _endpoint()
    headers = _headers()
    response = requests.get(endpoint, params={"select": "application_url,status,note,overrides"}, headers=headers, timeout=20)
    response.raise_for_status()
    existing = {
        canonical_application_url(row["application_url"]): row
        for row in response.json()
        if row.get("application_url")
    }
    rows = build_sync_rows(items, existing)
    if rows:
        upsert_headers = {**headers, "Prefer": "resolution=merge-duplicates"}
        response = requests.post(endpoint, params={"on_conflict": "application_url"}, headers=upsert_headers, json=rows, timeout=20)
        response.raise_for_status()
    return {row["application_url"]: row["status"] for row in rows}
