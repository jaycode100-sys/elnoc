"""Data model — section 8. No table may hold device credentials (sec 12)."""
from __future__ import annotations
from datetime import datetime
from sqlalchemy import (
    String, Integer, Text, DateTime, ForeignKey, Float, Boolean, UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .database import Base
from .utils_time import utcnow

def _utc_default():
    return utcnow()

class Customer(Base):
    __tablename__ = "customer"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    aliases: Mapped[str] = mapped_column(Text, default="")
    tier: Mapped[str] = mapped_column(String(50), default="standard")
    notes: Mapped[str] = mapped_column(Text, default="")
    sources: Mapped[str] = mapped_column(String(200), default="PRTG")  # csv: PRTG,ZABBIX,SMARTOLT,PHOENIX
    links: Mapped[list["Link"]] = relationship(back_populates="customer")

class Contact(Base):
    __tablename__ = "contact"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(200), default="")
    team: Mapped[str] = mapped_column(String(200), default="")
    phone: Mapped[str] = mapped_column(String(50), default="")
    email: Mapped[str] = mapped_column(String(200), default="")
    whatsapp_number: Mapped[str] = mapped_column(String(50), default="")
    preferred_channels: Mapped[str] = mapped_column(String(100), default="email,whatsapp")
    availability_hours: Mapped[str] = mapped_column(String(100), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

class Link(Base):
    __tablename__ = "link"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customer.id"))
    name: Mapped[str] = mapped_column(String(200), unique=True)
    circuit_id: Mapped[str] = mapped_column(String(200), default="")
    a_end: Mapped[str] = mapped_column(String(200), default="")
    b_end: Mapped[str] = mapped_column(String(200), default="")
    medium: Mapped[str] = mapped_column(String(100), default="fibre")
    responsible_team: Mapped[str] = mapped_column(String(200), default="")
    aliases: Mapped[str] = mapped_column(Text, default="")
    primary_contact_id: Mapped[int | None] = mapped_column(ForeignKey("contact.id"), nullable=True)
    tier: Mapped[str] = mapped_column(String(50), default="access")  # core|distribution|access|edge
    sources: Mapped[str] = mapped_column(String(200), default="PRTG")
    standing_watcher_id: Mapped[int | None] = mapped_column(ForeignKey("contact.id"), nullable=True)
    optic_a: Mapped[str] = mapped_column(String(200), default="")  # FR-74 optic model per end
    optic_b: Mapped[str] = mapped_column(String(200), default="")
    customer: Mapped["Customer"] = relationship(back_populates="links")

class EscalationRule(Base):
    __tablename__ = "escalation_rule"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    link_id: Mapped[int | None] = mapped_column(ForeignKey("link.id"), nullable=True)
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customer.id"), nullable=True)
    step_order: Mapped[int] = mapped_column(Integer, default=1)
    contact_id: Mapped[int] = mapped_column(ForeignKey("contact.id"))
    wait_minutes: Mapped[int] = mapped_column(Integer, default=15)
    channels: Mapped[str] = mapped_column(String(100), default="email,whatsapp")

class SiteDevice(Base):
    __tablename__ = "site_device"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    hostname: Mapped[str] = mapped_column(String(200), unique=True)
    ip: Mapped[str] = mapped_column(String(100), default="")
    site: Mapped[str] = mapped_column(String(200), default="")
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    criticality_tier: Mapped[str] = mapped_column(String(50), default="access")
    link_id: Mapped[int | None] = mapped_column(ForeignKey("link.id"), nullable=True)
    monitored_in: Mapped[str] = mapped_column(String(200), default="PRTG")

class Case(Base):
    __tablename__ = "case_tbl"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_default)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    engineer: Mapped[str] = mapped_column(String(200), default="")
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customer.id"), nullable=True)
    link_id: Mapped[int | None] = mapped_column(ForeignKey("link.id"), nullable=True)
    device: Mapped[str] = mapped_column(String(300), default="")
    phoenix_ticket_no: Mapped[str] = mapped_column(String(100), default="")
    symptom: Mapped[str] = mapped_column(Text, default="")
    checks_done: Mapped[str] = mapped_column(Text, default="")
    root_cause_category: Mapped[str] = mapped_column(String(200), default="")
    root_cause_detail: Mapped[str] = mapped_column(Text, default="")
    fix: Mapped[str] = mapped_column(Text, default="")
    helped_by: Mapped[str] = mapped_column(String(300), default="")
    escalated_to: Mapped[str] = mapped_column(String(300), default="")
    time_to_resolve_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    first_thing_to_check_next_time: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(50), default="open")  # open|escalated|waiting_other_team|resolved
    confirmed_by: Mapped[str] = mapped_column(String(200), default="")
    severity: Mapped[str] = mapped_column(String(20), default="major")
    opened_by: Mapped[str] = mapped_column(String(20), default="manual")  # auto|manual
    acknowledged_by: Mapped[str] = mapped_column(String(200), default="")
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    outage_location: Mapped[str] = mapped_column(String(300), default="")
    outage_note: Mapped[str] = mapped_column(Text, default="")
    link_state: Mapped[str] = mapped_column(String(20), default="down")  # down|degraded|unstable|up (FR-45)
    waiting_on: Mapped[str] = mapped_column(String(300), default="")
    escalation_level: Mapped[str] = mapped_column(String(20), default="")  # L1|L2|L3|Vendor
    # Phoenix ticket trail. Shown in the app ONLY — never in handover text.
    phoenix_ticket_opened_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    # When the link was confirmed restored — powers the handover's
    # "current update on link restoration" block.
    restored_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    # Resolution-evidence challenge (MCQ): set UP -> ELNOC asks for proof.
    resolution_challenged_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    last_contact_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    outage_start: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)  # when the fault itself began
    current_escalation_step: Mapped[int] = mapped_column(Integer, default=0)
    last_escalation_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

class CaseLink(Base):
    __tablename__ = "case_link"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("case_tbl.id"))
    link_id: Mapped[int] = mapped_column(ForeignKey("link.id"))

class CaseEvent(Base):
    __tablename__ = "case_event"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("case_tbl.id"))
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_default)
    engineer: Mapped[str] = mapped_column(String(200), default="")
    kind: Mapped[str] = mapped_column(String(50), default="note")  # note|status|escalation|notification|system|ai
    text: Mapped[str] = mapped_column(Text, default="")

class Event(Base):
    __tablename__ = "event"
    key: Mapped[str] = mapped_column(String(300), primary_key=True)  # stable fingerprint
    type: Mapped[str] = mapped_column(String(100), default="down")  # down|up|problem|mail|pon|onu
    source: Mapped[str] = mapped_column(String(50), default="PRTG")
    device: Mapped[str] = mapped_column(String(300), default="")
    summary: Mapped[str] = mapped_column(String(500), default="")
    severity: Mapped[str] = mapped_column(String(20), default="major")
    ref: Mapped[str] = mapped_column(String(300), default="")
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_default)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_default)
    case_id: Mapped[int | None] = mapped_column(ForeignKey("case_tbl.id"), nullable=True)
    link_id: Mapped[int | None] = mapped_column(ForeignKey("link.id"), nullable=True)
    raw: Mapped[str] = mapped_column(Text, default="")

class Notification(Base):
    __tablename__ = "notification"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("case_tbl.id"))
    event_key: Mapped[str] = mapped_column(String(300), default="")
    contact_id: Mapped[int | None] = mapped_column(ForeignKey("contact.id"), nullable=True)
    channel: Mapped[str] = mapped_column(String(20), default="email")
    status: Mapped[str] = mapped_column(String(20), default="queued")  # queued|sent|failed
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ack_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str] = mapped_column(Text, default="")
    ack_token: Mapped[str] = mapped_column(String(100), default="", unique=True)

class CaseWatcher(Base):
    __tablename__ = "case_watcher"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("case_tbl.id"))
    contact_id: Mapped[int] = mapped_column(ForeignKey("contact.id"))
    added_by: Mapped[str] = mapped_column(String(200), default="")
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_default)
    __table_args__ = (UniqueConstraint("case_id", "contact_id", name="uq_watcher"),)

class Attachment(Base):
    """Evidence. Attachments form a THREAD per case (MCQ: uploads kept as a
    thread), so the story of a fault reads top-to-bottom: location -> trace ->
    interface -> device -> sensor -> resolution proof."""
    __tablename__ = "attachment"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("case_tbl.id"))
    filename: Mapped[str] = mapped_column(String(300))
    stored_path: Mapped[str] = mapped_column(String(500))
    sha256: Mapped[str] = mapped_column(String(100), default="")
    uploaded_by: Mapped[str] = mapped_column(String(200), default="")
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_default)
    note: Mapped[str] = mapped_column(Text, default="")
    thread_seq: Mapped[int] = mapped_column(Integer, default=1)
    reply_to_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    evidence_kind: Mapped[str] = mapped_column(String(30), default="other")
    is_resolution_evidence: Mapped[bool] = mapped_column(Boolean, default=False)

class MaintenanceWindow(Base):
    __tablename__ = "maintenance_window"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    target_type: Mapped[str] = mapped_column(String(20), default="device")  # device|link
    target: Mapped[str] = mapped_column(String(300))
    start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    reason: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[str] = mapped_column(String(200), default="")

class AppUser(Base):
    __tablename__ = "app_user"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(100), unique=True)
    name: Mapped[str] = mapped_column(String(200), default="")
    role: Mapped[str] = mapped_column(String(50), default="engineer")  # engineer|senior|manager|admin
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    password_hash: Mapped[str] = mapped_column(String(200))
    password_salt: Mapped[str] = mapped_column(String(100))

class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    entity: Mapped[str] = mapped_column(String(100))
    entity_id: Mapped[str] = mapped_column(String(100))
    version: Mapped[int] = mapped_column(Integer, default=1)
    changed_by: Mapped[str] = mapped_column(String(200), default="")
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_default)
    diff: Mapped[str] = mapped_column(Text, default="")

class Handover(Base):
    __tablename__ = "handover"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    shift_date: Mapped[str] = mapped_column(String(20))  # DD/MM/YYYY Lagos
    shift: Mapped[str] = mapped_column(String(20), default="day")
    from_engineer: Mapped[str] = mapped_column(String(200), default="")
    to_engineer: Mapped[str] = mapped_column(String(200), default="")
    open_case_ids: Mapped[str] = mapped_column(Text, default="[]")
    free_notes: Mapped[str] = mapped_column(Text, default="")
    acknowledged_by: Mapped[str] = mapped_column(String(200), default="")
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_default)

class Playbook(Base):
    __tablename__ = "playbook"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(300))
    trigger_category: Mapped[str] = mapped_column(String(200), default="")
    steps: Mapped[str] = mapped_column(Text, default="")
    owner: Mapped[str] = mapped_column(String(200), default="")
    who_to_call: Mapped[str] = mapped_column(String(300), default="")
    when_to_escalate: Mapped[str] = mapped_column(String(300), default="")
    last_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_default)

class AliasLearned(Base):
    __tablename__ = "alias_learned"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    typed_text: Mapped[str] = mapped_column(String(200))
    entity_type: Mapped[str] = mapped_column(String(20))  # link|customer
    entity_id: Mapped[int] = mapped_column(Integer)
    count: Mapped[int] = mapped_column(Integer, default=1)
    __table_args__ = (UniqueConstraint("typed_text", "entity_type", "entity_id", name="uq_alias"),)

class OpticalReading(Base):
    __tablename__ = "optical_reading"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    link_id: Mapped[int | None] = mapped_column(ForeignKey("link.id"), nullable=True)
    device: Mapped[str] = mapped_column(String(300), default="")
    rsl_dbm: Mapped[float | None] = mapped_column(Float, nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_default)
    source: Mapped[str] = mapped_column(String(50), default="PRTG")

class CollectorRun(Base):
    __tablename__ = "collector_run"
    source: Mapped[str] = mapped_column(String(50), primary_key=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_ok: Mapped[bool] = mapped_column(Boolean, default=True)
    last_error: Mapped[str] = mapped_column(Text, default="")

class AgentLog(Base):
    __tablename__ = "agent_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    asked_by: Mapped[str] = mapped_column(String(200), default="")
    question: Mapped[str] = mapped_column(Text, default="")
    tools_used: Mapped[str] = mapped_column(Text, default="")
    answer: Mapped[str] = mapped_column(Text, default="")
    sources: Mapped[str] = mapped_column(Text, default="")
    confidence: Mapped[str] = mapped_column(String(20), default="medium")
    feedback: Mapped[str] = mapped_column(String(20), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_default)

ROOT_CAUSE_CATEGORIES = [
    "far-end not transmitting",
    "fibre cut",
    "power",
    "transceiver or optics",
    "config",
    "third-party or ISP",
    "planned maintenance",
    "unknown",
]

# Escalation levels (team-agreed meanings): L1 first-line checks, L2 advanced
# technical, L3 senior/network-specialist, Vendor separate third-party path.
ESCALATION_LEVELS = {
    "L1": "Level 1 Support — first-line: initial checks, link status, ping tests, ticket logging.",
    "L2": "Level 2 Support — advanced technical: VLAN/interface checks, MAC learning, routing, packet loss, config.",
    "L3": "Level 3 Support — senior/network specialists: core equipment, routing protocols, major outages.",
    "Vendor": "External provider path — third-party fibre/equipment/expertise (separate path, not above L3).",
}

# Short forms used in the handover text (MCQ Q15=C: "L2 (advanced technical)").
ESCALATION_LEVELS_SHORT = {
    "L1": "first-line", "L2": "advanced technical",
    "L3": "senior", "Vendor": "third-party",
}

# Evidence kinds for the media thread (kind, human label) — the categories the
# team said every update should be able to attach.
EVIDENCE_KINDS = {
    "location": "Physical location (site photo, cabinet, GPS)",
    "trace": "Fibre trace (OTDR .sor, splice/connector shots)",
    "interface": "Interface status (physical port, light levels)",
    "smartolt": "SmartOLT device (ONU/OLT screen, port state)",
    "prtg": "PRTG sensor (graph, channel, utilisation)",
    "resolution": "Resolution proof (utilisation graph, interface pic, learn-MAC)",
    "other": "Other evidence",
}


def level_label(level: str) -> str:
    """'L2' -> 'L2 (advanced technical)'; '' -> ''."""
    if not level:
        return ""
    short = ESCALATION_LEVELS_SHORT.get(level)
    return f"{level} ({short})" if short else level

class HandoverImport(Base):
    """A pasted WhatsApp handover kept for audit + day-over-day update diffing."""
    __tablename__ = "handover_import"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_default)
    imported_by: Mapped[str] = mapped_column(String(200), default="")
    shift_date: Mapped[str] = mapped_column(String(20), default="")
    raw_text: Mapped[str] = mapped_column(Text, default="")
    entries_json: Mapped[str] = mapped_column(Text, default="[]")
    applied: Mapped[bool] = mapped_column(Boolean, default=False)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
