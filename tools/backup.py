"""Nightly backup (NFR-10)."""
import sys
sys.path.insert(0, ".")
from app.config import settings
from app.services.backup import backup_db

if __name__ == "__main__":
    print(backup_db(settings.DB_PATH, settings.BACKUP_DIR))
