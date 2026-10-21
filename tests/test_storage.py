import os
import tempfile
import unittest
from pathlib import Path

from storage import AppError, SQLiteBackend


class QRCheckStorageTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.file = str(Path(self.tmp.name) / "db.sqlite3")
        self.s = SQLiteBackend(self.file)
        self.qr = self.s.add_qr("고정 QR A", "001122")
        self.raw = "SCAN:" + self.qr["id"]

    def tearDown(self):
        self.tmp.cleanup()

    def test_complete_and_event_values(self):
        scan = self.s.register_scan(self.raw, "browser-camera")
        wrong = self.s.verify_scan(scan["scan_id"], "1111")
        self.assertEqual(wrong["status"], "PIN_FAILED")
        good = self.s.verify_scan(scan["scan_id"], "001122")
        self.assertEqual(good["status"], "VERIFIED")
        ev = list(reversed(self.s.list_events()))
        self.assertEqual([e["event"] for e in ev], ["SCANNED", "PIN_FAILED", "VERIFIED"])
        self.assertEqual([e["entered_pin"] for e in ev], [None, "1111", "001122"])
        self.assertEqual(self.s.list_scans()[0]["status"], "VERIFIED")

    def test_pin_change_keeps_fixed_qr_and_history(self):
        prev = self.s.register_scan(self.raw, "manual-test")
        self.assertEqual(self.s.verify_scan(prev["scan_id"], "001122")["status"], "VERIFIED")
        self.s.update_qr(self.qr["id"], pin="9")
        current = self.s.register_scan(self.raw, "manual-test")
        self.assertEqual(self.s.verify_scan(current["scan_id"], "9")["status"], "VERIFIED")
        self.assertEqual(len(self.s.list_scans()), 2)
        self.assertEqual(self.s.list_qrs()[0]["id"], self.qr["id"])

    def test_five_failures_lock(self):
        scan = self.s.register_scan(self.raw, "metamask-rpc")
        for i in range(5):
            result = self.s.verify_scan(scan["scan_id"], "42")
        self.assertEqual(result["status"], "LOCKED")
        self.assertEqual(result["attempts"], 5)
        with self.assertRaises(AppError):
            self.s.verify_scan(scan["scan_id"], "001122")

    def test_repeat_same_qr_creates_new_scan(self):
        a = self.s.register_scan(self.raw, "browser-camera")
        b = self.s.register_scan(self.raw, "browser-camera")
        self.assertNotEqual(a["scan_id"], b["scan_id"])
        self.assertEqual(len(self.s.list_scans()), 2)

    def test_invalid_inputs(self):
        with self.assertRaises(AppError):
            self.s.add_qr("wrong", "abc")
        with self.assertRaises(AppError):
            self.s.add_qr("wrong", "1" * 33)
        with self.assertRaises(AppError):
            self.s.register_scan("SCAN:bogusbogus", "browser-camera")
        with self.assertRaises(AppError):
            self.s.register_scan(self.raw, "fabricated")
        with self.assertRaises(AppError):
            self.s.verify_scan("unknown", "1111")

    def test_disabled_and_persistent(self):
        self.s.update_qr(self.qr["id"], enabled=False)
        with self.assertRaises(AppError):
            self.s.register_scan(self.raw, "browser-camera")
        self.s.update_qr(self.qr["id"], enabled=True)
        self.s.register_scan(self.raw, "browser-camera")
        second = SQLiteBackend(self.file)
        self.assertEqual(len(second.list_scans()), 1)


if __name__ == "__main__":
    unittest.main()

class SupabaseHeadersTest(unittest.TestCase):
    def test_server_secret_key_does_not_send_bearer(self):
        from unittest.mock import patch
        from storage import SupabaseBackend
        import io
        class MockResponse:
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self): return b'[]'
        with patch('storage.urllib.request.urlopen', return_value=MockResponse()) as mocked:
            SupabaseBackend('https://example.supabase.co', 'sb_secret_demo').list_qrs()
            req = mocked.call_args[0][0]
            self.assertEqual(req.get_header('Apikey'), 'sb_secret_demo')
            self.assertFalse(req.has_header('Authorization'))

    def test_legacy_service_role_does_send_bearer(self):
        from unittest.mock import patch
        from storage import SupabaseBackend
        class MockResponse:
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self): return b'[]'
        with patch('storage.urllib.request.urlopen', return_value=MockResponse()) as mocked:
            SupabaseBackend('https://example.supabase.co', 'jwt.legacy.demo').list_qrs()
            req = mocked.call_args[0][0]
            self.assertEqual(req.get_header('Authorization'), 'Bearer jwt.legacy.demo')
  
