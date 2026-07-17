from dataclasses import asdict, dataclass, field
from typing import Optional


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

    def to_dict(self):
        return asdict(self)
