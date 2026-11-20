# NOVA Desktop 3.2.0 — Full Windows package

## Package contents

The GitHub Actions Windows build includes:

- Full NOVA backend and frontend source.
- Python 3.12.10 embeddable x64 runtime.
- `pypdf==6.19.0` staged into the bundled interpreter.
- llama.cpp CPU x64 build `b12565`, pinned by SHA-256.
- KaTeX 0.16.22 JS, CSS, fonts and auto-render helper for offline LaTeX display.
- Windows one-click launch, stop and desktop shortcut scripts.

No GGUF files are shipped. The user imports a chat model from NOVA's Models screen. The optional embedding model can be installed separately with `Install NOVA Embeddings.bat`.

## Build

The `.github/workflows/package-windows.yml` workflow runs on `windows-latest`, downloads pinned upstream assets, verifies Python and llama.cpp SHA-256 digests, assembles the self-contained folder, checks the bundled interpreter and engine, confirms no GGUF file entered the bundle, compresses the ZIP, generates a ZIP SHA-256 file and uploads a 30-day GitHub Actions artifact.

## Startup

`Start NOVA.bat` runs `Start-NOVA.ps1`. The PowerShell launcher performs local file/runtime/engine self-checks, ensures a compatible NOVA service is not already running, starts the bundled Python backend, waits for the expected health/version response, then opens the local UI. Startup performs no downloads or package installation.

## User data

Keep `data\\` and `models\\` when updating. These folders are not included in the generated release ZIP.
