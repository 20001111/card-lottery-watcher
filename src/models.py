from dataclasses import asdict, dataclass, field
from difflib import SequenceMatcher
import hashlib
import re
from typing import Iterable, Optional
import unicodedata
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


def canonical_application_url(application_url: str) -> str:
    """Normalize an application URL without losing meaningful query values."""
    parsed = urlsplit(application_url)
    query = urlencode(
        sorted(
            (key, value)
            for key, value in parse_qsl(parsed.query, keep_blank_values=True)
            if not key.lower().startswith(("utm_", "fbclid", "gclid"))
        )
    )
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path.rstrip("/"), query, ""))


def lottery_identity(store: str, title: str, application_url: str, deadline: Optional[str] = None) -> str:
    """Produce one stable ID for one application page.

    Store names, AI titles and deadline formatting can change between sources.
    They must not turn the same application page into a duplicate listing.
    """
    return hashlib.sha256(canonical_application_url(application_url).encode()).hexdigest()[:20]


def notification_identity(store: str, title: str, application_url: str) -> str:
    """Stable identity used only to prevent repeat Discord notifications.

    A deadline correction must update the website without looking like a new
    lottery announcement.
    """
    return lottery_identity(store, title, application_url)


@dataclass
class Lottery:
    id: str
    title: str
    category: str
    store: str
    store_key: str
    source_url: str
    application_url: str
    deadline: Optional[str] = None
    start_at: Optional[str] = None
    conditions: list[str] = field(default_factory=list)
    source_kind: str = "discovery"
    official_confirmed: bool = False
    eligibility: str = "unknown"
    eligibility_reasons: list[str] = field(default_factory=list)
    status: str = "open"
    discord_message_id: Optional[str] = None
    # Kept in state so the Website can show NEW for a full day, rather than
    # only for the single collection run where the lottery was found.
    first_seen_at: Optional[str] = None
    # A future lottery is announced once more when its application period
    # actually begins.  Stored state prevents the 09:00 digest repeating it.
    start_notified_at: Optional[str] = None

    def to_dict(self):
        return asdict(self)


def _quality(item: Lottery) -> tuple[int, int, int, int, int]:
    """Prefer verified and information-rich versions of the same lottery."""
    return (
        int(item.official_confirmed),
        int(item.source_kind == "official"),
        int(bool(item.start_at and item.deadline)),
        len(" ".join(item.conditions)),
        len(item.title),
    )


def _first_value(items: list[Lottery], field_name: str, unknown: str = "unknown"):
    for item in sorted(items, key=_quality, reverse=True):
        value = getattr(item, field_name)
        if value and value != unknown:
            return value
    return getattr(max(items, key=_quality), field_name)


def _comparison_text(value: str) -> str:
    """Make harmless title variations comparable without translating content."""
    text = unicodedata.normalize("NFKC", value or "").lower()
    # The same ONE PIECE lottery is often written once in English and once in
    # Japanese by separate sources.
    text = re.sub(r"one\s*piece", "ワンピース", text)
    return re.sub(r"[\s\W_]+", "", text)


def _same_semantic_lottery(left: Lottery, right: Lottery) -> bool:
    """Recognise the same listing when sources provide different entry URLs.

    URL equality is the strongest signal.  This fallback is deliberately
    conservative: it requires the same store, card category, and *both*
    timestamps before accepting a near-identical title.
    """
    if not (left.start_at and left.deadline and right.start_at and right.deadline):
        return False
    if (
        _comparison_text(left.store) != _comparison_text(right.store)
        or left.category != right.category
        or left.start_at != right.start_at
        or left.deadline != right.deadline
    ):
        return False
    # Sources often append the store name in parentheses to the title.  The
    # store is already compared above, so it must not prevent a merge.
    left_title = _comparison_text(left.title).replace(_comparison_text(left.store), "")
    right_title = _comparison_text(right.title).replace(_comparison_text(right.store), "")
    return SequenceMatcher(None, left_title, right_title).ratio() >= 0.88


def _merge_group(group: list[Lottery]) -> Lottery:
    """Keep the richest record while retaining fields gathered by other sources."""
    ranked = sorted(group, key=_quality, reverse=True)
    best = ranked[0]
    conditions: list[str] = []
    for item in ranked:
        for condition in item.conditions:
            cleaned = " ".join(condition.split())
            if cleaned and cleaned not in conditions:
                conditions.append(cleaned)

    first_seen = [item.first_seen_at for item in group if item.first_seen_at]
    start_notified = [item.start_notified_at for item in group if item.start_notified_at]
    message_ids = [item.discord_message_id for item in ranked if item.discord_message_id]
    category = _first_value(ranked, "category")
    if category == "unknown":
        category = best.category
    return Lottery(
        id=lottery_identity(best.store, best.title, best.application_url, best.deadline),
        title=best.title,
        category=category,
        store=best.store,
        store_key=best.store_key,
        source_url=best.source_url,
        application_url=best.application_url,
        deadline=_first_value(ranked, "deadline", ""),
        start_at=_first_value(ranked, "start_at", ""),
        conditions=conditions,
        source_kind=best.source_kind,
        official_confirmed=any(item.official_confirmed for item in group),
        eligibility=best.eligibility,
        eligibility_reasons=best.eligibility_reasons,
        status=best.status,
        discord_message_id=message_ids[0] if message_ids else None,
        first_seen_at=min(first_seen) if first_seen else None,
        start_notified_at=min(start_notified) if start_notified else None,
    )


def deduplicate_lotteries(items: Iterable[Lottery]) -> list[Lottery]:
    """Merge duplicate URLs and conservative same-lottery source variations."""
    url_groups: dict[str, list[Lottery]] = {}
    for item in items:
        key = canonical_application_url(item.application_url) or f"missing:{item.id}"
        url_groups.setdefault(key, []).append(item)

    groups: list[list[Lottery]] = []
    for url_group in url_groups.values():
        representative = _merge_group(url_group)
        for group in groups:
            if _same_semantic_lottery(representative, _merge_group(group)):
                group.extend(url_group)
                break
        else:
            groups.append(list(url_group))
    return [_merge_group(group) for group in groups]
