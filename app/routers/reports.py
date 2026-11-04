"""Incident & Escalation Report Generation (P3-6).

Endpoints:
  POST   /api/reports/incidents/upload   — upload incidents JSON/CSV file
  POST   /api/reports/escalations/upload — upload escalations JSON/CSV file
  GET    /api/reports/incidents          — list stored incidents
  GET    /api/reports/escalations        — list stored escalations
  GET    /api/reports/incidents/export   — export incidents as CSV or JSON
  GET    /api/reports/escalations/export — export escalations as CSV or JSON
  GET    /api/reports/powerpoint         — generate PowerPoint report (.pptx) from incidents + escalations
  GET    /api/reports/powerpoint/download — download generated PowerPoint file

Data model matches the uploaded spreadsheet format:
  Customer, Issue Detected, Time Restored, Root Cause
  (plus optional: Asset, Description, Time of Incident, Time of Resolution)
"""

from __future__ import annotations

import csv
import io
import json
import os
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, UploadFile, HTTPException
from fastapi.responses import JSONResponse, Response, FileResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from ..database import get_db
from ..security import get_current_user
from ..utils_time import utcnow, to_lagos

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))

REPORTS_DIR = Path("reports")
REPORTS_DIR.mkdir(exist_ok=True)

# In-memory store for uploaded reports (per session/request). In production
# this would be a database table.
_incidents_store: list[dict] = []
_escalations_store: list[dict] = []


# ---------------------------------------------------------------- upload

@router.post("/api/reports/incidents/upload")
def api_upload_incidents(
    file: UploadFile = File(...),
    user=Depends(get_current_user),
):
    """Upload incidents as CSV or JSON."""
    content = file.file.read()
    filename = (file.filename or "").lower()

    try:
        if filename.endswith(".csv"):
            data = _parse_csv_incidents(content)
        elif filename.endswith(".json"):
            data = json.loads(content.decode("utf-8"))
            if not isinstance(data, list):
                data = [data]
        else:
            return JSONResponse({"error": "Unsupported file type. Use .csv or .json"}, status_code=400)
    except Exception as e:
        return JSONResponse({"error": f"Failed to parse file: {e}"}, status_code=400)

    _incidents_store.extend(data)
    return JSONResponse({
        "uploaded": len(data),
        "total": len(_incidents_store),
        "message": f"Uploaded {len(data)} incident(s).",
    })


@router.post("/api/reports/escalations/upload")
def api_upload_escalations(
    file: UploadFile = File(...),
    user=Depends(get_current_user),
):
    """Upload escalations as CSV or JSON."""
    content = file.file.read()
    filename = (file.filename or "").lower()

    try:
        if filename.endswith(".csv"):
            data = _parse_csv_escalations(content)
        elif filename.endswith(".json"):
            data = json.loads(content.decode("utf-8"))
            if not isinstance(data, list):
                data = [data]
        else:
            return JSONResponse({"error": "Unsupported file type. Use .csv or .json"}, status_code=400)
    except Exception as e:
        return JSONResponse({"error": f"Failed to parse file: {e}"}, status_code=400)

    _escalations_store.extend(data)
    return JSONResponse({
        "uploaded": len(data),
        "total": len(_escalations_store),
        "message": f"Uploaded {len(data)} escalation(s).",
    })


# ---------------------------------------------------------------- list

@router.get("/api/reports/incidents")
def api_list_incidents(user=Depends(get_current_user)):
    return JSONResponse({"count": len(_incidents_store), "incidents": _incidents_store})


@router.get("/api/reports/escalations")
def api_list_escalations(user=Depends(get_current_user)):
    return JSONResponse({"count": len(_escalations_store), "escalations": _escalations_store})


# ---------------------------------------------------------------- export

def _csv_export(rows: list[dict]) -> str:
    """Export rows to CSV with cells expanded (matching the uploaded spreadsheet format)."""
    if not rows:
        return ""
    # Collect all keys
    all_keys = set()
    for r in rows:
        all_keys.update(r.keys())
    # Order columns: customer, issue detected, time restored, root cause first
    preferred = ["Customer", "Issue Detected", "Time Restored", "Root Cause",
                 "Asset", "Description", "Time of Incident", "Time of Resolution"]
    ordered = [k for k in preferred if k in all_keys]
    remaining = [k for k in sorted(all_keys) if k not in ordered]
    fieldnames = ordered + remaining

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    for r in rows:
        writer.writerow({k: r.get(k, "") for k in fieldnames})
    return buf.getvalue()


@router.get("/api/reports/incidents/export")
def api_export_incidents(
    fmt: str = "csv",
    user=Depends(get_current_user),
):
    """Export incidents as CSV or JSON."""
    if fmt == "json":
        return JSONResponse({"incidents": _incidents_store})
    elif fmt == "csv":
        csv_content = _csv_export(_incidents_store)
        return Response(
            content=csv_content,
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename=incidents_{utcnow().strftime('%Y%m%d_%H%M%S')}.csv"},
        )
    else:
        return JSONResponse({"error": "Use ?fmt=csv or ?fmt=json"}, status_code=400)


@router.get("/api/reports/escalations/export")
def api_export_escalations(
    fmt: str = "csv",
    user=Depends(get_current_user),
):
    """Export escalations as CSV or JSON."""
    if fmt == "json":
        return JSONResponse({"escalations": _escalations_store})
    elif fmt == "csv":
        csv_content = _csv_export(_escalations_store)
        return Response(
            content=csv_content,
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename=escalations_{utcnow().strftime('%Y%m%d_%H%M%S')}.csv"},
        )
    else:
        return JSONResponse({"error": "Use ?fmt=csv or ?fmt=json"}, status_code=400)


# ---------------------------------------------------------------- PowerPoint report

@router.get("/api/reports/powerpoint")
def api_powerpoint_report(
    user=Depends(get_current_user),
):
    """Generate PowerPoint (.pptx) report from incidents + escalations.

    Format matches the uploaded report template:
    Title slide → Incident summary table → Escalation summary table.
    """
    try:
        from pptx import Presentation
        from pptx.util import Inches, Pt
        from pptx.enum.text import PP_ALIGN
    except ImportError:
        return JSONResponse(
            {"error": "python-pptx not installed. Run: pip install python-pptx"},
            status_code=500,
        )

    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)

    # ---- Title slide
    slide = prs.slides.add_slide(prs.slide_layouts[0])
    title = slide.shapes.title
    subtitle = slide.placeholders[1]
    title.text = "NOC Incident & Escalation Report"
    subtitle.text = f"Generated {utcnow().strftime('%d %b %Y, %H:%M WAT')}\nIncidents: {len(_incidents_store)} | Escalations: {len(_escalations_store)}"

    # ---- Incident summary slide
    slide = prs.slides.add_slide(prs.slide_layouts[1])
    title = slide.shapes.title
    title.text = "Incident Report"
    body = slide.shapes.placeholders[1].text_frame
    body.text = f"Total incidents: {len(_incidents_store)}"
    # Add a table
    rows = min(len(_incidents_store) + 1, 20)
    cols = 4
    tbl_shape = slide.shapes.add_table(rows, cols, Inches(0.5), Inches(1.5), Inches(12.3), Inches(5.5))
    table = tbl_shape.table
    table.columns[0].width = Inches(2.5)
    table.columns[1].width = Inches(3.5)
    table.columns[2].width = Inches(3.0)
    table.columns[3].width = Inches(3.3)
    headers = ["Customer", "Issue Detected", "Time Restored", "Root Cause"]
    for j, h in enumerate(headers):
        cell = table.cell(0, j)
        cell.text = h
        cell.text_frame.paragraphs[0].runs[0].font.bold = True
    for i, r in enumerate(_incidents_store[:19], start=1):
        table.cell(i, 0).text = str(r.get("Customer", ""))
        table.cell(i, 1).text = str(r.get("Issue Detected", r.get("Description", "")))[:100]
        table.cell(i, 2).text = str(r.get("Time Restored", ""))
        table.cell(i, 3).text = str(r.get("Root Cause", ""))[:120]

    # ---- Escalation summary slide
    slide = prs.slides.add_slide(prs.slide_layouts[1])
    title = slide.shapes.title
    title.text = "Escalation Report"
    body = slide.shapes.placeholders[1].text_frame
    body.text = f"Total escalations: {len(_escalations_store)}"
    tbl_shape = slide.shapes.add_table(min(len(_escalations_store) + 1, 20), cols, Inches(0.5), Inches(1.5), Inches(12.3), Inches(5.5))
    table = tbl_shape.table
    table.columns[0].width = Inches(2.5)
    table.columns[1].width = Inches(3.5)
    table.columns[2].width = Inches(3.0)
    table.columns[3].width = Inches(3.3)
    for j, h in enumerate(headers):
        cell = table.cell(0, j)
        cell.text = h
        cell.text_frame.paragraphs[0].runs[0].font.bold = True
    for i, r in enumerate(_escalations_store[:19], start=1):
        table.cell(i, 0).text = str(r.get("Customer", ""))
        table.cell(i, 1).text = str(r.get("Issue Detected", r.get("Description", "")))[:100]
        table.cell(i, 2).text = str(r.get("Time Restored", ""))
        table.cell(i, 3).text = str(r.get("Root Cause", ""))[:120]

    # Save
    pptx_path = REPORTS_DIR / f"elnoc_report_{utcnow().strftime('%Y%m%d_%H%M%S')}.pptx"
    prs.save(str(pptx_path))
    return JSONResponse({
        "message": "PowerPoint report generated",
        "download_url": f"/api/reports/powerpoint/download/{pptx_path.name}",
        "incidents": len(_incidents_store),
        "escalations": len(_escalations_store),
    })


@router.get("/api/reports/powerpoint/download/{filename}")
def api_download_powerpoint(filename: str, user=Depends(get_current_user)):
    path = REPORTS_DIR / filename
    if not path.exists():
        return JSONResponse({"error": "File not found"}, status_code=404)
    return FileResponse(path, media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation", filename=filename)


# ---------------------------------------------------------------- CSV parsers

def _parse_csv_incidents(content: bytes) -> list[dict]:
    text = content.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    rows = []
    for r in reader:
        # Normalize column names to match the uploaded spreadsheet format
        row = {}
        for k, v in r.items():
            k_clean = (k or "").strip()
            if k_clean:
                row[k_clean] = (v or "").strip()
        if row:
            rows.append(row)
    return rows


def _parse_csv_escalations(content: bytes) -> list[dict]:
    text = content.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    rows = []
    for r in reader:
        row = {}
        for k, v in r.items():
            k_clean = (k or "").strip()
            if k_clean:
                row[k_clean] = (v or "").strip()
        if row:
            rows.append(row)
    return rows
