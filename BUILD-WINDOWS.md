# NOVA Desktop 3.0.2 — Windows build notes

## One-click user setup

The supported user flow is: download the repository using **Code → Download ZIP**, extract the ZIP, and double-click `Start NOVA.bat`. The launcher bootstraps the runtime and application, then opens NOVA in Edge or Chrome app mode.

First-run setup downloads or installs:

- Python 3.12.10 for the current Windows user if Python 3.12 is not already available.
- `pypdf==6.19.0` from `requirements.txt`.
- KaTeX 0.19.1 and its fonts for offline math rendering.
- Official llama.cpp CPU x64 build `b12565`, pinned by SHA-256 `ba675a702e8f3b2704da64f20fea1e532e63070e47f10f101644162f19415fbe`.
- Optional `all-MiniLM-L6-v2` Q8 embedding GGUF, pinned by SHA-256 `771705d3231fb60715dad2e960f5220cfbaa866786257082e845d91fc8b0d0ee`.

You then download a chat GGUF model from NOVA's Models screen or import your own model. First-time setup and model downloads require internet. Local chat is offline once the runtime and a model are installed.

## Source layout

- `app/nova_backend.py` — local HTTP/API backend, SQLite features, model process management, and tool router.
- `web/index.html` — NOVA desktop interface.
- `web/vendor/katex/` — offline KaTeX runtime assets, downloaded by the bootstrap if absent.
- `tests/test_backend.py` — backend regression tests.

The bootstrap retries failed downloads, stages them before replacing valid files, validates the Python installer signature, verifies the llama.cpp and embedding assets by SHA-256, and checks the KaTeX JS/CSS/font assets before use. It reassembles base64 text parts into a SHA-256-verified `tar.xz` archive and safely extracts it. GitHub Actions also parses the launcher with Windows PowerShell 5.1 and runs backend tests on Windows. GitHub Actions performs the same reconstruction, runs tests, and commits the readable source paths to `main`.

The backend serializes llama.cpp start/stop operations, reserves model download/import jobs before worker threads begin, writes preferences atomically, and creates consistent SQLite backup snapshots.\n\n## Run tests locally

```powershell
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
```

## Local endpoints

- NOVA web/API: `127.0.0.1:8765`
- llama.cpp chat engine: `127.0.0.1:8080`
- optional embeddings engine: `127.0.0.1:8081`

User data and downloaded models belong in `data/` and `models/`, never in version control.
