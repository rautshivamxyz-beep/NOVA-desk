import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class PackagingTests(unittest.TestCase):
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
        start = launcher.index("$ExtractKatex = @'\n") + len("$ExtractKatex = @'\n")
        end = launcher.index("\n'@", start)
        embedded_python = launcher[start:end]
        compile(embedded_python, "<NOVA embedded KaTeX extractor>", "exec")

    def test_readable_application_source_is_packaged(self):
        self.assertTrue((ROOT / "app/nova_backend.py").is_file())
        self.assertTrue((ROOT / "web/index.html").is_file())
        self.assertTrue((ROOT / "Start NOVA.bat").is_file())

    def test_bootstrap_has_retries_and_verification(self):
        launcher = (ROOT / "Start-NOVA.ps1").read_text(encoding="utf-8")
        self.assertIn("function Get-Download", launcher)
        self.assertIn("Get-AuthenticodeSignature", launcher)
        self.assertIn("$ExpectedHash", launcher)
        self.assertIn("$KatexReady", launcher)
        self.assertIn("application source is missing", launcher)


if __name__ == "__main__":
    unittest.main(verbosity=2)
