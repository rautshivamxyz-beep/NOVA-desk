import base64
import hashlib
import io
import re
import tarfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class PackagingTests(unittest.TestCase):
    def test_embedded_source_bundle_is_current_and_complete(self):
        parts = sorted(ROOT.glob("NOVA-Desktop-3.0-core.b64.part*"))
        self.assertTrue(parts, "source archive parts are missing")
        encoded = "".join(p.read_text(encoding="ascii").strip() for p in parts)
        archive_bytes = base64.b64decode(encoded, validate=True)
        launcher = (ROOT / "Start-NOVA.ps1").read_text(encoding="utf-8")
        match = re.search(r'expected = "([0-9a-f]{64})"', launcher)
        self.assertIsNotNone(match, "launcher source checksum is missing")
        self.assertEqual(hashlib.sha256(archive_bytes).hexdigest(), match.group(1))

        expected_files = (
            "app/nova_backend.py",
            "web/index.html",
            "tests/test_backend.py",
            "tests/test_packaging.py",
        )
        with tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:xz") as archive:
            members = {m.name: m for m in archive.getmembers() if m.isfile()}
            self.assertEqual(set(members), set(expected_files))
            for name in expected_files:
                bundled = archive.extractfile(members[name]).read()
                self.assertEqual(bundled, (ROOT / name).read_bytes(), name)

    def test_release_version_is_consistent(self):
        version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
        backend = (ROOT / "app/nova_backend.py").read_text(encoding="utf-8")
        launcher = (ROOT / "Start-NOVA.ps1").read_text(encoding="utf-8")
        self.assertIn(f'VERSION = "{version}"', backend)
        self.assertIn(f"version -eq '{version}'", launcher)

    def test_katex_extraction_uses_valid_python_mode(self):
        launcher = (ROOT / "Start-NOVA.ps1").read_text(encoding="utf-8")
        self.assertIn('with tarfile.open(source, "r:gz") as archive:', launcher)
        self.assertNotIn("tarfile.open(source, r:gz)", launcher)


if __name__ == "__main__":
    unittest.main(verbosity=2)
