from dataclasses import asdict, dataclass, field
import hashlib
from typing import Iterable, Optional
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
    application_method: str = "unknown"
    receipt_method: str = "unknown"
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


def deduplicate_lotteries(items: Iterable[Lottery]) -> list[Lottery]:
    """Merge source variations so one application URL is shown once."""
    groups: dict[str, list[Lottery]] = {}
    for item in items:
        key = canonical_application_url(item.application_url) or f"missing:{item.id}"
        groups.setdefault(key, []).append(item)

    merged: list[Lottery] = []
    for group in groups.values():
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
        merged.append(
            Lottery(
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
                application_method=_first_value(ranked, "application_method"),
                receipt_method=_first_value(ranked, "receipt_method"),
                status=best.status,
                discord_message_id=message_ids[0] if message_ids else None,
                first_seen_at=min(first_seen) if first_seen else None,
                start_notified_at=min(start_notified) if start_notified else None,
            )
        )
    return merged
