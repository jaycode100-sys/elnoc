"""Central configuration. All secrets come from .env, never from code."""
from __future__ import annotations
import os, sys


def _res(p):
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, p)
    return os.path.abspath(p)
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default

class Settings:
    DB_PATH: str = os.getenv("ELNOC_DB_PATH") or _res("data/elnoc.db")
    BACKUP_DIR: str = os.getenv("ELNOC_BACKUP_DIR") or _res("backups")
    SECRET_KEY: str = os.getenv("ELNOC_SECRET_KEY", "dev-only-change-me-please-0123456789")
    SESSION_HOURS: int = _int("ELNOC_SESSION_HOURS", 12)
    BASE_URL: str = os.getenv("ELNOC_BASE_URL", "http://localhost:8000")
    TZ_NAME: str = os.getenv("ELNOC_TZ", "Africa/Lagos")

    # Hosting tiers (HOSTING.md). DATABASE_URL is read in database.py.
    SUPABASE_URL: str = os.getenv("SUPABASE_URL", "")
    SUPABASE_SERVICE_KEY: str = os.getenv("SUPABASE_SERVICE_KEY", "")
    SUPABASE_BACKUP_BUCKET: str = os.getenv("SUPABASE_BACKUP_BUCKET", "elnoc-backups")

    # AI assistant — official provider APIs. Either one is enough; Anthropic
    # wins if both are set. LLM_API_KEY is kept as the legacy OpenAI name.
    LLM_API_KEY: str = os.getenv("OPENAI_API_KEY", "") or os.getenv("LLM_API_KEY", "")
    LLM_MODEL: str = os.getenv("LLM_MODEL", "")
    ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
    ANTHROPIC_MODEL: str = os.getenv("ANTHROPIC_MODEL", "")
    # Cap the assistant so a curious loop cannot burn the monthly credit.
    ASSISTANT_DAILY_CAP: int = _int("ASSISTANT_DAILY_CAP", 200)
    # How many prior turns to resend as context.
    ASSISTANT_HISTORY_TURNS: int = _int("ASSISTANT_HISTORY_TURNS", 8)

    ESC_STEP_WAIT_MIN: int = _int("ESC_STEP_WAIT_MIN", 15)
    MAJOR_DIGEST_HOURS: int = _int("MAJOR_DIGEST_HOURS", 4)
    STALE_WAIT_MIN: int = _int("STALE_WAIT_MIN", 120)
    MTTR_BREACH_MIN: int = _int("MTTR_BREACH_MIN", 240)
    CORRELATION_WINDOW_MIN: int = _int("CORRELATION_WINDOW_MIN", 30)

    # Update-staleness watcher: question an unchanged UPDATE after 12h,
    # call it a repeat after 48h (team rule: same update 2 days = question).
    STALE_UPDATE_HOURS: int = _int("STALE_UPDATE_HOURS", 12)
    REPEAT_UPDATE_HOURS: int = _int("REPEAT_UPDATE_HOURS", 48)

    PRTG_BASE_URL: str = os.getenv("PRTG_BASE_URL", "")
    PRTG_USERNAME: str = os.getenv("PRTG_USERNAME", "")
    PRTG_PASSHASH: str = os.getenv("PRTG_PASSHASH", "")
    ZABBIX_BASE_URL: str = os.getenv("ZABBIX_BASE_URL", "")
    ZABBIX_API_TOKEN: str = os.getenv("ZABBIX_API_TOKEN", "")
    # Pre-5.4 servers have no API tokens: user.login fallback instead.
    ZABBIX_USER: str = os.getenv("ZABBIX_USER", "")
    ZABBIX_PASSWORD: str = os.getenv("ZABBIX_PASSWORD", "")
    # Full base, including your tenant: https://<subdomain>.smartolt.com
    SMARTOLT_BASE_URL: str = os.getenv("SMARTOLT_BASE_URL", "")
    # Sent as the X-Token header (not Bearer). SmartOLT > General > API key.
    SMARTOLT_API_KEY: str = os.getenv("SMARTOLT_API_KEY", "")
    # Incremental window for get_onus_statuses; blank = full scan.
    SMARTOLT_STATUS_SINCE: str = os.getenv("SMARTOLT_STATUS_SINCE", "")
    # 0 (default) = per-zone roll-up only. 1 = one ticket per offline ONU.
    # Leave at 0 unless you genuinely want a ticket for every single ONU.
    SMARTOLT_ONU_ALERTS: str = os.getenv("SMARTOLT_ONU_ALERTS", "0")
    # Hard ceiling on events per collector run, so one bad poll cannot bury the NOC.
    SMARTOLT_MAX_EVENTS: int = int(os.getenv("SMARTOLT_MAX_EVENTS", "200") or 200)

    MAIL_IMAP_HOST: str = os.getenv("MAIL_IMAP_HOST", "")
    MAIL_IMAP_USER: str = os.getenv("MAIL_IMAP_USER", "")
    MAIL_IMAP_PASS: str = os.getenv("MAIL_IMAP_PASS", "")
    MAIL_KEYWORDS: str = os.getenv("MAIL_KEYWORDS", "downtime,outage,link down,fibre cut")

    SMTP_HOST: str = os.getenv("SMTP_HOST", "")
    SMTP_PORT: int = _int("SMTP_PORT", 587)
    SMTP_USER: str = os.getenv("SMTP_USER", "")
    SMTP_PASS: str = os.getenv("SMTP_PASS", "")
    SMTP_FROM: str = os.getenv("SMTP_FROM", "noc@company.local")
    WHATSAPP_TOKEN: str = os.getenv("WHATSAPP_TOKEN", "")
    WHATSAPP_PHONE_NUMBER_ID: str = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")
    SMS_API_KEY: str = os.getenv("SMS_API_KEY", "")

settings = Settings()
