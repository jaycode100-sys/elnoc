"""Fuzzy search across customer/link/alias + deterministic alias learning (FR-12, FR-16)."""
from __future__ import annotations
from sqlalchemy.orm import Session
from rapidfuzz import fuzz, process
from ..models import Link, Customer, AliasLearned

def _candidates(db: Session) -> list[dict]:
    out = []
    links = db.query(Link).all()
    custs = {c.id: c for c in db.query(Customer).all()}
    for l in links:
        c = custs.get(l.customer_id)
        cname = c.name if c else ""
        texts = [l.name, l.circuit_id or "", l.a_end or "", l.b_end or "",
                 (l.aliases or ""), cname, (c.aliases if c else "")]
        blob = " | ".join(t for t in texts if t)
        out.append({"kind": "link", "id": l.id, "label": f"{l.name} — {cname}",
                    "link": l, "customer": c, "blob": blob})
    return out

def _boost(db: Session, typed: str, cand_id: int) -> int:
    row = db.query(AliasLearned).filter(
        AliasLearned.typed_text == typed.strip().lower(),
        AliasLearned.entity_type == "link",
        AliasLearned.entity_id == cand_id).first()
    return (row.count * 5) if row else 0  # deterministic, no ML

def search_links(db: Session, query: str, limit: int = 8) -> list[dict]:
    q = (query or "").strip()
    if not q:
        return []
    cands = _candidates(db)
    if not cands:
        return []
    scored = []
    for c in cands:
        # best partial score across name / alias blob
        s = max(
            fuzz.WRatio(q, c["link"].name),
            fuzz.partial_ratio(q.lower(), c["blob"].lower()),
            fuzz.token_set_ratio(q, c["blob"]),
        )
        s += _boost(db, q, c["id"])
        scored.append((s, c))
    scored.sort(key=lambda t: t[0], reverse=True)
    results = []
    for score, c in scored[:limit]:
        l = c["link"]
        results.append({
            "score": round(float(score), 1),
            "link_id": l.id,
            "link_name": l.name,
            "circuit_id": l.circuit_id,
            "customer": c["customer"].name if c["customer"] else "",
            "customer_id": c["customer"].id if c["customer"] else None,
            "a_end": l.a_end, "b_end": l.b_end,
            "responsible_team": l.responsible_team,
            "tier": l.tier,
        })
    return results

def learn_alias(db: Session, typed: str, entity_type: str, entity_id: int) -> None:
    """Every selection increments alias learning (FR-16)."""
    key = (typed or "").strip().lower()
    if not key:
        return
    row = db.query(AliasLearned).filter(
        AliasLearned.typed_text == key,
        AliasLearned.entity_type == entity_type,
        AliasLearned.entity_id == entity_id).first()
    if row:
        row.count += 1
    else:
        db.add(AliasLearned(typed_text=key, entity_type=entity_type, entity_id=entity_id, count=1))
    db.commit()
