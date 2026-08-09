"""Build an iPhone-calendar-style lottery schedule for GitHub Pages."""

from datetime import date, datetime, timedelta
from html import escape
import hashlib
import json
from pathlib import Path
from zoneinfo import ZoneInfo


WEEKDAYS = ("\u65e5", "\u6708", "\u706b", "\u6c34", "\u6728", "\u91d1", "\u571f")
STORE_COLORS = (("#bfdbfe", "#1e40af"), ("#bbf7d0", "#166534"), ("#fde68a", "#92400e"), ("#ddd6fe", "#5b21b6"), ("#fecdd3", "#9f1239"), ("#a5f3fc", "#155e75"))


def _parse_date(value: str | None, timezone: str):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone(ZoneInfo(timezone)) if parsed.tzinfo else parsed.replace(tzinfo=ZoneInfo(timezone))
    except ValueError:
        return None


def _minutes_percent(value: datetime) -> float:
    return round((value.hour * 60 + value.minute) / 1440 * 100, 2)


def _date_time(value: datetime) -> str:
    return f"{value:%m/%d}({WEEKDAYS[(value.weekday() + 1) % 7]}) {value:%H:%M}"


def _kind(item: dict) -> str:
    return "pokemon" if item.get("category") == "pokemon" else "onepiece" if item.get("category") == "onepiece" else "other"


def _store_style(item: dict) -> str:
    """Use a stable colour for the same store group everywhere on the page."""
    store_key = str(item.get("store_key") or "").strip().lower()
    key = str(item.get("store") or store_key or "other").strip().lower()
    index = int(hashlib.sha256(key.encode("utf-8")).hexdigest()[:8], 16) % len(STORE_COLORS)
    background, foreground = STORE_COLORS[index]
    return f"--event:{background};--event-text:{foreground};"


def _application_status_style(view: str) -> str:
    """Use the card background to answer the most important question first."""
    if view == "upcoming":
        return "--event:#fee2e2;--event-text:#b91c1c;"
    return "--event:#dcfce7;--event-text:#166534;"


def _detail(item: dict, start: datetime, deadline: datetime) -> str:
    conditions = " / ".join(item.get("conditions") or []) or "\u8a18\u8f09\u306a\u3057"
    verification = "\u516c\u5f0f\u78ba\u8a8d\u6e08\u307f" if item.get("official_confirmed") else "\u516c\u5f0f\u78ba\u8a8d\u5f85\u3061"
    evidence = item.get("evidence") or "\u30ea\u30f3\u30af\u5148\u306e\u8a73\u7d30\u3092\u3054\u78ba\u8a8d\u304f\u3060\u3055\u3044"
    url = escape(item.get("application_url", "#"), quote=True)
    return (
        '<div class="detail">'
        f'<p>\U0001f3ea <b>\u5e97\u8217</b>{escape(item.get("store", "\u8a18\u8f09\u306a\u3057"))}</p>'
        f'<p>\U0001f4c5 <b>\u958b\u59cb</b>{start:%m/%d %H:%M}</p>'
        f'<p>\u23f0 <b>\u7de0\u5207</b>{deadline:%m/%d %H:%M}</p>'
        f'<p class="condition-detail">\U0001f4cb <b>\u5fdc\u52df\u6761\u4ef6</b>{escape(conditions)}</p>'
        f'<p><b>{verification}</b>{escape(evidence)}</p>'
        f'<a href="{url}" target="_blank" rel="noreferrer">\U0001f310 Web\u3067\u5fdc\u52df\u30da\u30fc\u30b8\u3092\u958b\u304f</a></div>'
    )


def _bar_segments(week_start: date, entries: list[tuple[dict, datetime, datetime]]) -> tuple[list[str], int]:
    """Return non-overlapping horizontal bars for one Sunday-to-Saturday week."""
    week_end = week_start + timedelta(days=6)
    candidates = []
    for item, start, deadline in entries:
        first = max(start.date(), week_start)
        last = min(deadline.date(), week_end)
        if first > last:
            continue
        start_column = (first - week_start).days + 1
        end_column = (last - week_start).days + 2
        candidates.append((start_column, end_column, first, last, item, start, deadline))
    candidates.sort(key=lambda value: (value[0], value[1], value[4].get("title", "")))

    lanes: list[list[tuple[int, int]]] = []
    bars = []
    for start_column, end_column, first, last, item, start, deadline in candidates:
        lane = next(
            (index for index, occupied in enumerate(lanes) if all(end_column <= left or start_column >= right for left, right in occupied)),
            len(lanes),
        )
        if lane == len(lanes):
            lanes.append([])
        lanes[lane].append((start_column, end_column))
        span = end_column - start_column
        left = _minutes_percent(start) / span if first == start.date() else 0
        right = (100 - _minutes_percent(deadline)) / span if last == deadline.date() else 0
        if first == start.date() and last == deadline.date():
            edge = "single"
            label = f"{start:%H:%M}\u301c{deadline:%H:%M}"
        elif first == start.date():
            edge = "start"
            label = f"{start:%H:%M}\u304b\u3089"
        elif last == deadline.date():
            edge = "end"
            label = f"\u301c{deadline:%H:%M}"
        else:
            edge = "middle"
            label = "\u53d7\u4ed8\u4e2d"
        style = _store_style(item) + f"grid-column:{start_column}/{end_column};grid-row:{lane + 1};margin-left:{left}%;margin-right:{right}%;"
        title = escape(item.get("title", "\u62bd\u9078"))
        store = escape(item.get("store", ""))
        new_badge = '<mark class="new-badge">NEW</mark>' if item.get("is_new") else ""
        bars.append(
            f'<details class="bar {_kind(item)} edge-{edge}" style="{style}"><summary>'
            f'<span>{label}</span>{new_badge}<strong>{store}</strong>{title}<small>{store}</small></summary>{_detail(item, start, deadline)}</details>'
        )
    return bars, max(1, len(lanes))


def _week(week_start: date, year: int, month: int, entries: list[tuple[dict, datetime, datetime]], today: date) -> str:
    dates = []
    for offset in range(7):
        current = week_start + timedelta(days=offset)
        classes = ["date"]
        if current.month != month:
            classes.append("outside")
        if current == today:
            classes.append("today")
        dates.append(f'<div class="{" ".join(classes)}"><time>{current.day}</time></div>')
    bars, lanes = _bar_segments(week_start, entries)
    return (
        '<div class="week"><div class="dates">' + "".join(dates) + '</div>'
        f'<div class="bars" style="grid-template-rows:repeat({lanes},minmax(30px,auto))">{"".join(bars)}</div></div>'
    )


def _month(year: int, month: int, entries: list[tuple[dict, datetime, datetime]], today: date) -> str:
    first = date(year, month, 1)
    last = date(year + (month == 12), 1 if month == 12 else month + 1, 1) - timedelta(days=1)
    first_sunday = first - timedelta(days=(first.weekday() + 1) % 7)
    last_saturday = last + timedelta(days=(5 - last.weekday()) % 7)
    weeks = []
    cursor = first_sunday
    while cursor <= last_saturday:
        weeks.append(_week(cursor, year, month, entries, today))
        cursor += timedelta(days=7)
    headers = "".join(f'<div>{name}</div>' for name in WEEKDAYS)
    return f'<section class="month"><h2>{year}\u5e74{month}\u6708</h2><div class="weekdays">{headers}</div>{"".join(weeks)}</section>'


def _lottery_list(entries: list[tuple[dict, datetime, datetime]], now: datetime, view: str = "active") -> str:
    """Build separate lists for lotteries open now and lotteries opening later."""
    is_active = view == "active"
    active = sorted(
        (entry for entry in entries if entry[1] <= now < entry[2])
        if is_active
        else (entry for entry in entries if entry[1] > now),
        key=lambda entry: entry[2] if is_active else entry[1],
    )
    heading = "\u53d7\u4ed8\u4e2d\u306e\u62bd\u9078" if is_active else "\u3053\u308c\u304b\u3089\u53d7\u4ed8\u958b\u59cb\u306e\u62bd\u9078"
    empty = "\u73fe\u5728\u53d7\u4ed8\u4e2d\u306e\u62bd\u9078\u306f\u3042\u308a\u307e\u305b\u3093\u3002" if is_active else "\u73fe\u5728\u3001\u3053\u308c\u304b\u3089\u53d7\u4ed8\u958b\u59cb\u3068\u306a\u308b\u62bd\u9078\u306f\u3042\u308a\u307e\u305b\u3093\u3002"
    if not active:
        return f'<section class="current {view}"><h2>{heading}</h2><p class="empty">{empty}</p></section>'
    cards = []
    for item, start, deadline in active:
        store = escape(item.get("store", "\u5e97\u8217\u540d\u4e0d\u660e"))
        title = escape(item.get("title", "\u62bd\u9078"))
        item_id = escape(str(item.get("id", "")), quote=True)
        new_mark = '<mark style="display:inline-block;margin:0 6px 6px 0;padding:2px 6px;border-radius:5px;background:#ef4444;color:#fff;font-size:.7rem;font-weight:900;vertical-align:middle;">NEW</mark>' if item.get("is_new") else ""
        conditions = item.get("conditions") or []
        condition_text = " / ".join(conditions) or "\u8ffd\u52a0\u6761\u4ef6\u306e\u8a18\u8f09\u306a\u3057"
        condition_kind = "none" if not conditions else "has_conditions"
        application = item.get("application_method", "unknown")
        labels = []
        if condition_kind == "none": labels.append("\u8ffd\u52a0\u6761\u4ef6\u306e\u8a18\u8f09\u306a\u3057")
        elif condition_kind == "has_conditions": labels.append("\u8ffd\u52a0\u6761\u4ef6\u3042\u308a")
        if application == "online": labels.append("Web\u5fdc\u52df")
        elif application == "store": labels.append("\u5e97\u982d\u5fdc\u52df")
        tag_html = ''.join(f'<span class="tag">{escape(label)}</span>' for label in labels) or '<span class="tag muted">Web\u5fdc\u52df\u65b9\u6cd5\u306f\u8a73\u7d30\u3067\u78ba\u8a8d</span>'
        url = escape(item.get("application_url", "#"), quote=True)
        status_label = "\U0001f7e2 \u4eca\u3059\u3050\u5fdc\u52df\u53ef" if is_active else "\U0001f534 \u307e\u3060\u5fdc\u52df\u3067\u304d\u307e\u305b\u3093"
        cards.append(
            f'<article id="lottery-{item_id}" class="lottery-card" style="{_application_status_style(view)}" data-status="{view}" data-condition="{condition_kind}" data-application="{application}">'
            f'<span class="store-name">{status_label}　\U0001f3ea {store}</span>{new_mark}<h3>{title}</h3><span class="period"><i>\U0001f4c5 \u958b\u59cb</i>{_date_time(start)}<em>\u2192</em><i>\u23f0 \u7de0\u5207</i>{_date_time(deadline)}</span><span class="condition-summary">\U0001f4cb <strong>\u5fdc\u52df\u6761\u4ef6</strong> {escape(condition_text)}</span>'
            f'<div class="tags">{tag_html}</div><a class="apply-link" href="{url}" target="_blank" rel="noreferrer">\U0001f310 Web\u3067\u5fdc\u52df\u3059\u308b</a></article>'
        )
    filters = ''
    guidance = '\u5fdc\u52df\u6761\u4ef6\u306f\u5404\u30ab\u30fc\u30c9\u306b\u8868\u793a\u3057\u3066\u3044\u307e\u3059\u3002\u60c5\u5831\u5143\u306b\u660e\u8a18\u3055\u308c\u305f\u3082\u306e\u3060\u3051\u63b2\u8f09\u3057\u307e\u3059\u3002' if is_active else '\u958b\u59cb\u65e5\u6642\u3092\u78ba\u8a8d\u6e08\u307f\u306e\u60c5\u5831\u3067\u3059\u3002\u958b\u59cb\u6642\u523b\u3092\u904e\u304e\u308b\u3068\u300c\u53d7\u4ed8\u4e2d\u306e\u62bd\u9078\u300d\u3078\u79fb\u308a\u307e\u3059\u3002'
    card_styles = '<style>.lottery-card{padding:14px 15px 13px}.lottery-card h3{margin:3px 0 9px;font-size:1rem;line-height:1.45}.lottery-card .period{display:flex;flex-wrap:wrap;gap:5px;align-items:center;color:#374151;font-size:.82rem;margin:6px 0}.apply-link{display:block;margin-top:10px;padding:10px;text-align:center;text-decoration:none;border-radius:8px;background:#2563eb;color:#fff;font-weight:800}.hide-lottery,.reset-hidden{border:0;background:transparent;color:#4b5563;font-size:.78rem;font-weight:700;cursor:pointer;padding:8px 2px 0}.reset-hidden{padding:7px 4px;align-self:end;text-decoration:underline}.filters label:has(#application-filter){display:none}.user-hidden{display:none!important}</style><script>document.addEventListener("DOMContentLoaded",()=>{const target=location.hash?document.querySelector(location.hash):null;if(target){target.open=true;target.scrollIntoView({block:"center"});}const key="card-lottery-hidden";const load=()=>{try{return new Set(JSON.parse(localStorage.getItem(key)||"[]"));}catch{return new Set();}};let hidden=load();const render=()=>document.querySelectorAll(".lottery-card").forEach(card=>card.classList.toggle("user-hidden",hidden.has(card.dataset.lotteryId)));render();document.addEventListener("click",event=>{const button=event.target.closest(".hide-lottery");if(!button)return;hidden.add(button.dataset.lotteryId);try{localStorage.setItem(key,JSON.stringify([...hidden]));}catch{}render();});document.getElementById("reset-hidden")?.addEventListener("click",()=>{hidden.clear();try{localStorage.removeItem(key);}catch{}render();});const condition=document.getElementById("condition-filter");condition?.addEventListener("change",()=>{document.querySelectorAll(".lottery-card[data-status=active]").forEach(card=>{card.hidden=condition.value!=="all"&&card.dataset.condition!==condition.value;});});})</script>'
    # This second, direct handler intentionally has no dependency on filters or URL hashes.
    # It keeps the per-browser hide action working even if another page enhancement fails.
    card_styles += '<script>window.addEventListener("load",()=>{const key="card-lottery-hidden";let hidden;try{hidden=new Set(JSON.parse(localStorage.getItem(key)||"[]"));}catch{hidden=new Set();}const paint=()=>document.querySelectorAll(".lottery-card").forEach(card=>card.style.display=hidden.has(card.dataset.lotteryId)?"none":"");document.querySelectorAll(".hide-lottery").forEach(button=>button.onclick=()=>{hidden.add(button.dataset.lotteryId);try{localStorage.setItem(key,JSON.stringify([...hidden]));}catch{}paint();});const reset=document.getElementById("reset-hidden");if(reset)reset.onclick=()=>{hidden.clear();try{localStorage.removeItem(key);}catch{}paint();};paint();});</script>'
    # Keep cards static and dependable. Per-user hiding is intentionally not part
    # of the public website.
    card_styles = '<style>.lottery-card{padding:14px 15px 13px}.lottery-card h3{margin:3px 0 9px;font-size:1rem;line-height:1.45}.lottery-card .period{display:flex;flex-wrap:wrap;gap:5px;align-items:center;color:#374151;font-size:.82rem;margin:6px 0}.apply-link{display:block;margin-top:10px;padding:10px;text-align:center;text-decoration:none;border-radius:8px;background:#2563eb;color:#fff;font-weight:800}</style>'
    return card_styles + f'<section class="current {view}"><h2>{heading}</h2><p class="sub">{guidance}</p>{filters}' + ''.join(cards) + '</section>'


def _pending_page(items: list[dict]) -> str:
    """Show candidates that need a human to fill in one or both dates."""
    cards = []
    for item in items:
        if item.get("eligibility") == "ineligible":
            continue
        missing = []
        if not item.get("start_at"):
            missing.append("\u958b\u59cb\u65e5")
        if not item.get("deadline"):
            missing.append("\u7d42\u4e86\u65e5")
        if not missing:
            continue
        title = escape(item.get("title", "\u62bd\u9078\u60c5\u5831"))
        store = escape(item.get("store", ""))
        url = escape(item.get("application_url", "#"), quote=True)
        conditions = escape(" / ".join(item.get("conditions") or []) or "\u8a18\u8f09\u306a\u3057")
        verification = "\u516c\u5f0f\u78ba\u8a8d\u6e08\u307f" if item.get("official_confirmed") else "\u516c\u5f0f\u78ba\u8a8d\u5f85\u3061"
        cards.append(
            '<article class="candidate">'
            f'<h2>{title}</h2><p class="store">{store}</p>'
            f'<p><b>\u672a\u78ba\u5b9a</b>\uff1a{"\u30fb".join(missing)} \u3092\u78ba\u8a8d\u4e2d</p>'
            f'<p><b>{verification}</b></p>'
            f'<p>\u6761\u4ef6\uff1a{conditions}</p>'
            f'<a href="{url}" target="_blank" rel="noreferrer">\u60c5\u5831\u5143\u30fb\u5fdc\u52df\u30da\u30fc\u30b8\u3092\u958b\u304f</a></article>'
        )
    content = "".join(cards) or '<p class="empty">\u73fe\u5728\u3001\u8ffd\u52a0\u78ba\u8a8d\u5f85\u3061\u306e\u60c5\u5831\u306f\u3042\u308a\u307e\u305b\u3093\u3002</p>'
    return f'''<!doctype html>
<html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>\u672a\u78ba\u5b9a\u30fb\u78ba\u8a8d\u5f85\u3061\u306e\u62bd\u9078\u60c5\u5831</title><style>
body{{margin:0;background:#f8fafc;color:#111827;font-family:system-ui,-apple-system,"Segoe UI",sans-serif}}main{{max-width:720px;margin:auto;padding:24px 16px 48px}}h1{{margin:0 0 5px}}.sub,.store{{color:#6b7280}}.back{{display:inline-block;margin:0 0 20px;color:#2563eb}}.candidate{{background:#fff;border:1px solid #e5e7eb;border-left:5px solid #f59e0b;border-radius:10px;margin:14px 0;padding:15px}}.candidate h2{{font-size:1rem;margin:0}}.candidate p{{line-height:1.5}}.candidate a{{display:inline-block;background:#2563eb;border-radius:6px;color:#fff;padding:8px 11px;text-decoration:none;font-weight:700}}.empty{{color:#6b7280}}
</style></head><body><main><a class="back" href="./">\u2190 \u30ab\u30ec\u30f3\u30c0\u30fc\u3078\u623b\u308b</a><h1>\u672a\u78ba\u5b9a\u30fb\u78ba\u8a8d\u5f85\u3061\u306e\u62bd\u9078\u60c5\u5831</h1><p class="sub">\u62bd\u9078\u3089\u3057\u3044\u60c5\u5831\u306f\u898b\u3064\u304b\u3063\u305f\u3082\u306e\u306e\u3001\u958b\u59cb\u65e5\u307e\u305f\u306f\u7de0\u5207\u304c\u8db3\u308a\u306a\u3044\u5019\u88dc\u3067\u3059\u3002\u65e5\u4ed8\u3092\u78ba\u8a8d\u3067\u304d\u305f\u3082\u306e\u3060\u3051\u3001\u901a\u5e38\u306e\u30ab\u30ec\u30f3\u30c0\u30fc\u3078\u79fb\u3057\u307e\u3059\u3002</p>{content}</main></body></html>'''


def build_calendar(items: list[dict], destination: Path, timezone: str = "Asia/Tokyo"):
    """Write a self-contained month-grid page and JSON data for GitHub Pages."""
    destination.mkdir(parents=True, exist_ok=True)
    now = datetime.now(ZoneInfo(timezone))
    entries = []
    months = set()
    pending_items = []
    for item in items:
        if item.get("eligibility") == "ineligible":
            continue
        deadline = _parse_date(item.get("deadline"), timezone)
        start = _parse_date(item.get("start_at"), timezone)
        # The calendar is intentionally strict: an item needs both ends of the
        # application period. Everything else remains on the review page.
        if not deadline or not start:
            pending_items.append(item)
            continue
        if start > deadline:
            pending_items.append(item)
            start = deadline
            continue
        entries.append((item, start, deadline))
        cursor = date(start.year, start.month, 1)
        final = date(deadline.year, deadline.month, 1)
        while cursor <= final:
            months.add((cursor.year, cursor.month))
            cursor = date(cursor.year + (cursor.month == 12), 1 if cursor.month == 12 else cursor.month + 1, 1)
    body = "".join(_month(year, month, entries, now.date()) for year, month in sorted(months))
    if not body:
        body = '<p class="empty">\u73fe\u5728\u53d7\u4ed8\u4e2d\u306e\u62bd\u9078\u306f\u3042\u308a\u307e\u305b\u3093\u3002</p>'
    page = f'''<!doctype html>
<html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>\u30ab\u30fc\u30c9\u62bd\u9078\u30ab\u30ec\u30f3\u30c0\u30fc</title><style>
:root{{--bg:#fff;--text:#111827;--muted:#7a8290;--line:#e5e7eb;--pokemon:#b9dcff;--onepiece:#ffe0a4;--other:#dcc8ff}}*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--text);font-family:system-ui,-apple-system,"Segoe UI",sans-serif}}main{{max-width:1060px;margin:auto;padding:22px 12px 48px}}h1{{font-size:1.6rem;margin:0 0 4px}}.sub{{color:var(--muted);margin:0 0 22px}}.month{{margin:28px 0}}h2{{font-size:1.25rem;margin:0 0 8px}}.weekdays,.dates,.bars{{display:grid;grid-template-columns:repeat(7,minmax(0,1fr))}}.weekdays{{border-bottom:1px solid var(--line);color:var(--muted);font-weight:700;text-align:center;font-size:.82rem;padding-bottom:7px}}.weekdays div:first-child{{color:#e05c64}}.weekdays div:last-child{{color:#4f7fd5}}.week{{border-bottom:1px solid var(--line);min-height:118px;padding:7px 0 9px}}.dates{{height:28px}}.date{{padding:0 5px;font-weight:700;font-size:.92rem}}.date:first-child{{color:#e05c64}}.date:last-child{{color:#4f7fd5}}.date.outside{{color:#c4c8d0}}.date.today time{{display:inline-grid;place-items:center;width:28px;height:28px;margin-top:-4px;border-radius:50%;background:#ff3b45;color:#fff}}.bars{{grid-auto-flow:row;gap:4px 0;margin-top:2px}}.bar{{min-width:0;overflow:visible;border-radius:8px;font-size:.75rem;position:relative}}.bar summary{{cursor:pointer;list-style:none;padding:5px 7px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;line-height:1.2}}.bar summary::-webkit-details-marker{{display:none}}.bar summary span{{font-weight:800;margin-right:4px}}.bar summary small{{display:none}}.bar.pokemon{{background:var(--pokemon);color:#16558c}}.bar.onepiece{{background:var(--onepiece);color:#805800}}.bar.other{{background:var(--other);color:#573a9b}}.bar.edge-start{{border-radius:8px 0 0 8px}}.bar.edge-middle{{border-radius:0}}.bar.edge-end{{border-radius:0 8px 8px 0}}.detail{{position:relative;z-index:3;margin-top:3px;padding:9px;background:#fff;border:1px solid var(--line);border-radius:8px;box-shadow:0 8px 20px #0002;white-space:normal;color:var(--text);min-width:230px}}.detail p{{margin:5px 0;line-height:1.4}}.detail b{{display:inline-block;min-width:52px;color:var(--muted)}}.detail a{{display:block;margin-top:8px;padding:8px;text-decoration:none;text-align:center;border-radius:6px;background:#2563eb;color:#fff;font-weight:700}}.empty{{color:var(--muted)}}
.bar summary strong{{display:inline-block;margin-right:4px;padding:1px 4px;border-radius:4px;background:#ffffffa8;font-weight:800}}.bar{{background:var(--event);color:var(--event-text)}}.bar.pokemon,.bar.onepiece,.bar.other{{background:var(--event);color:var(--event-text)}}.new-badge{{display:inline-block;margin-right:4px;padding:1px 4px;border:0;border-radius:4px;background:#ef4444;color:#fff;font-size:.68rem;font-weight:900;vertical-align:1px}}
.current{{margin:22px 0 34px}}.filters{{display:flex;flex-wrap:wrap;gap:8px;margin:10px 0 14px}}.filters label{{display:grid;gap:3px;font-size:.78rem;color:#4b5563;font-weight:700}}.filters select{{border:1px solid #cbd5e1;border-radius:7px;background:#fff;padding:7px;color:#111827}}.lottery-card{{display:block;border:1px solid var(--event);border-left:7px solid var(--event-text);border-radius:12px;margin:12px 0;background:var(--event);box-shadow:0 2px 8px #0f172a0d}}.lottery-card summary{{cursor:pointer;list-style:none;padding:14px 15px 10px}}.lottery-card summary::-webkit-details-marker{{display:none}}.store-name{{display:block;margin-bottom:7px;color:var(--event-text);font-size:.9rem;font-weight:900}}.lottery-card summary b{{display:block;font-size:1rem;line-height:1.45;margin:3px 0 9px}}.lottery-card summary .period{{display:flex;flex-wrap:wrap;gap:5px;align-items:center;color:#374151;font-size:.82rem;margin:6px 0}}.period i{{font-style:normal;border-radius:5px;background:#ffffffbf;color:var(--event-text);font-weight:900;padding:3px 6px}}.period em{{font-style:normal;color:#6b7280;font-size:1rem}}.condition-summary{{display:block;padding:8px 9px;border-radius:7px;background:#fff9;border-left:3px solid #f59e0b;font-size:.82rem;line-height:1.45;max-height:3.25em;overflow:hidden}}.condition-summary strong{{color:#92400e}}.tags{{padding:0 15px 11px;display:flex;gap:5px;flex-wrap:wrap}}.tag{{font-size:.74rem;font-weight:800;padding:3px 7px;border-radius:99px;background:#ffffffc7;color:var(--event-text)}}.tag.muted{{color:#4b5563}}.lottery-card .detail{{margin:0 12px 12px}}.detail .condition-detail{{padding:8px;border-radius:7px;background:#fff7ed;font-weight:700}} 
@media(max-width:650px){{main{{padding:16px 4px 30px}}h1{{padding:0 8px;font-size:1.35rem}}.sub{{padding:0 8px;font-size:.82rem}}h2{{padding:0 8px;font-size:1.05rem}}.weekdays{{font-size:.72rem}}.week{{min-height:108px;padding-top:6px}}.date{{padding:0 3px;font-size:.8rem}}.bar{{font-size:.61rem}}.bar summary{{padding:4px 3px}}.detail{{font-size:.78rem;min-width:205px}}}}
</style></head><body><main><h1>\u30ab\u30fc\u30c9\u62bd\u9078\u30ab\u30ec\u30f3\u30c0\u30fc</h1><p class="sub">\u958b\u59cb\u65e5\u3068\u7d42\u4e86\u65e5\u304c\u78ba\u8a8d\u3067\u304d\u305f\u62bd\u9078\u3060\u3051\u3092\u63b2\u8f09\u3057\u307e\u3059\u3002</p>{_lottery_list(entries, now, "active")}{_lottery_list(entries, now, "upcoming")}<h2>\u53d7\u4ed8\u671f\u9593\u30ab\u30ec\u30f3\u30c0\u30fc</h2>{body}</main><script>const target=document.querySelector(location.hash);if(target&&target.tagName==='DETAILS'){{target.open=true;setTimeout(()=>target.scrollIntoView({{block:'center'}}),0);}}const filters=[['condition-filter','condition'],['application-filter','application'],['receipt-filter','receipt']];function applyFilters(){{document.querySelectorAll('.lottery-card').forEach(card=>{{if(card.dataset.status!=='active')return;card.hidden=!filters.every(([id,key])=>{{const value=document.getElementById(id).value;return value==='all'||card.dataset[key]===value;}});}})}}filters.forEach(([id])=>{{const select=document.getElementById(id);if(select){{select.addEventListener('change',applyFilters);}}}});</script></body></html>'''
    # The old static footer is kept for backwards compatibility, but an empty
    # URL fragment is not a valid CSS selector and used to throw on every load.
    page = page.replace(
        "<script>const target=document.querySelector(location.hash);",
        "<script>const target=location.hash ? document.querySelector(location.hash) : null;",
    )
    (destination / "index.html").write_text(page, encoding="utf-8")
    (destination / "pending.html").write_text(_pending_page(pending_items), encoding="utf-8")
    (destination / "lotteries.json").write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
