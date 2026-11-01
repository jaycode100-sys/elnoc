"""Evidence thread (media kept as a conversation, per the team's request).

Uploads are optional but advised, and ordered: location -> trace -> interface
-> SmartOLT device -> PRTG sensor -> resolution proof. Each upload can reply to
an earlier one, so the thread reads like the fault story.

When a link is set UP, ELNOC CHALLENGES the engineer for resolution evidence
(PRTG utilisation graph, ONU utilisation, interface picture, learn-MAC...) and
the case stays flagged until something lands.
"""
from __future__ import annotations
import hashlib, os
from pathlib import Path
from fastapi import APIRouter, Depends, Request, Form, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import Case, CaseEvent, Attachment, EVIDENCE_KINDS
from ..security import get_current_user
from ..utils_time import utcnow

router = APIRouter()
EVIDENCE_DIR = Path("evidence")
EVIDENCE_DIR.mkdir(exist_ok=True)

MAX_BYTES = 15 * 1024 * 1024

# Allowed evidence file extensions — images, PDFs, text logs only
ALLOWED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".pdf", ".txt", ".csv", ".sor"}

RESOLUTION_PROMPTS = [
    "PRTG utilisation graph for the recovered window",
    "ONU / SmartOLT utilisation after restoration",
    "Physical interface picture (port up, light levels)",
    "Learn-MAC table showing the link is passing traffic",
]


def thread_rows(db: Session, case_id: int) -> list[Attachment]:
    return db.query(Attachment).filter(Attachment.case_id == case_id)\
        .order_by(Attachment.thread_seq, Attachment.id).all()


def next_seq(db: Session, case_id: int) -> int:
    row = db.query(Attachment).filter(Attachment.case_id == case_id)\
        .order_by(Attachment.thread_seq.desc()).first()
    return (row.thread_seq + 1) if row else 1


def has_resolution_evidence(db: Session, case_id: int) -> bool:
    return db.query(Attachment).filter(
        Attachment.case_id == case_id,
        Attachment.is_resolution_evidence == True).count() > 0  # noqa: E712


def outstanding_challenge(db: Session, case_id: int) -> dict | None:
    """UP (or resolved) but no resolution proof yet -> challenge."""
    case = db.get(Case, case_id)
    if not case:
        return None
    up = (case.link_state or "").lower() == "up" or case.status == "resolved"
    if not up:
        return None
    if has_resolution_evidence(db, case_id):
        return None
    return {"case_id": case_id,
            "message": "Link is UP — add proof it really is. PRTG graph, ONU "
                       "utilisation, interface picture or learn-MAC.",
            "accepted": RESOLUTION_PROMPTS}


@router.get("/api/case/{case_id}/evidence")
def list_evidence(case_id: int, db: Session = Depends(get_db),
                  user=Depends(get_current_user)):
    rows = thread_rows(db, case_id)
    return JSONResponse({
        "kinds": EVIDENCE_KINDS,
        "challenge": outstanding_challenge(db, case_id),
        "items": [{"id": r.id, "seq": r.thread_seq, "reply_to": r.reply_to_id,
                   "kind": r.evidence_kind, "kind_label": EVIDENCE_KINDS.get(
                       r.evidence_kind, r.evidence_kind),
                   "filename": r.filename, "by": r.uploaded_by,
                   "at": r.uploaded_at.isoformat() if r.uploaded_at else None,
                   "note": r.note, "resolution": bool(r.is_resolution_evidence)}
                  for r in rows],
    })


@router.post("/cases/{case_id}/evidence")
async def add_evidence(case_id: int, request: Request,
                       file: UploadFile = File(None), note: str = Form(""),
                       evidence_kind: str = Form("other"),
                       reply_to_id: str = Form(""), resolution: str = Form(""),
                       user=Depends(get_current_user), db: Session = Depends(get_db)):
    case = db.get(Case, case_id)
    if evidence_kind not in EVIDENCE_KINDS:
        evidence_kind = "other"
    if file is None or not (file.filename or "").strip():
        return RedirectResponse(url=f"/cases/{case_id}", status_code=303)
    data = await file.read()
    if len(data) > MAX_BYTES:
        return HTMLResponse("Evidence file too large (15 MB max).", status_code=400)
    # Extension allowlist
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        return HTMLResponse(
            f"File type '{ext}' not allowed. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
            status_code=400,
        )
    digest = hashlib.sha256(data).hexdigest()
    safe = "".join(c for c in (file.filename or "evidence")
                   if c.isalnum() or c in "._-")[:120] or "evidence"
    dest = EVIDENCE_DIR / f"case{case_id}-{digest[:12]}-{safe}"
    dest.write_bytes(data)
    seq = next_seq(db, case_id)
    att = Attachment(
        case_id=case_id, filename=file.filename or safe, stored_path=str(dest),
        sha256=digest, uploaded_by=user.username, uploaded_at=utcnow(),
        note=note[:800], thread_seq=seq,
        reply_to_id=int(reply_to_id) if reply_to_id.strip().isdigit() else None,
        evidence_kind=evidence_kind, is_resolution_evidence=bool(resolution))
    db.add(att)
    db.add(CaseEvent(
        case_id=case_id, at=utcnow(), engineer=user.username, kind="note",
        text=f"Evidence #{seq} [{EVIDENCE_KINDS[evidence_kind]}] "
             f"{file.filename}{' (resolution proof)' if resolution else ''}"
             + (f" — {note[:200]}" if note else "")))
    db.commit()
    return RedirectResponse(url=f"/cases/{case_id}", status_code=303)


@router.post("/cases/{case_id}/evidence/{att_id}/delete")
def delete_evidence(case_id: int, att_id: int, user=Depends(get_current_user),
                    db: Session = Depends(get_db)):
    att = db.get(Attachment, att_id)
    if att and att.case_id == case_id and user.role in ("senior", "admin"):
        # Remove the physical file too
        try:
            p = Path(att.stored_path)
            if p.exists():
                p.unlink()
        except OSError:
            pass
        db.delete(att)
        db.commit()
    return RedirectResponse(url=f"/cases/{case_id}", status_code=303)


@router.post("/cases/{case_id}/challenge-resolution")
def challenge_resolution(case_id: int, user=Depends(get_current_user),
                         db: Session = Depends(get_db)):
    """Ask again for proof the link is really restored (idempotent stamp)."""
    case = db.get(Case, case_id)
    case.resolution_challenged_at = utcnow()
    db.add(CaseEvent(case_id=case_id, at=utcnow(), engineer=user.username,
                     kind="system",
                     text="Resolution evidence requested: PRTG graph / ONU "
                          "utilisation / interface picture / learn-MAC."))
    db.commit()
    return RedirectResponse(url=f"/cases/{case_id}", status_code=303)