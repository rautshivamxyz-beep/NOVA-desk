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

    def test_startup_uses_bundled_runtime_and_does_not_download(self):
        launcher = (ROOT / "Start-NOVA.ps1").read_text(encoding="utf-8")
        self.assertIn("runtime\\python\\python.exe", launcher)
        self.assertIn("llama-server.exe", launcher)
        self.assertNotIn("Invoke-WebRequest", launcher)
        self.assertNotIn("pip install", launcher)
        self.assertNotIn("Get-Download", launcher)

    def test_katex_assets_are_packaged_by_windows_build(self):
        html = (ROOT / "web/index.html").read_text(encoding="utf-8")
        self.assertIn("/vendor/katex/katex.min.css", html)
        self.assertIn("/vendor/katex/katex.min.js", html)
        workflow = (ROOT / ".github/workflows/package-windows.yml").read_text(encoding="utf-8")
        self.assertIn("katex-0.16.22.tgz", workflow)
        self.assertIn("vendor\\katex", workflow)

    def test_windows_build_bundles_runtime_and_excludes_models(self):
        workflow = (ROOT / ".github/workflows/package-windows.yml").read_text(encoding="utf-8")
        self.assertIn("python-3.12.10-embed-amd64.zip", workflow)
        self.assertIn("pypdf==6.19.0", workflow)
        self.assertIn("llama-b12565-bin-win-cpu-x64.zip", workflow)
        self.assertIn("No GGUF model files", workflow)
        self.assertIn("upload-artifact@v4", workflow)

    def test_model_import_is_kept(self):
        html = (ROOT / "web/index.html").read_text(encoding="utf-8")
        self.assertIn("gguf", html.lower())
        backend = (ROOT / "app/nova_backend.py").read_text(encoding="utf-8")
        self.assertIn("def start_download", backend)
        self.assertIn("def start_engine", backend)

    def test_core_features_are_kept(self):
        backend = (ROOT / "app/nova_backend.py").read_text(encoding="utf-8")
        for token in ("flashcard", "reminder", "backup", "memory", "recipe", "document"):
            self.assertIn(token, backend.lower())
        html = (ROOT / "web/index.html").read_text(encoding="utf-8")
        for token in ("Study", "Documents", "Memory", "Models", "Health"):
            self.assertIn(token, html)


if __name__ == "__main__":
    unittest.main(verbosity=2)
