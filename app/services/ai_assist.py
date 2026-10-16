"""Phase 6a scaffolding: glossary + RSL interpreter (numbers from code, FR-73/74)."""
from __future__ import annotations

GLOSSARY: dict[str, str] = {
    "rsl": "Received Signal Level — optical power at the receiver, in dBm. More negative = weaker.",
    "far-end": "The remote end of the link (the side that is not local). 'Far end not transmitting' means the remote laser is dark or its fibre is broken toward us.",
    "rc": "In team shorthand, the remote customer-side unit/site (as in 'LTV8 Ikeja-RC'). Confirm per link.",
    "pon": "Passive Optical Network — one OLT port feeds many ONUs through a splitter.",
    "onu": "Optical Network Unit — customer-side fibre endpoint on a PON.",
    "olt": "Optical Line Terminal — central-side PON equipment.",
    "otdr": "Optical Time-Domain Reflectometer — sends pulses and plots reflections vs distance to find cuts/splices.",
    "dbm": "Decibel-milliwatts. Fibre RSL is negative (e.g. -19 dBm is healthy, -28 dBm is near failure for many optics).",
    "attenuation": "Loss of signal along fibre/splices/connectors, in dB.",
    "l1": "Level 1 Support — first-line: initial checks, link status, ping tests, ticket logging.",
    "l2": "Level 2 Support — advanced technical: VLAN/interface checks, MAC learning, routing, packet loss, config.",
    "l3": "Level 3 Support — senior/network specialists: core equipment, routing protocols, major outages.",
    "vendor": "External provider path — third-party fibre/equipment/expertise. A separate path, not above L3.",
}

# Typical APD/GPON limits; per-link optic datasheet overrides (FR-74)
DEFAULT_LIMITS = {"warn_dbm": -25.0, "fail_dbm": -28.0}

OPTIC_LIMITS = {
    "GPON-B+": {"warn_dbm": -25.0, "fail_dbm": -28.0},
    "GPON-C+": {"warn_dbm": -27.0, "fail_dbm": -30.0},
    "XGS-PON": {"warn_dbm": -26.0, "fail_dbm": -28.0},
    "1G-LX": {"warn_dbm": -20.0, "fail_dbm": -24.0},
    "10G-LR": {"warn_dbm": -18.0, "fail_dbm": -20.5},
}

def explain(term: str) -> dict:
    key = (term or "").strip().lower()
    for k, v in GLOSSARY.items():
        if k in key or key in k:
            return {"term": k, "definition": v, "source": "ELNOC glossary (editable by seniors)"}
    return {"term": term, "definition": "I don't know — glossary has no entry. Ask a senior to add it.",
            "source": "ELNOC glossary", "confidence": "low"}

def interpret_rsl(rsl_dbm: float, optic_model: str = "", history: list[float] | None = None) -> dict:
    """Pure-code calculation; model quotes it, never computes (sec 17.4)."""
    lim = OPTIC_LIMITS.get((optic_model or "").strip(), DEFAULT_LIMITS)
    margin = round(rsl_dbm - lim["fail_dbm"], 2)  # >0 means above failure floor
    if rsl_dbm <= lim["fail_dbm"]:
        status, causes = "FAIL", ["likely fibre break, far-end dark, or dirty connector; check RSL history for a step drop"]
    elif rsl_dbm <= lim["warn_dbm"]:
        status, causes = "MARGINAL", ["aging splice, bend, or dirty connector; trend matters more than one reading"]
    else:
        status, causes = "OK", ["within optic limits"]
    drift = None
    if history and len(history) >= 3:
        drift = round(rsl_dbm - sum(history[-5:]) / min(5, len(history)), 2)
    return {"rsl_dbm": rsl_dbm, "optic": optic_model or "default",
            "limits": lim, "margin_db": margin, "status": status,
            "likely_causes": causes,
            "first_checks": ["verify far-end transmitting", "inspect/clean connectors",
                             "compare with last 5 readings", "OTDR if step drop"],
            "drift_db": drift}
