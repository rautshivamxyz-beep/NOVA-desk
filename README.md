# NOVA Desktop 3.0 (Windows)

NOVA is a local-first Windows assistant powered by a local GGUF model and llama.cpp. Chat and document features run on the computer; web search and Wikipedia lookups need internet access.

## Features
- Streaming chat with Markdown and offline KaTeX math rendering.
- Local GGUF model download, import, selection, and engine restart.
- Tool routing for calculator, saved memory, documents, Wikipedia, and web search.
- PDF/text/Markdown document ingestion with semantic search when the bundled embedding model is available, and keyword fallback otherwise.
- Notes, memory, flashcards with spaced review intervals, quizzes, reminders, reusable prompts, learned skills, and web lookup history.
- Voice input and spoken replies through Edge/Chrome browser speech APIs.
- Health diagnostics and backup/restore.

## Windows launch
Use the complete Windows ZIP release. Extract it fully, run `Create Desktop Shortcut.bat` once, then launch from the NOVA desktop icon. For visible diagnostics, run `Start NOVA (show errors).bat`.

On first run choose Qwen3 1.7B or Qwen3 0.6B; the model downloads into `models`. You can import another `.gguf` from Models or drag it onto the app.

## Source checkout
See [BUILD-WINDOWS.md](BUILD-WINDOWS.md). Main files are `app/nova_backend.py` and `web/index.html`; regression tests are in `tests/`. The Windows package additionally includes portable Python, llama.cpp Windows binaries, the PDF library, offline KaTeX assets, and the embedding model.

## Verification
The 3.0 backend regression tests and a browser UI smoke test pass in the development environment. Actual llama.cpp inference, Windows process startup, and Windows browser integration still need final verification on a Windows PC.

## Licence
No licence has been selected for the NOVA project source yet. Public visibility does not grant permission to reuse, modify, or redistribute this project. Add a licence before describing it as open-source.

User data, downloaded models, and logs must never be committed.
