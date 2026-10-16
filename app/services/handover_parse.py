"""Tolerant parser for the real Daily-Handover WhatsApp text.

ELNOC *produces* the canonical format (services/handover.py) but must *read*
what engineers actually paste: inconsistent spacing (STATUS:DOWN, STATUS :
DOWN), missing UPDATE: prefixes, typo'd FOLLOWING, AFFECTED LINKS: inline vs
LINKS AFFECTED on its own line, resolved notes after a bar (UP | reason),
doubled or missing --- dividers, non-standard states (AWAITING CONFIRMATION…).

Anything unrecognized lands in `warnings`, never silently dropped.
"""
from __future__ import annotations
import re

HEADER_RX = re.compile(r"^TICKET UPDATES\s*[–—-]\s*(.+?)\s*$", re.IGNORECASE)
STATUS_RX = re.compile(r"^STATUS\s*:\s*(.+?)\s*$", re.IGNORECASE)
UPDATE_RX = re.compile(r"^UPDATE\s*:\s*(.*)$", re.IGNORECASE)
AFFECT_INLINE_RX = re.compile(r"^(?:AFFECTED LINKS|LINKS AFFECTED)\s*:\s*(.+)$", re.IGNORECASE)
AFFECT_HEAD_RX = re.compile(r"^(?:AFFECTED LINKS|LINKS AFFECTED)\s*$", re.IGNORECASE)
DIV_RX = re.compile(r"^-{10,}\s*$")
UNRES_HDR = "UNRESOLVED LINKS"
RES_HDR = "RESOLVED LINKS"

# "FOLLOWING UP WITH X" wager: the waiting party, when the line is shaped so.
PARTY_RX = re.compile(r"^FOLLOWING\s+(?:UP|UIP)\s+WITH\s+(.+)$", re.IGNORECASE)


def normalize_status(raw: str) -> tuple[str | None, str, str]:
    """-> (link_state|None, status_raw_upper, trailing note after bar)."""
    s = (raw or "").strip()
    parts = [p.strip() for p in s.split("|", 1)]
    state, note = parts[0].upper(), (parts[1] if len(parts) > 1 else "")
    if state == "DOWN":
        return "down", state, note
    if state == "DEGRADED":
        return "degraded", state, note
    if state == "UP":
        return "up", state, note
    return None, state, note  # e.g. AWAITING CONFIRMATION… — kept raw, still unresolved


def split_affected(text: str) -> list[str]:
    return [a.strip() for a in re.split(r"[,;]", text or "") if a.strip()]


def parse_handover(text: str) -> dict:
    """Parse pasted WhatsApp handover -> {date, unresolved[], resolved[], warnings[]}.

    Entry: {link, status_raw, link_state|None, update, affected[], section}.
    """
    unresolved, resolved, warnings = [], [], []
    date, section, current = None, None, None

    def flush():
        nonlocal current
        if current and (current.get("link") or "").strip():
            (unresolved if current["section"] == "unresolved" else resolved).append(current)
        current = None

    expect_affected = False
    for lineno, raw_line in enumerate((text or "").splitlines(), 1):
        line = raw_line.strip()
        if not line:
            expect_affected = False
            continue
        m = HEADER_RX.match(line)
        if m:
            date = m.group(1).strip()
            continue
        up = line.upper()
        if up == UNRES_HDR:
            flush(); section = "unresolved"; continue
        if up == RES_HDR:
            flush(); section = "resolved"; continue
        if DIV_RX.match(line):
            flush(); expect_affected = False; continue
        if section is None:
            warnings.append(f"line {lineno}: before any section: {line[:80]}")
            continue

        m = STATUS_RX.match(line)
        if m:
            if current is None:
                warnings.append(f"line {lineno}: STATUS without a link: {line[:80]}")
                continue
            state, status_raw, note = normalize_status(m.group(1))
            current["status_raw"] = status_raw
            current["link_state"] = state
            if note:
                current["update"] = ((current.get("update") or "") + f" | {note}").strip(" |")
            expect_affected = False
            continue

        m = UPDATE_RX.match(line)
        if m:
            if current is None:
                warnings.append(f"line {lineno}: UPDATE without a link: {line[:80]}")
                continue
            bit = m.group(1).strip()
            current["update"] = ((current.get("update") or "") + f" | {bit}").strip(" |") if bit else current.get("update", "")
            expect_affected = False
            continue

        m = AFFECT_INLINE_RX.match(line)
        if m:
            if current is None:
                warnings.append(f"line {lineno}: affected-links without a link: {line[:80]}")
                continue
            current["affected"].extend(split_affected(m.group(1)))
            expect_affected = False
            continue
        if AFFECT_HEAD_RX.match(line):
            expect_affected = True
            continue
        if expect_affected:
            # the line(s) after a bare LINKS AFFECTED head
            if current is not None:
                current["affected"].extend(split_affected(line))
                continue
            warnings.append(f"line {lineno}: affected-links without a link: {line[:80]}")
            expect_affected = False
            continue

        if line.upper().startswith("FOLLOW"):
            # bare follow-up line, UPDATE: prefix missing (typos tolerated)
            if current is None:
                warnings.append(f"line {lineno}: follow-up without a link: {line[:80]}")
                continue
            current["update"] = ((current.get("update") or "") + f" | {line}").strip(" |")
            continue

        # otherwise: a new link entry starts
        flush()
        current = {"link": line, "status_raw": "", "link_state": None,
                   "update": "", "affected": [], "section": section}

    flush()
    # de-dup affected, keep order
    for e in unresolved + resolved:
        seen, out = set(), []
        for a in e["affected"]:
            k = a.upper()
            if k not in seen:
                seen.add(k); out.append(a)
        e["affected"] = out
    return {"date": date, "unresolved": unresolved, "resolved": resolved,
            "warnings": warnings}


def extract_party(update: str) -> str:
    """Waiting party from a FOLLOWING UP WITH … update ("" when absent)."""
    if not update:
        return ""
    first = update.split("|")[0].strip()
    m = PARTY_RX.match(first)
    if m:
        return m.group(1).strip().upper()[:300]
    # also accept "TEAM TO …, FOLLOWING UP WITH X" mid-line shapes
    m = re.search(r"FOLLOWING\s+(?:UP|UIP)\s+WITH\s+([^|]+)", update, re.IGNORECASE)
    return m.group(1).strip().upper()[:300] if m else ""
