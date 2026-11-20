# Changelog

## 3.0.2 — Reliability update

- Fixed the first-run KaTeX archive-mode syntax error and require its JavaScript, CSS, and font assets before setup succeeds.
- Added retrying, staged downloads. The Python installer must have a valid Python Software Foundation Authenticode signature; llama.cpp and embedding files are SHA-256 checked.
- Verify that llama-server.exe can run, including when a previous copy is already present.
- Check the local health endpoint version before attaching to a running service or opening the desktop window.
- Serialize llama.cpp start/stop operations and reserve model download/import jobs before worker threads begin, avoiding duplicate processes and racing transfers.
- Write preferences atomically and use SQLite's online backup API for consistent database snapshots.
- Add package-integrity/version checks, and run backend regression tests plus a PowerShell 5.1 syntax parse on Windows CI.

The Windows launcher has not yet been exercised end-to-end on a physical Windows PC with a downloaded GGUF model.
