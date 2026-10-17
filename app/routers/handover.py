"""Handover (FR-40..FR-47): builder, on-screen ack, WhatsApp text, CSV, group-by-party."""
from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from pathlib import Path
import json, csv, io
from ..database import get_db
from ..models import Case, Link, Customer, Handover, CaseEvent, CaseLink, HandoverImport
from ..security import get_current_user, find_secret
from ..services.handover import build_handover_text, group_by_waiting_party
from ..services.handover_parse import parse_handover, extract_party
from ..services.update_watch import watch_updates, flag_text, normalize_update
from ..services.search import search_links
from ..utils_time import utcnow, fmt_date, ensure_utc
from ..services.escalation import is_stale_wait

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))

def _attach(db, cases):
    links = {l.id: l for l in db.query(Link).all()}
    for c in cases:
        l = links.get(c.link_id or 0)
        c._link_name = l.name if l else c.device or f"CASE-{c.id}"
        ev = db.query(CaseEvent).filter(CaseEvent.case_id == c.id)\
            .order_by(CaseEvent.at.desc()).first()
        c._latest_note = ev.text if ev else (c.symptom or "")
        aff = db.query(CaseLink).filter(CaseLink.case_id == c.id).all()
        c._affected = [links[a.link_id].name for a in aff if a.link_id in links]
    _attach_updates(db, cases)
    return cases

def _attach_updates(db, cases):
    """c._upd = {state, hours, runs, current} per the 12h/48h rule."""
    for c in cases:
        evs = db.query(CaseEvent).filter(CaseEvent.case_id == c.id).all()
        c._upd = watch_updates(c.symptom or "", c.opened_at, evs)
        c._upd_flag = flag_text(c._upd)
    return cases

def _stale_map(cases):
    return {c.id: c._upd_flag for c in cases if getattr(c, "_upd_flag", "")}

@router.get("/handover", response_class=HTMLResponse)
def handover_page(request: Request, user=Depends(get_current_user), db: Session = Depends(get_db)):
    cases = db.query(Case).filter(Case.status != "resolved").order_by(Case.opened_at).all()
    _attach(db, cases)
    groups = group_by_waiting_party(cases)
    handovers = db.query(Handover).order_by(Handover.id.desc()).limit(10).all()
    return templates.TemplateResponse(request, "handover.html", { "user": user, "cases": cases, "groups": groups,
         "handovers": handovers, "today": fmt_date(utcnow())})

@router.post("/handover")
def create_handover(request: Request, shift: str = Form("day"),
                    from_engineer: str = Form(""), free_notes: str = Form(""),
                    show_wait_age: str = Form(""), summary: str = Form(""),
                    to_engineer: str = Form(""), restored_hours: str = Form("12"),
                    user=Depends(get_current_user), db: Session = Depends(get_db)):
    cases = db.query(Case).filter(Case.status != "resolved").order_by(Case.opened_at).all()
    _attach(db, cases)
    # include this shift's closed too (FR-40)
    closed = db.query(Case).filter(Case.status == "resolved")\
        .order_by(Case.closed_at.desc()).limit(20).all()
    _attach(db, closed)
    all_cases = cases + [c for c in closed
                         if c.closed_at and (utcnow() - ensure_utc(c.closed_at)).days == 0]
    try:
        window = max(1, int(restored_hours or 12))
    except ValueError:
        window = 12
    text = build_handover_text(all_cases, fmt_date(utcnow()),
                               show_wait_age=bool(show_wait_age),
                               summary=bool(summary),
                               from_engineer=from_engineer or user.username,
                               to_engineer=to_engineer,
                               restored_hours=window)
    if free_notes.strip():
        text += f"\nNOTES\n{free_notes.strip()}\n"
    h = Handover(shift_date=fmt_date(utcnow()), shift=shift,
                 from_engineer=from_engineer or user.username,
                 to_engineer=to_engineer,
                 open_case_ids=json.dumps([c.id for c in cases]),
                 free_notes=free_notes)
    db.add(h); db.commit()
    # stash text on object for redirect page
    return RedirectResponse(url=f"/handover/{h.id}", status_code=303)

@router.get("/handover/{hid:int}", response_class=HTMLResponse)
def view_handover(hid: int, request: Request, user=Depends(get_current_user),
                  db: Session = Depends(get_db)):
    h = db.get(Handover, hid)
    ids = json.loads(h.open_case_ids or "[]")
    cases = [db.get(Case, i) for i in ids if db.get(Case, i)]
    cases = [c for c in cases if c]
    _attach(db, cases)
    qp = request.query_params
    stale = _stale_map(cases) if qp.get("stale") else {}
    text = build_handover_text(cases, h.shift_date, stale_map=stale,
                               resolved_notes=bool(qp.get("notes")),
                               summary=qp.get("summary", "1") != "0",
                               from_engineer=h.from_engineer or "",
                               to_engineer=h.to_engineer or "")
    if h.free_notes.strip():
        text += f"\nNOTES\n{h.free_notes.strip()}\n"
    questioned = [c for c in cases if getattr(c, "_upd_flag", "")]
    return templates.TemplateResponse(request, "handover_view.html", { "user": user, "h": h, "text": text, "cases": cases,
        "questioned": questioned, "stale_on": bool(qp.get("stale")), "notes_on": bool(qp.get("notes"))})

@router.get("/handover/{hid:int}/txt", response_class=PlainTextResponse)
def handover_txt(hid: int, request: Request, user=Depends(get_current_user), db: Session = Depends(get_db)):
    h = db.get(Handover, hid)
    ids = json.loads(h.open_case_ids or "[]")
    cases = [db.get(Case, i) for i in ids if db.get(Case, i)]
    cases = [c for c in cases if c]
    _attach(db, cases)
    qp = request.query_params
    stale = _stale_map(cases) if qp.get("stale") else {}
    text = build_handover_text(cases, h.shift_date, stale_map=stale,
                               resolved_notes=bool(qp.get("notes")),
                               summary=qp.get("summary", "1") != "0",
                               from_engineer=h.from_engineer or "",
                               to_engineer=h.to_engineer or "")
    if h.free_notes.strip():
        text += f"\nNOTES\n{h.free_notes.strip()}\n"
    return text

@router.post("/handover/{hid:int}/ack")
def ack_handover(hid: int, name: str = Form(""), user=Depends(get_current_user),
                 db: Session = Depends(get_db)):
    h = db.get(Handover, hid)
    h.acknowledged_by = name or user.username
    from ..utils_time import utcnow as _u
    h.acknowledged_at = _u()
    h.to_engineer = h.acknowledged_by
    db.commit()
    return RedirectResponse(url=f"/handover/{hid:int}", status_code=303)

@router.get("/handover/{hid:int}/csv")
def handover_csv(hid: int, user=Depends(get_current_user), db: Session = Depends(get_db)):
    from fastapi.responses import Response
    h = db.get(Handover, hid)
    ids = json.loads(h.open_case_ids or "[]")
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["case_id", "link", "link_state", "status", "waiting_on", "symptom"])
    for i in ids:
        c = db.get(Case, i)
        if not c:
            continue
        l = db.get(Link, c.link_id) if c.link_id else None
        w.writerow([c.id, l.name if l else c.device, c.link_state, c.status,
                    c.waiting_on, (c.symptom or "")[:200]])
    return Response(content=buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": f"attachment; filename=handover-{hid}.csv"})

# ---------------- WhatsApp import: paste -> match -> apply ----------------
def _match_link(db, name):
    """Registry match for a pasted link name: exact, else fuzzy >= 70."""
    q = (name or "").strip()
    if not q:
        return None, 0
    exact = db.query(Link).filter(Link.name.ilike(q)).first()
    if exact:
        return exact, 100.0
    res = search_links(db, q, limit=1)
    if res and res[0]["score"] >= 70:
        return db.get(Link, res[0]["link_id"]), res[0]["score"]
    return None, 0

def _open_case(db, link):
    if link is None:
        return None
    return db.query(Case).filter(Case.link_id == link.id,
                                 Case.status != "resolved")\
        .order_by(Case.opened_at.desc()).first()

def _preview_entries(db, parsed):
    rows = []
    for idx, e in enumerate(parsed["unresolved"] + parsed["resolved"]):
        link, score = _match_link(db, e["link"])
        case = _open_case(db, link)
        upd_norm = normalize_update(e["update"])
        cur_hours, cur_norm, flag = 0.0, "", ""
        if case is not None:
            evs = db.query(CaseEvent).filter(CaseEvent.case_id == case.id).all()
            w = watch_updates(case.symptom or "", case.opened_at, evs)
            cur_norm, cur_hours = w["current"], w["hours"]
            if upd_norm and upd_norm == cur_norm:
                flag = flag_text(w)
        elif upd_norm:
            flag = ""
        rows.append({"idx": idx, "entry": e, "link": link, "score": score,
                     "case": case, "party": extract_party(e["update"]),
                     "unchanged_hours": cur_hours, "flag": flag,
                     "same": bool(upd_norm and upd_norm == cur_norm)})
    return rows

@router.get("/handover/import", response_class=HTMLResponse)
def import_page(request: Request, user=Depends(get_current_user),
                db: Session = Depends(get_db)):
    recent = db.query(HandoverImport).order_by(HandoverImport.id.desc()).limit(10).all()
    return templates.TemplateResponse(request, "handover_import.html",
        {"user": user, "preview": None, "recent": recent,
         "today": fmt_date(utcnow())})

@router.post("/handover/import", response_class=HTMLResponse)
def import_preview(request: Request, raw_text: str = Form(""),
                   shift_date: str = Form(""),
                   user=Depends(get_current_user), db: Session = Depends(get_db)):
    parsed = parse_handover(raw_text or "")
    imp = HandoverImport(imported_by=user.username,
                         shift_date=shift_date.strip() or parsed["date"] or fmt_date(utcnow()),
                         raw_text=(raw_text or "")[:20000])
    db.add(imp); db.commit()
    rows = _preview_entries(db, parsed)
    imp.entries_json = json.dumps([{"idx": r["idx"], "link_name": r["entry"]["link"],
                                    "link_id": r["link"].id if r["link"] else None,
                                    "case_id": r["case"].id if r["case"] else None,
                                    "status": r["entry"]["link_state"],
                                    "update": r["entry"]["update"],
                                    "affected": r["entry"]["affected"],
                                    "section": r["entry"]["section"],
                                    "party": r["party"], "flag": r["flag"],
                                    "same": r["same"]} for r in rows])[:20000]
    db.commit()
    recent = db.query(HandoverImport).order_by(HandoverImport.id.desc()).limit(10).all()
    return templates.TemplateResponse(request, "handover_import.html",
        {"user": user, "preview": {"import": imp, "rows": rows, "parsed": parsed},
         "recent": recent, "today": fmt_date(utcnow())})

@router.post("/handover/import/{iid:int}/apply")
async def import_apply(iid: int, request: Request, user=Depends(get_current_user),
                       db: Session = Depends(get_db)):
    imp = db.get(HandoverImport, iid)
    if not imp or imp.applied:
        return RedirectResponse(url="/handover/import", status_code=303)
    form = dict((await request.form()).items())
    entries = json.loads(imp.entries_json or "[]")
    unknown = db.query(Customer).filter(Customer.name == "Unknown").first()
    if unknown is None:
        unknown = Customer(name="Unknown"); db.add(unknown); db.flush()
    applied, skipped, created = 0, 0, 0
    for e in entries:
        idx = e["idx"]
        if form.get(f"skip_{idx}"):
            skipped += 1
            e["outcome"] = "skipped by engineer"
            continue
        update = (e["update"] or "").strip()
        hit = find_secret(update)
        if hit:
            skipped += 1
            e["outcome"] = f"skipped: possible secret ({hit})"
            continue
        link = db.get(Link, e["link_id"]) if e["link_id"] else None
        if link is None and form.get(f"newlink_{idx}"):
            link = Link(name=e["link_name"][:200], customer_id=unknown.id,
                        responsible_team="NOC", aliases="", tier="access", sources="")
            db.add(link); db.flush()
            e["link_id"] = link.id
            created += 1
        case = db.get(Case, e["case_id"]) if e["case_id"] else (_open_case(db, link) if link else None)
        if case is None and link is not None:
            case = Case(engineer=user.username, customer_id=link.customer_id,
                        link_id=link.id, device="", opened_by="handover-import",
                        symptom=update or f"carried from handover {imp.shift_date}",
                        status="open", severity="major",
                        link_state=e["status"] or "down",
                        waiting_on=e["party"] or "", opened_at=utcnow())
            db.add(case); db.flush()
            e["case_id"] = case.id
            created += 1
        if case is None:
            skipped += 1
            e["outcome"] = "skipped: no link (tick 'create link' to add it)"
            continue
        note = update or "(no update given)"
        if e["section"] == "resolved":
            note += " — reported resolved upstream: verify & close"
        db.add(CaseEvent(case_id=case.id, at=utcnow(), engineer=user.username,
                         kind="note", text=f"Handover {imp.shift_date}: {note}"[:4000]))
        if e["status"]:
            case.link_state = e["status"]
        if e["party"] and e["section"] != "resolved":
            case.waiting_on = e["party"]
        for a in e["affected"] or []:
            al = db.query(Link).filter(Link.name.ilike(a.strip())).first()
            if al and not db.query(CaseLink).filter(
                    CaseLink.case_id == case.id, CaseLink.link_id == al.id).first():
                db.add(CaseLink(case_id=case.id, link_id=al.id))
        if e["flag"]:
            db.add(CaseEvent(case_id=case.id, at=utcnow(), engineer="system",
                             kind="system", text=f"Update watch: {e['flag']}"[:500]))
        applied += 1
        e["outcome"] = f"applied to case #{case.id}"
    imp.entries_json = json.dumps(entries)[:20000]
    imp.applied = True
    imp.applied_at = utcnow()
    db.commit()
    return RedirectResponse(url=f"/handover/import/done/{imp.id}", status_code=303)

@router.get("/handover/import/done/{iid:int}", response_class=HTMLResponse)
def import_done(iid: int, request: Request, user=Depends(get_current_user),
                db: Session = Depends(get_db)):
    imp = db.get(HandoverImport, iid)
    entries = json.loads(imp.entries_json or "[]") if imp else []
    return templates.TemplateResponse(request, "handover_import_done.html",
        {"user": user, "imp": imp, "entries": entries})
