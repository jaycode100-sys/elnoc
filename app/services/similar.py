"""Similar cases: same link first, then same customer, then FTS symptom (FR-23)."""
from __future__ import annotations
from sqlalchemy import text
from sqlalchemy.orm import Session
from ..models import Case

def _fts_match(db: Session, symptom: str, exclude_id: int, limit: int = 10) -> list[int]:
    q = (symptom or "").strip()
    if len(q) < 3:
        return []
    if db.bind and db.bind.dialect.name != "sqlite":
        return _ilike_match(db, q, exclude_id, limit)
    # quote for FTS5
    safe = '"' + q.replace('"', ' ')[:120] + '"'
    try:
        rows = db.execute(
            text("SELECT case_id FROM case_fts WHERE case_fts MATCH :q LIMIT :lim"),
            {"q": safe, "lim": limit}).fetchall()
        return [r[0] for r in rows if r[0] != exclude_id]
    except Exception:
        return []

def _ilike_match(db: Session, symptom: str, exclude_id: int, limit: int) -> list[int]:
    """Postgres/Supabase path: no FTS5 there — keyword ILIKE over the card."""
    words = [w for w in symptom.replace('"', " ").split() if len(w) > 3][:4]
    if not words:
        return []
    from sqlalchemy import or_ as _or
    conds = []
    for w in words:
        like = f"%{w}%"
        conds.append(Case.symptom.ilike(like))
        conds.append(Case.fix.ilike(like))
    try:
        rows = db.query(Case.id).filter(Case.id != exclude_id, _or(*conds))\
            .order_by(Case.opened_at.desc()).limit(limit).all()
        return [r[0] for r in rows]
    except Exception:
        return []

def similar_cases(db: Session, case: Case, limit: int = 5) -> list[Case]:
    scored: dict[int, tuple[int, Case]] = {}
    # 1) same link
    if case.link_id:
        for c in db.query(Case).filter(Case.link_id == case.link_id, Case.id != case.id)\
                .order_by(Case.opened_at.desc()).limit(limit * 2).all():
            scored[c.id] = (100, c)
    # 2) same customer
    if case.customer_id:
        for c in db.query(Case).filter(Case.customer_id == case.customer_id, Case.id != case.id)\
                .order_by(Case.opened_at.desc()).limit(limit * 2).all():
            scored.setdefault(c.id, (50, c))
    # 3) FTS symptom
    for cid in _fts_match(db, case.symptom or "", case.id or 0):
        c = db.get(Case, cid)
        if c and c.id not in scored:
            scored[c.id] = (10, c)
    ranked = sorted(scored.values(), key=lambda t: t[0], reverse=True)
    return [c for _, c in ranked[:limit]]

def sync_fts(db: Session, case: Case, customer_name: str = "", link_name: str = "") -> None:
    if db.bind and db.bind.dialect.name != "sqlite":
        return  # Postgres path reads live rows via _ilike_match; nothing to sync
    db.execute(text("DELETE FROM case_fts WHERE case_id = :cid"), {"cid": case.id})
    db.execute(text("DELETE FROM case_fts WHERE case_id = :cid"), {"cid": case.id})
    db.execute(text(
        "INSERT INTO case_fts(case_id, symptom, fix, root_cause_detail, customer_name, link_name)"
        " VALUES (:cid, :s, :f, :r, :c, :l)"),
        {"cid": case.id, "s": case.symptom or "", "f": case.fix or "",
         "r": case.root_cause_detail or "", "c": customer_name, "l": link_name})
    db.commit()
