"""Durable moderator decisions for public lottery listings.

This module is used both by the collector and the private GitHub Actions
workflow.  A suppressed application URL is never re-published by tomorrow's
collection run, and restoring it returns the saved listing immediately.
"""

import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .calendar import build_calendar
from .models import Lottery, canonical_application_url, deduplicate_lotteries


ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "data" / "lotteries.json"
MODERATION = ROOT / "data" / "moderation.json"


def load_moderation() -> dict:
    if not MODERATION.exists():
        return {"suppressed": {}}
    data = json.loads(MODERATION.read_text(encoding="utf-8"))
    data.setdefault("suppressed", {})
    return data


def suppressed_urls() -> set[str]:
    return set(load_moderation()["suppressed"])


def _write_moderation(data: dict) -> None:
    MODERATION.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _load_state() -> list[Lottery]:
    if not STATE.exists():
        return []
    return [Lottery(**item) for item in json.loads(STATE.read_text(encoding="utf-8"))]


def _write_public(items: list[Lottery]) -> None:
    items = deduplicate_lotteries(items)
    items.sort(key=lambda item: (item.deadline or "9999", item.title))
    STATE.write_text(json.dumps([item.to_dict() for item in items], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    build_calendar([item.to_dict() for item in items], ROOT / "docs", "Asia/Tokyo")


def suppress(application_url: str) -> str:
    key = canonical_application_url(application_url)
    moderation = load_moderation()
    current = _load_state()
    matching = [item for item in current if canonical_application_url(item.application_url) == key]
    saved = matching[0].to_dict() if matching else None
    moderation["suppressed"][key] = {
        "application_url": application_url,
        "suppressed_at": datetime.now(ZoneInfo("Asia/Tokyo")).isoformat(),
        "lottery": saved,
    }
    _write_moderation(moderation)
    _write_public([item for item in current if canonical_application_url(item.application_url) != key])
    return "非掲載にしました。次回以降の自動収集でも、この応募URLは再掲載されません。"


def restore(application_url: str) -> str:
    key = canonical_application_url(application_url)
    moderation = load_moderation()
    decision = moderation["suppressed"].pop(key, None)
    if not decision:
        raise ValueError("この応募URLは非掲載リストにありません。")
    current = _load_state()
    saved = decision.get("lottery")
    if saved:
        current.append(Lottery(**saved))
    _write_moderation(moderation)
    _write_public(current)
    return "復元しました。保存されていた抽選をWebsiteへ戻しました。"


def main() -> None:
    if len(sys.argv) != 3 or sys.argv[1] not in {"suppress", "restore"}:
        raise SystemExit("Usage: python -m src.moderation suppress|restore <application_url>")
    action, application_url = sys.argv[1:]
    print(suppress(application_url) if action == "suppress" else restore(application_url))


if __name__ == "__main__":
    main()
