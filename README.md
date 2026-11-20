# NOVA Desktop 3.0.2 — Windows one-click

NOVA is a local-first Windows assistant. The desktop interface runs in Microsoft Edge or Google Chrome, while local chat inference is powered by your chosen GGUF model through llama.cpp.

## Start NOVA (one click)

1. Open this repository: https://github.com/rautshivamxyz-beep/NOVA-desk
2. Select **Code → Download ZIP** and extract the ZIP completely to a normal writable folder (for example, Documents\NOVA).
3. Double-click **Start NOVA.bat**.
4. On the first launch, NOVA sets up its private Python 3.12 runtime if required, installs PDF support, downloads offline math-rendering files, downloads and verifies the llama.cpp Windows CPU engine, and attempts to install the optional embedding model.
5. NOVA opens in an Edge/Chrome app window. Open **Models** and download Qwen3 1.7B or Qwen3 0.6B, or import a `.gguf` file you already have.

After setup, **Start NOVA.bat** is the one-click launcher. First-time setup and chat-model downloads require internet. Once your model and runtime are installed, local chat and saved data stay on this PC and work offline. Web search and Wikipedia need internet.

To add a desktop shortcut, double-click **Create Desktop Shortcut.bat** once. Keep the launcher console open while NOVA runs; press Enter in that console to stop the NOVA instance cleanly. **Stop NOVA.bat** is also available.

## Features

- Offline local-model chat with streaming, Markdown, and LaTeX.
- GGUF model download, import, selection, and engine restart, with overlapping transfers rejected cleanly.
- Tool routing for calculator, memory, documents, Wikipedia, and web search.
- PDF/text/Markdown document Q&A and retrieval.
- Notes, memory, flashcards with spaced review, quizzes, reminders, reusable prompts, and skills.
- Browser voice input and spoken replies.
- Health diagnostics and backup/restore. Settings are written atomically and database backups use SQLite snapshot support.

Phone calls and SMS are not included in this desktop build.

## Source, updates and tests

The readable source is committed directly in `app/`, `web/`, and `tests/`. GitHub Actions runs backend regression tests on Linux and Windows and parses the launcher with Windows PowerShell 5.1. There is no separate source bootstrap archive to go stale.

See [BUILD-WINDOWS.md](BUILD-WINDOWS.md) for development, troubleshooting, and dependency details. Run tests with:

```powershell
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
```

## Data and privacy

Notes, memory, documents, preferences, downloaded models, and logs are stored locally in `data/` and `models/`. These folders and downloaded runtime binaries are excluded from Git. Do not commit your personal data or model files.

## Dependencies and licensing

The launcher downloads Python from python.org, the pinned llama.cpp Windows CPU release from `ggml-org/llama.cpp` (SHA-256 verified), KaTeX from npm, and the optional embedding model from Hugging Face (SHA-256 verified). Review their individual licences and notices. No separate NOVA project licence has yet been selected; public visibility alone does not grant reuse or redistribution rights.

Version: **3.0.2**.


## 3.0.1 startup hotfix

Fixed the first-run offline KaTeX installer: its Python `tarfile.open` mode is now correctly quoted as `'r:gz'`.\n\nFirst-run downloads now retry and stage temporary files before replacing assets. Python's installer signature is verified, llama.cpp and the embedding model are SHA-256 checked, and the launcher verifies the NOVA version on its local port before opening the UI.\n\nIf you already extracted an older ZIP, extract the latest ZIP into a fresh folder before launching.
