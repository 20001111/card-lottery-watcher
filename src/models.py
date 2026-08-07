from dataclasses import asdict, dataclass, field
import hashlib
from typing import Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


def lottery_identity(store: str, title: str, application_url: str, deadline: Optional[str] = None) -> str:
    """Produce a stable ID across reposts and tracking-link variants."""
    parsed = urlsplit(application_url)
    query = urlencode(sorted((key, value) for key, value in parse_qsl(parsed.query) if not key.lower().startswith(("utm_", "fbclid", "gclid"))))
    canonical_url = urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path.rstrip("/"), query, ""))
    text = "|".join((" ".join(store.lower().split()), " ".join(title.lower().split()), canonical_url, (deadline or "")[:10]))
    return hashlib.sha256(text.encode()).hexdigest()[:20]


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

    def to_dict(self):
        return asdict(self)
