import json
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
import yaml

from .ai_extract import extract_with_ai, page_document
from .discord_notify import send_heading, send_or_update
from .eligibility import evaluate
from .models import Lottery

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "data" / "lotteries.json"


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
    for source in config["sources"]:
        try:
            response = requests.get(source["url"], headers=headers, timeout=config.get("request_timeout_seconds", 20))
            response.raise_for_status()
            document, allowed_links = page_document(response.text, source["url"])
            extracted = extract_with_ai(source, document, allowed_links, now, config)
            for raw in extracted:
                identity_source = f"{raw['store']}|{raw['title']}|{raw['application_url']}"
                import hashlib
                identity = hashlib.sha256(identity_source.encode()).hexdigest()[:20]
                conditions = list(raw.get("requirements") or [])
                item = Lottery(
                    id=identity,
                    title=raw["title"],
                    category=raw["card_type"],
                    store=raw["store"],
                    store_key=source.get("store_key", "unknown"),
                    source_url=source["url"],
                    application_url=raw["application_url"],
                    deadline=raw["deadline"],
                    start_at=raw.get("start_at"),
                    conditions=conditions,
                    source_kind=source.get("kind", "discovery"),
                    official_confirmed=source.get("kind") == "official",
                )
                collected[item.id] = evaluate(item, config.get("eligibility", {}))
        except Exception as exc:
            print(f"WARN {source['name']}: {exc}")

    for item in collected.values():
        item.discord_message_id = old.get(item.id, {}).get("discord_message_id")
    items = list(collected.values())
    items.sort(key=lambda x: (x.eligibility not in ("eligible", "check"), x.deadline or "9999"))

    webhook = os.getenv("DISCORD_WEBHOOK_URL")
    if not webhook:
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps([x.to_dict() for x in items], ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Collected {len(items)} items. DISCORD_WEBHOOK_URL is not configured; notification skipped.")
        return
    digest = [x for x in items if x.eligibility != "ineligible"]
    send_heading(webhook, f"📅 本日のカード抽選（締切順） {now:%Y/%m/%d}")
    for item in digest[:25]:
        try:
            item.discord_message_id = send_or_update(webhook, item)
        except Exception as exc:
            print(f"WARN Discord {item.title}: {exc}")
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps([x.to_dict() for x in items], ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
