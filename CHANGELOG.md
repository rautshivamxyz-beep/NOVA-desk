# Changelog

## 3.2.0 Full — complete Windows package without chat model

- Restored the intended full-package design: bundled Python runtime, pypdf, llama.cpp CPU engine, offline KaTeX assets, complete application source and all existing NOVA feature modules.
- Excluded chat GGUF weights so users can import their own models.
- Kept the optional embedding model as a separate, user-triggered install.
- Changed startup to use the bundled runtime and engine with local checks only. No first-launch downloads or pip install.
- Added a Windows Actions package workflow that validates bundled Python, llama.cpp startup, and absence of GGUF model files before producing the ZIP.
