import importlib.util
import io
import json
import os
import sqlite3
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
spec = importlib.util.spec_from_file_location("nova_backend_tested", ROOT / "app" / "nova_backend.py")
nova = importlib.util.module_from_spec(spec)
spec.loader.exec_module(nova)


class NovaBackendTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="nova-tests-")
        nova.DATA = os.path.join(cls.temp.name, "data")
        nova.MODELS = os.path.join(cls.temp.name, "models")
        nova.DB = os.path.join(nova.DATA, "nova.db")
        nova.PREFS = os.path.join(nova.DATA, "prefs.json")
        os.makedirs(nova.DATA, exist_ok=True)
        os.makedirs(nova.MODELS, exist_ok=True)
        nova._embed_ok.update(v=False, checked=__import__("time").time())
        nova.init_db()

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def setUp(self):
        with nova.db() as c:
            for table in ("notes", "memory", "docs", "chunks", "cards", "exams", "reminders", "fetchlog", "recipes", "skills"):
                c.execute("DELETE FROM " + table)
            c.execute("DELETE FROM memory_fts")
            c.execute("DELETE FROM chunks_fts")
        try:
            os.remove(nova.PREFS)
        except FileNotFoundError:
            pass

    def test_calculator_safe_arithmetic(self):
        self.assertEqual(nova.calculator("(12 + 8) / 4"), "(12 + 8) / 4 = 5")
        self.assertEqual(nova.calculator("2^3"), "2**3 = 8")
        self.assertEqual(nova.calculator("10 % 3"), "10 % 3 = 1")

    def test_calculator_rejects_code_and_unbounded_powers(self):
        self.assertEqual(nova.calculator("__import__('os').system('whoami')"), "")
        self.assertEqual(nova.calculator("2^100"), "")
        self.assertEqual(nova.calculator("1/0"), "")

    def test_model_filename_and_url_validation(self):
        self.assertEqual(nova.safe_model_name(r"C:\\fake\\test model.gguf"), "test_model.gguf")
        self.assertEqual(nova.safe_model_name("../x"), "x.gguf")
        self.assertTrue(nova.valid_model_download_url("https://huggingface.co/a/b/resolve/main/m.gguf"))
        self.assertFalse(nova.valid_model_download_url("http://huggingface.co/a/m.gguf"))
        self.assertFalse(nova.valid_model_download_url("https://example.com/m.gguf"))

    def test_public_web_url_blocks_private_network(self):
        self.assertFalse(nova._public_web_url("http://127.0.0.1:8765/api/health"))
        self.assertFalse(nova._public_web_url("file:///etc/passwd"))

    def test_memory_and_document_keyword_fallback(self):
        rid = nova.remember("I prefer dark mode in the desktop app", "test")
        self.assertTrue(rid)
        self.assertTrue(any("dark mode" in x["fact"] for x in nova.recall("dark mode")))
        doc = nova.ingest("study.txt", "Photosynthesis converts light energy into chemical energy in green plants. " * 4)
        self.assertGreater(doc["chunks"], 0)
        self.assertTrue(nova.doc_search("chemical energy"))

    def test_preferences_are_written_atomically_and_validate_type(self):
        saved = nova.set_prefs({"mode": "detailed"})
        self.assertEqual(saved["mode"], "detailed")
        self.assertEqual(nova.get_prefs()["mode"], "detailed")
        with self.assertRaises(ValueError):
            nova.set_prefs(["not", "a", "mapping"])
        self.assertEqual(nova.get_prefs()["mode"], "detailed")

    def test_model_download_reservation_prevents_overlap(self):
        with nova._dl_lock:
            nova._dl.update(state="running", name="busy.gguf")
        try:
            result = nova.start_download(
                "https://huggingface.co/example/repo/resolve/main/model.gguf", "model.gguf")
            self.assertFalse(result["ok"])
            self.assertIn("already running", result["error"])
        finally:
            with nova._dl_lock:
                nova._dl.update(state="idle", name="", done=0, total=0, error="")

    def test_backup_restore_and_invalid_backup_error(self):
        nova.run("INSERT INTO notes(title,body,created,updated) VALUES(?,?,?,?)", ("Saved", "test data", 1, 1))
        nova.set_prefs({"mode": "detailed"})
        handler = object.__new__(nova.Handler)
        backup = handler._backup()
        nova.run("DELETE FROM notes")
        self.assertTrue(handler._restore(backup)["ok"])
        self.assertEqual(nova.one("SELECT title FROM notes")["title"], "Saved")
        self.assertEqual(nova.get_prefs()["mode"], "detailed")
        bad = handler._restore(b"not a zip file")
        self.assertFalse(bad["ok"])
        self.assertIn("error", bad)
        self.assertNotIn("NameError", bad["error"])

    def test_http_ui_and_local_origin_guard(self):
        server = nova.ThreadingHTTPServer(("127.0.0.1", 0), nova.Handler)
        old_port = nova.PORT
        nova.PORT = server.server_port
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = "http://127.0.0.1:%d" % server.server_port
        try:
            with urllib.request.urlopen(base + "/", timeout=3) as r:
                self.assertEqual(r.status, 200)
                self.assertIn(b"NOVA", r.read(4096))
            req = urllib.request.Request(base + "/api/calc", data=json.dumps({"expr": "9*9"}).encode(),
                                         headers={"Content-Type": "application/json", "Origin": base}, method="POST")
            with urllib.request.urlopen(req, timeout=3) as r:
                self.assertEqual(json.load(r)["result"], "9*9 = 81")

            # Model import must accept a complete GGUF and reject a fake file.
            good_model = b"GGUF" + (b"\x00" * 1_000_010)
            upload = urllib.request.Request(base + "/api/models/import?name=smoke.gguf", data=good_model,
                                            headers={"Origin": base, "Content-Type": "application/octet-stream"},
                                            method="POST")
            with urllib.request.urlopen(upload, timeout=5) as r:
                result = json.load(r)
                self.assertTrue(result["ok"])
                self.assertEqual(result["name"], "smoke.gguf")
            self.assertTrue(os.path.isfile(os.path.join(nova.MODELS, "smoke.gguf")))

            fake_model = urllib.request.Request(base + "/api/models/import?name=fake.gguf", data=b"not a GGUF" + (b"\x00" * 1_000_010),
                                                headers={"Origin": base, "Content-Type": "application/octet-stream"},
                                                method="POST")
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(fake_model, timeout=5)
            self.assertEqual(ctx.exception.code, 400)
            self.assertFalse(os.path.exists(os.path.join(nova.MODELS, "fake.gguf")))

            bad = urllib.request.Request(base + "/api/calc", data=b'{"expr":"1+1"}',
                                         headers={"Content-Type": "application/json", "Origin": "http://attacker.example:%d" % server.server_port}, method="POST")
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(bad, timeout=3)
            self.assertEqual(ctx.exception.code, 403)
        finally:
            server.shutdown()
            server.server_close()
            nova.PORT = old_port


if __name__ == "__main__":
    unittest.main(verbosity=2)
