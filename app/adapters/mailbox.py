"""Mailbox collector (FR-05). BODY.PEEK so mail is not marked read (gap #4)."""
from __future__ import annotations
import imaplib, email
from email.header import decode_header
from .base import RawEvent
from ..config import settings
from ..utils_time import utcnow

def _subject(s: str) -> bool:
    kws = [k.strip().lower() for k in settings.MAIL_KEYWORDS.split(",") if k.strip()]
    sub = (s or "").lower()
    return any(k in sub for k in kws)

def collect_mailbox(fetcher=None, mark_seen: bool = False) -> list[RawEvent]:
    if fetcher is not None:
        messages = fetcher()  # list of dicts {subject, from, date, body}
    else:
        if not settings.MAIL_IMAP_HOST:
            return []
        messages = []
        conn = imaplib.IMAP4_SSL(settings.MAIL_IMAP_HOST)
        try:
            conn.login(settings.MAIL_IMAP_USER, settings.MAIL_IMAP_PASS)
            conn.select("INBOX")
            typ, data = conn.search(None, "UNSEEN")
            for num in (data[0].split() if data and data[0] else []):
                typ, msg_data = conn.fetch(num, "(BODY.PEEK[])")  # PEEK: do not mark read
                raw = msg_data[0][1]
                m = email.message_from_bytes(raw)
                subj = str(m.get("Subject", ""))
                if not _subject(subj):
                    continue
                body = ""
                if m.is_multipart():
                    for part in m.walk():
                        if part.get_content_type() == "text/plain":
                            try:
                                body = part.get_payload(decode=True).decode(errors="ignore")[:2000]
                            except Exception:
                                pass
                            break
                else:
                    try:
                        body = m.get_payload(decode=True).decode(errors="ignore")[:2000]
                    except Exception:
                        body = str(m.get_payload())[:2000]
                messages.append({"subject": subj, "from": str(m.get("From", "")),
                                 "date": str(m.get("Date", "")), "body": body, "_num": num})
                # mark seen ONLY after event stored — caller does store then flags
        finally:
            try:
                conn.logout()
            except Exception:
                pass
    events = []
    for m in messages:
        if not _subject(m.get("subject", "")):
            continue
        events.append(RawEvent(
            source="MAILBOX", etype="mail",
            device=m.get("from", "")[:200],
            summary=f"Downtime mail: {m.get('subject','')[:300]}",
            severity="major", occurred_at=utcnow(),
            ref=m.get("subject", "")[:200], raw=m.get("body", "")[:2000],
            key_extra=m.get("subject", "")[:200]))  # same sender, 2 subjects, same day = 2 events
    return events
