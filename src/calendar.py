"""Build a Japanese month-grid lottery calendar for GitHub Pages."""

import calendar as calendar_module
from collections import defaultdict
from datetime import datetime
from html import escape
import json
from pathlib import Path
from zoneinfo import ZoneInfo


WEEKDAYS = ("\u6708", "\u706b", "\u6c34", "\u6728", "\u91d1", "\u571f", "\u65e5")


def _parse_date(value: str | None, timezone: str):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone(ZoneInfo(timezone)) if parsed.tzinfo else parsed.replace(tzinfo=ZoneInfo(timezone))
    except ValueError:
        return None


def _start_label(value: str | None, timezone: str) -> str:
    parsed = _parse_date(value, timezone)
    return f"{parsed:%m/%d %H:%M}" if parsed else "\u8a18\u8f09\u306a\u3057"


def _event(item: dict, deadline: datetime, timezone: str) -> str:
    conditions = " / ".join(item.get("conditions") or []) or "\u8a18\u8f09\u306a\u3057"
    verification = "\u516c\u5f0f\u78ba\u8a8d\u6e08\u307f" if item.get("official_confirmed") else "\u516c\u5f0f\u78ba\u8a8d\u5f85\u3061"
    evidence = item.get("evidence") or "\u30ea\u30f3\u30af\u5148\u306e\u8a73\u7d30\u3092\u3054\u78ba\u8a8d\u304f\u3060\u3055\u3044"
    title = escape(item.get("title", "\u62bd\u9078"))
    store = escape(item.get("store", ""))
    url = escape(item.get("application_url", "#"), quote=True)
    return (
        '<details class="event"><summary>'
        f'<span class="event-time">{deadline:%H:%M}</span>{title}'
        f'<small>{store}</small></summary><div class="event-detail">'
        f'<p><b>\u958b\u59cb</b>{escape(_start_label(item.get("start_at"), timezone))}</p>'
        f'<p><b>\u7de0\u5207</b>{deadline:%m/%d %H:%M}</p>'
        f'<p><b>\u6761\u4ef6</b>{escape(conditions)}</p>'
        f'<p><b>{verification}</b>{escape(evidence)}</p>'
        f'<a href="{url}" target="_blank" rel="noreferrer">\u5fdc\u52df\u30da\u30fc\u30b8\u3092\u958b\u304f</a>'
        '</div></details>'
    )


def _month(year: int, month: int, by_day: dict, now: datetime, timezone: str) -> str:
    first_weekday, days = calendar_module.monthrange(year, month)
    cells = ['<div class="blank"></div>'] * first_weekday
    for day in range(1, days + 1):
        date_key = f"{year:04d}-{month:02d}-{day:02d}"
        today = " today" if date_key == now.date().isoformat() else ""
        events = "".join(_event(item, deadline, timezone) for deadline, item in by_day.get(date_key, []))
        cells.append(f'<div class="day{today}"><time>{day}</time>{events}</div>')
    while len(cells) % 7:
        cells.append('<div class="blank"></div>')
    headers = "".join(f'<div class="weekday">{name}</div>' for name in WEEKDAYS)
    return (
        f'<section class="month"><h2>{year}\u5e74{month}\u6708</h2>'
        f'<div class="weekdays">{headers}</div><div class="grid">{"".join(cells)}</div></section>'
    )


def build_calendar(items: list[dict], destination: Path, timezone: str = "Asia/Tokyo"):
    """Write a self-contained month-grid page and JSON data for GitHub Pages."""
    destination.mkdir(parents=True, exist_ok=True)
    now = datetime.now(ZoneInfo(timezone))
    open_items = [item for item in items if item.get("eligibility") != "ineligible"]
    by_day = defaultdict(list)
    months = set()
    for item in open_items:
        deadline = _parse_date(item.get("deadline"), timezone)
        if deadline:
            by_day[deadline.date().isoformat()].append((deadline, item))
            months.add((deadline.year, deadline.month))
    for day_events in by_day.values():
        day_events.sort(key=lambda pair: pair[0])

    body = "".join(_month(year, month, by_day, now, timezone) for year, month in sorted(months))
    if not body:
        body = '<p class="empty">\u73fe\u5728\u53d7\u4ed8\u4e2d\u306e\u62bd\u9078\u306f\u3042\u308a\u307e\u305b\u3093\u3002</p>'
    page = f'''<!doctype html>
<html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>\u30ab\u30fc\u30c9\u62bd\u9078\u30ab\u30ec\u30f3\u30c0\u30fc</title><style>
:root{{--bg:#f6f7fb;--card:#fff;--text:#1d2433;--muted:#667085;--accent:#2563eb;--line:#dbe2ef;--sat:#eef4ff;--sun:#fff2f2}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--text);font-family:system-ui,-apple-system,"Segoe UI",sans-serif}}main{{max-width:1100px;margin:auto;padding:20px 14px 44px}}h1{{font-size:1.5rem;margin:0 0 4px}}.sub{{color:var(--muted);margin:0 0 22px;font-size:.92rem}}.month{{margin:24px 0}}h2{{font-size:1.12rem;margin:0 0 8px}}.weekdays,.grid{{display:grid;grid-template-columns:repeat(7,minmax(0,1fr))}}.weekday{{padding:7px 4px;text-align:center;font-size:.8rem;font-weight:700;color:var(--muted)}}.weekday:nth-child(6){{color:#2870ce}}.weekday:nth-child(7){{color:#d14f4f}}.day,.blank{{min-height:132px;border:1px solid var(--line);background:var(--card);padding:5px}}.blank{{background:#eef1f6}}.day:nth-child(7n+6){{background:var(--sat)}}.day:nth-child(7n){{background:var(--sun)}}.day.today{{outline:2px solid var(--accent);outline-offset:-2px}}time{{display:block;font-size:.82rem;font-weight:700;margin:1px 2px 5px}}.event{{margin:4px 0;border-radius:6px;background:#e8f0ff;overflow:hidden;font-size:.75rem}}.event summary{{cursor:pointer;list-style:none;padding:5px;line-height:1.3;overflow-wrap:anywhere}}.event summary::-webkit-details-marker{{display:none}}.event-time{{font-weight:800;color:var(--accent);margin-right:4px}}.event small{{display:block;color:var(--muted);margin-top:2px}}.event-detail{{padding:6px;background:var(--card);border-top:1px solid var(--line)}}.event-detail p{{margin:4px 0;line-height:1.35}}.event-detail b{{display:inline-block;min-width:38px;color:var(--muted)}}.event-detail a{{display:block;margin-top:7px;padding:7px;border-radius:5px;text-align:center;text-decoration:none;background:var(--accent);color:#fff;font-weight:700}}.empty{{color:var(--muted)}}
@media(max-width:650px){{main{{padding:16px 6px 32px}}.weekday{{font-size:.7rem;padding:5px 1px}}.day,.blank{{min-height:108px;padding:3px}}time{{font-size:.72rem}}.event{{font-size:.66rem;margin:3px 0}}.event summary{{padding:4px}}.event-detail{{font-size:.76rem}}}}
</style></head><body><main><h1>\u30ab\u30fc\u30c9\u62bd\u9078\u30ab\u30ec\u30f3\u30c0\u30fc</h1><p class="sub">\u7de0\u5207\u65e5\u30d9\u30fc\u30b9\u3002\u62bd\u9078\u540d\u3092\u62bc\u3059\u3068\u6761\u4ef6\u3068\u5fdc\u52df\u30ea\u30f3\u30af\u3092\u78ba\u8a8d\u3067\u304d\u307e\u3059\u3002</p>{body}</main></body></html>'''
    (destination / "index.html").write_text(page, encoding="utf-8")
    (destination / "lotteries.json").write_text(json.dumps(open_items, ensure_ascii=False, indent=2), encoding="utf-8")
