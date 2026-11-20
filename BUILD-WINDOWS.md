# Building and testing NOVA Desktop on Windows

This repository contains the NOVA application source and regression tests. The downloadable Windows package additionally bundles the portable Python runtime, pypdf, llama.cpp executable/DLLs, offline KaTeX assets, and the embedding GGUF model.

## Requirements
- Windows 10/11 (64-bit)
- Python 3.12 (or the bundled runtime from the release ZIP)
- pypdf==6.19.0 for PDF text extraction
- A Windows llama-server.exe build and its matching DLLs in the application root

Install the Python dependency:

```powershell
python -m pip install -r requirements.txt
```

Run the backend from the repository root:

```powershell
python app\nova_backend.py
```

Run regression tests:

```powershell
python -m unittest discover -s tests -v
```

For the one-click desktop experience, use the complete NOVA-Desktop-Windows release ZIP rather than this source-only checkout. Run Create Desktop Shortcut.bat once, then launch NOVA from the desktop icon or run start-nova-windows.bat.

User data, downloaded chat models, and runtime logs belong in data/ and models/; they must not be committed.
