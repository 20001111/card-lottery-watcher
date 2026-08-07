"""Send incomplete candidates to the private review dashboard."""

import os

import requests

from .models import lottery_identity


def send_candidate(raw: dict, source: dict) -> bool:
    """Queue a candidate without putting it in the public GitHub Pages data."""
    endpoint = os.getenv("ADMIN_QUEUE_URL")
    key = os.getenv("ADMIN_QUEUE_KEY")
    if not endpoint or not key:
        return False
    title = str(raw.get("title") or "").strip()
    url = str(raw.get("application_url") or "").strip()
    if not title or not url:
        return False
    requirements = " / ".join(raw.get("requirements") or [])
    evidence = str(raw.get("evidence") or "").strip()
    missing = []
    if not raw.get("start_at"):
        missing.append("開始日")
    if not raw.get("deadline"):
        missing.append("締切")
    notes = f"AI確認候補。未確認: {'・'.join(missing)}"
    if requirements:
        notes += f"\n条件: {requirements}"
    if evidence:
        notes += f"\n根拠: {evidence}"
    payload = {
        "externalId": lottery_identity(str(raw.get("store") or source.get("name") or ""), title, url),
        "source": "ai",
        "title": title,
        "store": str(raw.get("store") or source.get("name") or "").strip(),
        "url": url,
        "notes": notes,
        "region": "unknown",
    }
    response = requests.post(endpoint, json=payload, headers={"X-Admin-Ingest-Key": key}, timeout=12)
    response.raise_for_status()
    return True
