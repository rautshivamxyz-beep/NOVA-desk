# Changelog

## 3.1.0 Lite — small full-feature distribution

- Keep NOVA's full existing application interface and backend features while removing runtimes, llama.cpp binaries, embedding weights and AI chat-model weights from the application ZIP.
- Split prerequisites into a separate one-time installer. `Start NOVA.bat` now checks and launches only; it performs no downloads or installs.
- Install Python 3.12 + pypdf and a pinned, SHA-256-verified llama.cpp CPU engine once into the extracted NOVA folder.
- Keep GGUF model import in the app; no chat model is included or downloaded by setup.
- Keep keyword retrieval available without embeddings; add a separate one-click verified optional embedding installer.
- Pin the KaTeX browser assets to a CDN instead of downloading/vendor-copying them during startup.
