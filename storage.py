"""QRCheck persistence: local SQLite for development, Supabase REST for deployment."""
from __future__ import annotations

import json
import re
from contextlib import contextmanager
import secrets
import sqlite3
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock

PIN_RE = re.compile(r"^[0-9]{1,32}$")
RAW_RE = re.compile(r"^SCAN:([A-Za-z0-9_-]{8,128})$")
SOURCE_ALLOWLIST = {"metamask-rpc", "browser-camera", "manual-test"}
MAX_ATTEMPTS = 5


class AppError(Exception):
    pass


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def validate_pin(pin: str):
    if not isinstance(pin, str) or not PIN_RE.fullmatch(pin):
        raise AppError("인증번호는 숫자 1~32자리로 입력해주세요.")
    return pin


def qr_id_from_raw(raw: str):
    m = RAW_RE.fullmatch(raw if isinstance(raw, str) else "")
    if not m:
        raise AppError("QRCheck QR코드가 아닙니다. SCAN:... 형식만 지원합니다.")
    return m.group(1)


def new_id():
    return secrets.token_urlsafe(18)


class SQLiteBackend:
    def __init__(self, filename: str):
        self.filename = filename
        Path(filename).parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        with self._db() as c:
            c.executescript("""
                CREATE TABLE IF NOT EXISTS qrcheck_qrs (
                  id TEXT PRIMARY KEY, label TEXT NOT NULL, pin TEXT NOT NULL,
                  enabled INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS qrcheck_scans (
                  id TEXT PRIMARY KEY, qr_id TEXT NOT NULL, source TEXT NOT NULL,
                  status TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
                  created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                  FOREIGN KEY (qr_id) REFERENCES qrcheck_qrs(id)
                );
                CREATE TABLE IF NOT EXISTS qrcheck_events (
                  id INTEGER PRIMARY KEY AUTOINCREMENT, scan_id TEXT NOT NULL,
                  qr_id TEXT NOT NULL, event TEXT NOT NULL,
                  entered_pin TEXT, created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_scan_created ON qrcheck_scans(created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_event_created ON qrcheck_events(created_at DESC);
            """)

    @contextmanager
    def _db(self):
        c = sqlite3.connect(self.filename, timeout=20)
        try:
            c.row_factory = sqlite3.Row
            c.execute("PRAGMA busy_timeout=20000")
            c.execute("PRAGMA foreign_keys=ON")
            with c:
                yield c
        finally:
            c.close()

    @staticmethod
    def _one(row):
        return dict(row) if row else None

    def add_qr(self, label: str, pin: str):
        pin = validate_pin(pin)
        label = label.strip()[:100]
        if not label:
            raise AppError("QR 이름을 입력해주세요.")
        entry = {"id": new_id(), "label": label, "pin": pin, "enabled": True, "created_at": utc_now()}
        with self._lock, self._db() as c:
            c.execute("INSERT INTO qrcheck_qrs VALUES (?, ?, ?, ?, ?)",
                      (entry["id"], label, pin, 1, entry["created_at"]))
            c.commit()
        return entry

    def list_qrs(self):
        with self._db() as c:
            return [dict(r) for r in c.execute(
                "SELECT id,label,enabled,created_at,length(pin) AS pin_length FROM qrcheck_qrs ORDER BY created_at DESC")]

    def update_qr(self, qr_id: str, *, pin: str | None = None, enabled: bool | None = None):
        if pin is None and enabled is None:
            raise AppError("변경할 항목이 없습니다.")
        with self._lock, self._db() as c:
            if pin is not None:
                c.execute("UPDATE qrcheck_qrs SET pin=? WHERE id=?", (validate_pin(pin), qr_id))
            if enabled is not None:
                c.execute("UPDATE qrcheck_qrs SET enabled=? WHERE id=?", (int(enabled), qr_id))
            c.commit()
            row = c.execute("SELECT id,label,enabled FROM qrcheck_qrs WHERE id=?", (qr_id,)).fetchone()
            if row is None:
                raise AppError("해당 QR을 찾을 수 없습니다.")
            return dict(row)

    def register_scan(self, raw: str, source: str):
        qr_id = qr_id_from_raw(raw)
        if source not in SOURCE_ALLOWLIST:
            raise AppError("허용되지 않은 스캔 출처입니다.")
        scan_id, now = new_id(), utc_now()
        with self._lock, self._db() as c:
            c.execute("BEGIN IMMEDIATE")
            qr = c.execute("SELECT enabled FROM qrcheck_qrs WHERE id=?", (qr_id,)).fetchone()
            if not qr or not bool(qr["enabled"]):
                raise AppError("등록되지 않았거나 비활성화된 QR코드입니다.")
            c.execute("INSERT INTO qrcheck_scans VALUES (?,?,?,'SCANNED',0,?,?)",
                      (scan_id, qr_id, source, now, now))
            c.execute("INSERT INTO qrcheck_events(scan_id,qr_id,event,entered_pin,created_at) VALUES(?,?, 'SCANNED',NULL,?)",
                      (scan_id, qr_id, now))
            c.commit()
        return {"scan_id": scan_id, "qr_id": qr_id, "status": "SCANNED", "created_at": now}

    def verify_scan(self, scan_id: str, pin: str):
        pin = validate_pin(pin)
        with self._lock, self._db() as c:
            c.execute("BEGIN IMMEDIATE")
            row = c.execute("""
              SELECT s.qr_id,s.status,s.attempts,q.pin AS expected
              FROM qrcheck_scans s JOIN qrcheck_qrs q ON q.id=s.qr_id WHERE s.id=?
            """, (scan_id,)).fetchone()
            if row is None:
                raise AppError("유효하지 않은 스캔 기록입니다.")
            if row["status"] in ("VERIFIED", "LOCKED"):
                raise AppError("이미 완료되었거나 잠긴 스캔입니다.")
            count = row["attempts"] + 1
            event = "VERIFIED" if pin == row["expected"] else ("LOCKED" if count >= MAX_ATTEMPTS else "PIN_FAILED")
            now = utc_now()
            c.execute("UPDATE qrcheck_scans SET attempts=?,status=?,updated_at=? WHERE id=?",
                      (count, event, now, scan_id))
            c.execute("INSERT INTO qrcheck_events(scan_id,qr_id,event,entered_pin,created_at) VALUES(?,?,?,?,?)",
                      (scan_id, row["qr_id"], event, pin, now))
            c.commit()
        return {"scan_id": scan_id, "status": event, "attempts": count, "success": event == "VERIFIED"}

    def list_scans(self, limit: int = 250):
        with self._db() as c:
            return [dict(r) for r in c.execute("""
              SELECT s.id,s.qr_id,q.label,s.source,s.status,s.attempts,s.created_at,s.updated_at
              FROM qrcheck_scans s JOIN qrcheck_qrs q ON q.id=s.qr_id
              ORDER BY s.created_at DESC LIMIT ?
            """, (limit,))]

    def list_events(self, limit: int = 500):
        with self._db() as c:
            return [dict(r) for r in c.execute("""
              SELECT e.id,e.scan_id,e.qr_id,q.label,e.event,e.entered_pin,e.created_at
              FROM qrcheck_events e JOIN qrcheck_qrs q ON q.id=e.qr_id
              ORDER BY e.id DESC LIMIT ?
            """, (limit,))]


class SupabaseBackend:
    """Server-side only REST client; the service-role key is never sent to the browser."""
    def __init__(self, url: str, key: str):
        self.root = url.rstrip("/")
        self.key = key
        if not self.root.startswith("https://"):
            raise AppError("Supabase URL은 HTTPS 주소여야 합니다.")

    def _req(self, endpoint: str, method="GET", body=None, query=""):
        uri = self.root + "/rest/v1/" + endpoint + ("?" + query if query else "")
        data = json.dumps(body).encode() if body is not None else None
        headers = {
            "apikey": self.key,
            "Content-Type": "application/json", "Accept": "application/json",
            "Prefer": "return=representation",
        }
        if not self.key.startswith("sb_secret_"):
            # Legacy service_role JWT still uses Authorization. The new sb_secret key is not a JWT.
            headers["Authorization"] = "Bearer " + self.key
        req = urllib.request.Request(uri, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                bodytext = resp.read().decode("utf-8")
                return json.loads(bodytext) if bodytext else None
        except urllib.error.HTTPError as e:
            txt = e.read().decode("utf-8", errors="replace")
            raise AppError(f"Supabase 요청 실패 ({e.code}): {txt[:220]}") from e
        except (urllib.error.URLError, TimeoutError) as e:
            raise AppError("Supabase에 접속할 수 없습니다. 네트워크와 설정을 확인하세요.") from e

    def add_qr(self, label, pin):
        validate_pin(pin)
        label = label.strip()[:100]
        if not label:
            raise AppError("QR 이름을 입력해주세요.")
        ret = self._req("qrcheck_qrs", "POST", {"id": new_id(), "label": label, "pin": pin})
        return ret[0]

    def list_qrs(self):
        records = self._req("qrcheck_qrs", query="select=id,label,enabled,created_at,pin&order=created_at.desc") or []
        return [{"id": r["id"], "label": r["label"], "enabled": r["enabled"],
                 "created_at": r["created_at"], "pin_length": len(r["pin"])} for r in records]

    def update_qr(self, qr_id, *, pin=None, enabled=None):
        payload = {}
        if pin is not None: payload["pin"] = validate_pin(pin)
        if enabled is not None: payload["enabled"] = bool(enabled)
        if not payload: raise AppError("변경할 항목이 없습니다.")
        ret = self._req("qrcheck_qrs", "PATCH", payload, "id=eq." + urllib.parse.quote(qr_id))
        if not ret: raise AppError("해당 QR을 찾을 수 없습니다.")
        return ret[0]

    def register_scan(self, raw, source):
        qr_id_from_raw(raw)
        if source not in SOURCE_ALLOWLIST:
            raise AppError("허용되지 않은 스캔 출처입니다.")
        return self._req("rpc/qrcheck_register_scan", "POST", {
            "p_scan_id": new_id(), "p_raw": raw, "p_source": source})

    def verify_scan(self, scan_id, pin):
        validate_pin(pin)
        return self._req("rpc/qrcheck_verify_scan", "POST", {
            "p_scan_id": scan_id, "p_pin": pin})

    def list_scans(self, limit=250):
        return self._req("qrcheck_scans", query=f"select=*&order=created_at.desc&limit={int(limit)}") or []

    def list_events(self, limit=500):
        return self._req("qrcheck_events", query=f"select=*&order=id.desc&limit={int(limit)}") or []
