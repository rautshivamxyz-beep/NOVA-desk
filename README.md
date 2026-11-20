# NOVA Desktop 3.2.0 — Full Windows build (chat model not included)

This is the complete NOVA Desktop application package. It includes the app source, isolated Python runtime, PDF support, llama.cpp Windows CPU engine and offline KaTeX assets. **The AI chat GGUF model is deliberately not included** so you can import your own.

## One-click install

1. Download `NOVA-Desktop-3.2.0-Windows.zip` and extract the entire ZIP to a normal writable folder (for example, `Documents\\NOVA`).
2. Double-click **Start NOVA.bat**. No Python setup, pip install, llama.cpp download or KaTeX download is performed during startup.
3. Open **Models** and import your own `.gguf` model. You can also use NOVA's model downloader if you prefer.
4. Optional: double-click **Create Desktop Shortcut.bat** once to add a NOVA desktop icon.

The package is self-contained except for the chat model weights. It requires Windows x64 and a browser (Microsoft Edge or Google Chrome). If Windows reports a missing Visual C++ runtime, install the Microsoft Visual C++ 2015–2022 x64 Redistributable once.

## Features retained

- Streaming local chat with Markdown and LaTeX, answer modes, tone, profile and tutor mode.
- GGUF import, model selection, engine restart and optional Hugging Face model downloads.
- Tool routing for calculator, memory, documents, Wikipedia and web search.
- PDF/text/Markdown document Q&A and retrieval.
- Notes, memory, semantic search support, flashcards, quizzes, exams and spaced repetition.
- Reminders, recipes, web history, reusable prompts and skills.
- Voice input and spoken replies through the browser.
- Health diagnostics, backup and restore.

Phone calls and SMS are not included in this desktop build.

## Optional semantic embeddings

No GGUF weights are bundled. To enable the optional vector/semantic retrieval engine, run **Install NOVA Embeddings.bat** once. It downloads and verifies the small embedding GGUF separately; keyword search and the other document features remain available without it.

## User data

NOVA stores your database, notes, memory, documents, settings and logs in the `data\\` folder, and your imported chat models in `models\\`. Keep those folders when updating NOVA. Back them up before replacing the app folder. Do not place the app inside a ZIP preview or a protected Windows directory.

## Build and tests

The full Windows ZIP is produced by GitHub Actions from the checked-in application source and pinned runtime assets. The workflow tests the bundled Python runtime, checks the llama.cpp binary, includes offline KaTeX and verifies that no GGUF model files entered the package.

Run source tests with:

```powershell
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
```

No separate NOVA project licence has yet been selected. Public repository visibility alone does not grant reuse or redistribution rights. Review the licences for Python, pypdf, llama.cpp and KaTeX before redistributing the package.

Version: **3.2.0 Full**.
