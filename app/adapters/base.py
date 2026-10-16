"""Normalized Event record — every adapter returns these (sec 9)."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from ..utils_time import utcnow

@dataclass
class RawEvent:
    source: str       # PRTG|ZABBIX|SMARTOLT|MAILBOX|PHOENIX
    etype: str        # down|up|problem|mail|pon|onu
    device: str
    summary: str
    severity: str     # critical|major|minor|info
    occurred_at: datetime
    ref: str = ""
    raw: str = ""
    rsl_dbm: float | None = None  # FR-82 optical reading if present
    key_extra: str = ""  # extra fingerprint entropy (mailbox: subject)

    def __post_init__(self):
        if self.occurred_at is None:
            self.occurred_at = utcnow()
