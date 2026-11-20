# NOVA Desktop 3.1.0 Lite — full-feature app, small package

NOVA Lite keeps the existing NOVA Desktop interface and backend features while excluding large runtimes, llama.cpp binaries, embedding weights, and AI chat-model weights from the application ZIP. The application ZIP is only source and launch scripts; local prerequisites are installed once separately.

## Quick start

1. Download **Code → Download ZIP** or the `NOVA-Desktop-3.1.0-Lite-Windows.zip` package and extract it to a writable folder such as `Documents\\NOVA`.
2. Double-click **Install NOVA Prerequisites.bat** once. It installs Python 3.12 + PDF support and a verified llama.cpp Windows CPU engine. It does not download an AI chat model.
3. Double-click **Start NOVA.bat**. Startup only checks prerequisites and launches the app; it does not download or install dependencies.
4. Open **Models** and import your own `.gguf` model. You can also choose to download a model from NOVA's Models screen.

The prerequisite installer needs internet and downloads the runtime components once. You do not repeat this step every time NOVA starts. After a GGUF model is imported, local AI chat runs on the PC. Web search and Wikipedia need internet.

## Features retained

- Streaming local chat, Markdown, LaTeX, answer styles, tone settings, profile and tutor mode.
- GGUF import, selection, model switching, and optional model downloads from Hugging Face.
- Tool routing: calculator, memory, documents, Wikipedia and web search.
- PDF/text/Markdown document Q&A and retrieval.
- Notes, long-term memory, flashcards, quizzes, exams and spaced repetition.
- Reminders, recipes, web history, reusable prompts and skills.
- Browser voice input and spoken replies.
- Health diagnostics and backup/restore.

Phone calls and SMS are not included in this desktop build.

## Optional semantic embeddings

To enable vector/semantic retrieval, double-click **Install NOVA Embeddings.bat** once. It downloads and verifies an optional embedding GGUF separately; llama.cpp starts it when NOVA starts. This is separate from your chat model. Keyword retrieval remains available without it.

## Runtime and data locations

- Python: `%LOCALAPPDATA%\\Programs\\NOVA\\Python312`
- llama.cpp runtime: the extracted NOVA application folder (placed there by the separate one-time prerequisite installer)
- Chat GGUF models: `models\\`
- Optional embedding GGUF: `models\\embed\\`
- NOVA database, preferences and logs: `data\\`

Do not delete `data` or `models` when updating the app. Back them up before replacing the application folder. Keep the application extracted to a normal writable folder, not inside a ZIP preview or a protected Windows folder.

## Technical notes

`Start NOVA.bat` never runs pip, downloads the engine, downloads embedding weights, or downloads a chat model. Run the separate prerequisites installer only once, or when repairing prerequisites. LaTeX display uses a pinned KaTeX CDN resource; its first display requires internet and the browser may cache it. Core local chat does not depend on that CDN.

Tests: `python -m unittest discover -s tests -v`.

No separate NOVA project licence has yet been selected. Public repository visibility alone does not grant reuse or redistribution rights. Review the licences for Python, pypdf, llama.cpp and KaTeX before redistribution.

Version: **3.1.0 Lite**.
