"""Pydantic schemas for request/response validation.

Replaces ad-hoc `payload: dict` parsing with explicit schemas, so every
endpoint validates its input and documents its output.
"""
from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------- Shift notes

class ShiftNoteCreate(BaseModel):
    shift_date: str = Field(..., description="YYYY-MM-DD Lagos date")
    shift: str = Field(default="day", pattern="^(day|night)$")
    notes: str = Field(default="")
    extra_info: str = Field(default="")
    power_status: str = Field(default="")
    source: str = Field(default="manual", pattern="^(manual|whatsapp|pane)$")
    case_id: int | None = Field(default=None, ge=0)

    @field_validator("shift_date")
    @classmethod
    def _validate_date(cls, v: str) -> str:
        # Accept YYYY-MM-DD (ISO) — the canonical internal format
        from datetime import date
        date.fromisoformat(v)
        return v


class ShiftNoteUpdate(BaseModel):
    notes: str | None = None
    extra_info: str | None = None
    power_status: str | None = None


class ShiftNoteOut(BaseModel):
    id: int
    engineer: str
    shift_date: str
    shift: str
    notes: str
    extra_info: str
    power_status: str
    source: str
    case_id: int | None
    created_at: datetime
    updated_at: datetime | None


# ---------------------------------------------------------------- Shift close

class ShiftCloseRequest(BaseModel):
    nothing_to_report: bool = Field(default=False)
    override_reason: str | None = Field(default=None, max_length=500)


class ShiftCloseOut(BaseModel):
    id: int
    engineer: str
    shift_date: str
    shift: str
    closed_at: datetime
    power_report_id: int | None
    nothing_to_report: bool


# ---------------------------------------------------------------- WhatsApp paste

class WhatsAppPasteRequest(BaseModel):
    raw_text: str
    shift_date: str

    @field_validator("shift_date")
    @classmethod
    def _validate_date(cls, v: str) -> str:
        from datetime import date
        date.fromisoformat(v)
        return v


# ---------------------------------------------------------------- Power report

class PowerReportCreate(BaseModel):
    activity: str
    event_time: str | None = None
    battery_level: str | None = None
    source: str = Field(default="manual")
    report_date: str

    @field_validator("report_date")
    @classmethod
    def _validate_date(cls, v: str) -> str:
        from datetime import date
        date.fromisoformat(v)
        return v
