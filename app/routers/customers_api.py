"""Customer CRUD API — ready-to-plug for updating customers."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import Customer
from ..security import get_current_user, require_role
from ..utils_time import utcnow

router = APIRouter()


@router.get("/api/customers")
def api_list_customers(user=Depends(get_current_user),
                       db: Session = Depends(get_db)):
    rows = db.query(Customer).order_by(Customer.name).all()
    return JSONResponse([{"id": c.id, "name": c.name, "aliases": c.aliases,
                          "tier": c.tier, "notes": c.notes,
                          "sources": c.sources} for c in rows])


@router.put("/api/customers/{customer_id}")
def api_update_customer(customer_id: int, payload: dict,
                        user=Depends(require_role("admin", "senior")),
                        db: Session = Depends(get_db)):
    c = db.get(Customer, customer_id)
    if not c:
        return JSONResponse({"error": "customer not found"}, status_code=404)
    if "name" in payload:
        c.name = payload["name"].strip()
    if "aliases" in payload:
        c.aliases = payload["aliases"].strip()
    if "tier" in payload:
        c.tier = payload["tier"].strip()
    if "notes" in payload:
        c.notes = payload["notes"].strip()
    if "sources" in payload:
        c.sources = payload["sources"].strip()
    db.commit()
    return JSONResponse({"id": c.id, "name": c.name, "aliases": c.aliases,
                         "tier": c.tier, "notes": c.notes, "sources": c.sources,
                         "updated_at": utcnow().isoformat()})


@router.post("/api/customers")
def api_create_customer(payload: dict,
                        user=Depends(require_role("admin", "senior")),
                        db: Session = Depends(get_db)):
    name = (payload.get("name") or "").strip()
    if not name:
        return JSONResponse({"error": "name required"}, status_code=400)
    if db.query(Customer).filter(Customer.name == name).first():
        return JSONResponse({"error": "customer already exists"}, status_code=400)
    c = Customer(name=name,
                 aliases=(payload.get("aliases") or "").strip(),
                 tier=(payload.get("tier") or "standard").strip(),
                 notes=(payload.get("notes") or "").strip(),
                 sources=(payload.get("sources") or "").strip())
    db.add(c); db.commit(); db.refresh(c)
    return JSONResponse({"id": c.id, "name": c.name, "aliases": c.aliases,
                         "tier": c.tier, "notes": c.notes, "sources": c.sources})


@router.delete("/api/customers/{customer_id}")
def api_delete_customer(customer_id: int,
                        user=Depends(require_role("admin")),
                        db: Session = Depends(get_db)):
    c = db.get(Customer, customer_id)
    if not c:
        return JSONResponse({"error": "customer not found"}, status_code=404)
    db.delete(c); db.commit()
    return JSONResponse({"deleted": customer_id})
