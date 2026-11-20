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

    def test_startup_never_downloads_or_installs(self):
        launcher = (ROOT / "Start-NOVA.ps1").read_text(encoding="utf-8")
        self.assertNotIn("Invoke-WebRequest", launcher)
        self.assertNotIn("pip install", launcher)
        self.assertNotIn("Get-Download", launcher)
        self.assertIn("Install NOVA Prerequisites.bat", launcher)

    def test_prerequisite_installer_is_separate_and_verified(self):
        installer = (ROOT / "Install-NOVA-Prerequisites.ps1").read_text(encoding="utf-8")
        self.assertIn("Get-AuthenticodeSignature", installer)
        self.assertIn("pypdf==6.19.0", installer)
        self.assertIn("llama-b12565-bin-win-cpu-x64.zip", installer)
        self.assertIn("ba675a702e8f3b2704da64f20fea1e532e63070e47f10f101644162f19415fbe", installer)
        self.assertNotIn("Qwen3-", installer)
        self.assertIn("$EngineExe = Join-Path $Root 'llama-server.exe'", installer)
        embed_installer = (ROOT / "Install-NOVA-Embeddings.ps1").read_text(encoding="utf-8")
        self.assertIn("771705d3231fb60715dad2e960f5220cfbaa866786257082e845d91fc8b0d0ee", embed_installer)

    def test_model_import_is_documented(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("import your own", readme)
        self.assertIn("Start NOVA.bat", readme)

    def test_katex_uses_pinned_cdn_not_bootstrap_download(self):
        html = (ROOT / "web/index.html").read_text(encoding="utf-8")
        self.assertIn("katex@0.16.22", html)
        self.assertNotIn("/vendor/katex/", html)

    def test_readable_application_source_is_packaged(self):
        self.assertTrue((ROOT / "app/nova_backend.py").is_file())
        self.assertTrue((ROOT / "web/index.html").is_file())
        self.assertTrue((ROOT / "Start NOVA.bat").is_file())
        self.assertTrue((ROOT / "Install NOVA Prerequisites.bat").is_file())
        self.assertTrue((ROOT / "Install NOVA Embeddings.bat").is_file())


if __name__ == "__main__":
    unittest.main(verbosity=2)
