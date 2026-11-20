# NOVA Desktop 3.1.0 Lite — Windows build notes

## Package design

The release ZIP contains application source and launch scripts only. It excludes Python, pypdf, llama.cpp binaries/DLLs, embedding weights and chat-model weights to keep the package small. `Install NOVA Prerequisites.bat` is a separate one-time setup workflow; `Start NOVA.bat` only checks that setup is complete and starts the backend.

## Requirements installed once

- Python 3.12 (the installer can install a private user copy).
- `pypdf==6.19.0`.
- The pinned llama.cpp CPU x64 build `b12565`, verified by SHA-256 `ba675a702e8f3b2704da64f20fea1e532e63070e47f10f101644162f19415fbe`.

The Python installer signature is checked against the Python Software Foundation. Download files are staged and verified before being moved into their final location. No AI chat model is installed by the prerequisite script.

## Engine location

The app expects `llama-server.exe` and its required DLLs beside the NOVA launcher. The prerequisite installer places these files in the extracted app folder after verifying the downloaded archive. Do not delete the engine files after setup.

## Tests

```powershell
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
```

CI parses all PowerShell scripts on Windows and runs backend tests on Windows and Linux.

## Data

Keep `data\\` and `models\\` when updating the app. Back up these folders separately. Do not commit user databases, imported models or local logs.
