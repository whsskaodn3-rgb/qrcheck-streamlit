"""Optional one-time migration of v4 QR IDs/PINs to Streamlit edition.

Local:    python import_v4_qrs.py /path/to/old/data/scans.sqlite3
Supabase: set SUPABASE_URL and SUPABASE_SECRET_KEY, then rerun same command.
Only QR definitions are migrated; v4 scan history stays in the old DB.
"""
import os
import sqlite3
import sys
from pathlib import Path

from storage import SQLiteBackend, SupabaseBackend, validate_pin


def main(src_path):
    path = Path(src_path)
    if not path.is_file():
        raise SystemExit(f"v4 database not found: {path}")
    src = sqlite3.connect(path)
    src.row_factory = sqlite3.Row
    try:
        rows = src.execute("SELECT id,label,expected_pin,created_at FROM qrs").fetchall()
    finally:
        src.close()

    url = os.getenv("SUPABASE_URL", "")
    key = os.getenv("SUPABASE_SECRET_KEY", "") or os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
    if bool(url) != bool(key):
        raise SystemExit("Set both SUPABASE_URL and SUPABASE_SECRET_KEY or neither.")
    target = SupabaseBackend(url, key) if url else SQLiteBackend(os.getenv("LOCAL_DB", "data/qrcheck.sqlite3"))
    present = {r["id"] for r in target.list_qrs()}
    imported = skipped = 0
    for qr in rows:
        if qr["id"] in present:
            skipped += 1
            continue
        record = dict(qr)
        validate_pin(record["expected_pin"])
        if url:
            target._req("qrcheck_qrs", "POST", {
                "id": record["id"], "label": record["label"],
                "pin": record["expected_pin"], "created_at": record["created_at"]})
        else:
            with target._db() as c:
                c.execute("INSERT INTO qrcheck_qrs(id,label,pin,enabled,created_at) VALUES(?,?,?,1,?)",
                          (record["id"],record["label"],record["expected_pin"],record["created_at"]))
                c.commit()
        imported += 1
    print(f"Migrated: {imported}, existing/skipped: {skipped}. QR text and image stay the same.")
    print("Note: older scan/event history was not imported.")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python import_v4_qrs.py /path/to/v4/data/scans.sqlite3")
    main(sys.argv[1])
