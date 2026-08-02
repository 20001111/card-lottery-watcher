"""Build the small, mobile-friendly lottery calendar published by GitHub Pages."""

from collections import defaultdict
from datetime import datetime
from html import escape
import json
from pathlib import Path
from zoneinfo import ZoneInfo


def _deadline(item: dict, timezone: str):
    value = item.get("deadline")
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone(ZoneInfo(timezone)) if parsed.tzinfo else parsed.replace(tzinfo=ZoneInfo(timezone))
    except ValueError:
        return None


def _date_label(value: str | None, timezone: str) -> str:
    if not value:
        return "開始日時の記載なし"
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone(ZoneInfo(timezone))
        return f"開始 {parsed:%m/%d %H:%M}"
    except ValueError:
        return f"開始 {value}"


def build_calendar(items: list[dict], destination: Path, timezone: str = "Asia/Tokyo"):
    """Write a self-contained index page and its JSON data for GitHub Pages."""
    destination.mkdir(parents=True, exist_ok=True)
    now = datetime.now(ZoneInfo(timezone))
    open_items = [item for item in items if item.get("eligibility") != "ineligible"]
    groups = defaultdict(list)
    for item in open_items:
        deadline = _deadline(item, timezone)
        if deadline:
            groups[deadline.date().isoformat()].append((deadline, item))

    sections = []
    for date_key in sorted(groups):
        cards = []
        for deadline, item in sorted(groups[date_key], key=lambda pair: pair[0]):
            urgency = " today" if deadline.date() == now.date() else " soon" if (deadline - now).days <= 2 else ""
            cards.append(
                f'<a class="lottery{urgency}" href="{escape(item.get("application_url", "#"), quote=True)}" target="_blank" rel="noreferrer">'
                f'<span class="time">{deadline:%H:%M}まで</span>'
                f'<strong>{escape(item.get("title", "抽選"))}</strong>'
                f'<span>{escape(item.get("store", ""))}</span>'
                f'<span>{escape(_date_label(item.get("start_at"), timezone))}</span>'
                '</a>'
            )
        day = datetime.fromisoformat(date_key).strftime("%m/%d")
        sections.append(f'<section><h2>{day}</h2><div class="items">{"".join(cards)}</div></section>')

    body = "".join(sections) or '<p class="empty">現在受付中の抽選はありません。</p>'
    page = f'''<!doctype html>
<html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>カード抽選カレンダー</title><style>
:root{{color-scheme:light dark;--bg:#f6f7fb;--card:#fff;--text:#1d2433;--muted:#667085;--accent:#2563eb;--soon:#fff7df;--today:#e8f0ff}}
@media(prefers-color-scheme:dark){{:root{{--bg:#10131a;--card:#1a1f2b;--text:#f2f4f7;--muted:#b3bdcc;--accent:#8ab4ff;--soon:#403413;--today:#192b4a}}}}
*{{box-sizing:border-box}} body{{margin:0;background:var(--bg);color:var(--text);font-family:system-ui,-apple-system,"Segoe UI",sans-serif}}
main{{max-width:760px;margin:auto;padding:20px 14px 40px}} h1{{font-size:1.45rem;margin:0 0 4px}} .sub{{color:var(--muted);margin:0 0 22px;font-size:.92rem}} section{{margin:22px 0}} h2{{font-size:1.05rem;margin:0 0 9px}} .items{{display:grid;gap:8px}}
.lottery{{display:grid;grid-template-columns:72px 1fr;gap:2px 10px;padding:13px;background:var(--card);border-radius:12px;text-decoration:none;color:inherit;box-shadow:0 1px 3px #0001}} .lottery strong{{grid-column:2;font-size:.98rem}} .lottery span:last-child{{grid-column:2;color:var(--muted);font-size:.84rem}} .time{{grid-row:1 / 3;align-self:center;color:var(--accent);font-weight:700;font-size:.85rem}} .soon{{background:var(--soon)}} .today{{background:var(--today);outline:2px solid var(--accent)}} .empty{{color:var(--muted)}}
</style></head><body><main><h1>カード抽選カレンダー</h1><p class="sub">締切順・日本時間。カードを押すと応募ページを開きます。</p>{body}</main></body></html>'''
    (destination / "index.html").write_text(page, encoding="utf-8")
    (destination / "lotteries.json").write_text(json.dumps(open_items, ensure_ascii=False, indent=2), encoding="utf-8")
