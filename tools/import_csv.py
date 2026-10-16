"""CSV registry import (FR-10). Usage:
python tools/import_csv.py --kind customers --file data/seed/customers.csv
python tools/import_csv.py --kind links --file data/seed/links.csv
python tools/import_csv.py --kind contacts --file data/seed/contacts.csv
python tools/import_csv.py --kind devices --file data/seed/devices.csv
"""
import argparse, sys
sys.path.insert(0, ".")
from app.database import init_db, SessionLocal
from app.adapters.phoenix_csv import import_registry_csv

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--kind", required=True, choices=["customers", "links", "contacts", "devices"])
    ap.add_argument("--file", required=True)
    a = ap.parse_args()
    init_db()
    db = SessionLocal()
    n = import_registry_csv(db, a.kind, a.file)
    print(f"imported {n} {a.kind} from {a.file}")
