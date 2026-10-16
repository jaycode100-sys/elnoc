"""Channel senders with independent failure (NFR-05). Each channel fails alone."""
from __future__ import annotations
import smtplib, json, urllib.request, urllib.parse
from email.message import EmailMessage
from ..config import settings

class ChannelResult:
    def __init__(self, ok: bool, error: str = ""):
        self.ok = ok
        self.error = error

def send_email(to: str, subject: str, body: str, dry_run: bool = False) -> ChannelResult:
    if dry_run or not settings.SMTP_HOST:
        return ChannelResult(True, "dry-run/no-smtp")
    try:
        msg = EmailMessage()
        msg["From"] = settings.SMTP_FROM
        msg["To"] = to
        msg["Subject"] = subject
        msg.set_content(body)
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=20) as s:
            s.starttls()
            if settings.SMTP_USER:
                s.login(settings.SMTP_USER, settings.SMTP_PASS)
            s.send_message(msg)
        return ChannelResult(True)
    except Exception as e:  # noqa: BLE001 — one channel must never block others
        return ChannelResult(False, str(e)[:500])

def send_whatsapp(to_number: str, body: str, template: str | None = None,
                  dry_run: bool = False) -> ChannelResult:
    """Meta Cloud API. Outside the 24h window only templates deliver (gap #7 kept in mind)."""
    if dry_run or not settings.WHATSAPP_TOKEN:
        return ChannelResult(True, "dry-run/no-token")
    try:
        url = f"https://graph.facebook.com/v21.0/{settings.WHATSAPP_PHONE_NUMBER_ID}/messages"
        if template:
            payload = {"messaging_product": "whatsapp", "to": to_number,
                       "type": "template",
                       "template": {"name": template, "language": {"code": "en"},
                                    "components": [{"type": "body",
                                                    "parameters": [{"type": "text", "text": body[:900]}]}]}}
        else:
            payload = {"messaging_product": "whatsapp", "to": to_number,
                       "type": "text", "text": {"body": body[:4000]}}
        req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                     headers={"Authorization": f"Bearer {settings.WHATSAPP_TOKEN}",
                                              "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=20) as r:
            r.read()
        return ChannelResult(True)
    except Exception as e:  # noqa: BLE001
        return ChannelResult(False, str(e)[:500])

def send_sms(to_number: str, body: str, dry_run: bool = False) -> ChannelResult:
    """Swappable provider interface (Termii-compatible shape); keep under ~300 chars."""
    body = body[:300]
    if dry_run or not settings.SMS_API_KEY:
        return ChannelResult(True, "dry-run/no-key")
    try:
        data = urllib.parse.urlencode({"to": to_number, "from": "NOC",
                                       "sms": body, "type": "plain",
                                       "api_key": settings.SMS_API_KEY}).encode()
        req = urllib.request.Request("https://v3.api.termii.com/api/sms/send", data=data)
        with urllib.request.urlopen(req, timeout=20) as r:
            r.read()
        return ChannelResult(True)
    except Exception as e:  # noqa: BLE001
        return ChannelResult(False, str(e)[:500])
