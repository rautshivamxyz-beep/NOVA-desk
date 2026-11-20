$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$Root = (Resolve-Path $PSScriptRoot).Path
Set-Location $Root

function Write-Step([string]$Message) {
    Write-Host "`n[NOVA] $Message" -ForegroundColor Cyan
}
function Fail([string]$Message) {
    Write-Host "`n[NOVA ERROR] $Message" -ForegroundColor Red
    exit 1
}
function Invoke-Checked([string]$File, [string[]]$Args) {
    & $File @Args
    if ($LASTEXITCODE -ne 0) { Fail "Command failed: $File $($Args -join ' ')" }
}

# The compact source bundle is expanded after Python bootstrap below.
$SourceArchive = Join-Path $Root 'NOVA-Desktop-3.0-core.tar.xz'
$SourceParts = @(Get-ChildItem -Path (Join-Path $Root 'NOVA-Desktop-3.0-core.b64.part*') -File -ErrorAction SilentlyContinue | Sort-Object Name)
$BackendPath = Join-Path $Root 'app\nova_backend.py'
if (!(Test-Path $BackendPath) -and $SourceParts.Count -eq 0) {
    Fail 'Source bundle is missing. Download the complete repository ZIP and extract it first.'
}

# Use an existing Python 3.12 installation, or install a private user-scoped copy.
$Python = $null
$LocalPython = Join-Path $env:LOCALAPPDATA 'Programs\NOVA\Python312\python.exe'
if (Test-Path $LocalPython) { $Python = $LocalPython }
if (!$Python) {
    $PyLauncher = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($PyLauncher) {
        $Candidate = & $PyLauncher.Source -3.12 -c 'import sys; print(sys.executable)' 2>$null
        if ($LASTEXITCODE -eq 0) {
            $Candidate = ($Candidate | Select-Object -Last 1).Trim()
            if (Test-Path $Candidate) { $Python = $Candidate }
        }
    }
}
if (!$Python) {
    $PythonCommand = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($PythonCommand) {
        $Candidate = & $PythonCommand.Source -c 'import sys; print(sys.version_info[:2]); print(sys.executable)' 2>$null
        if ($LASTEXITCODE -eq 0 -and (($Candidate -join ' ') -match '\(3, 12\)')) { $Python = ($Candidate | Select-Object -Last 1).Trim() }
    }
}
if (!$Python) {
    Write-Step 'Installing a private Python 3.12 runtime (one time)'
    $PythonInstaller = Join-Path $env:TEMP 'nova-python-3.12.10-amd64.exe'
    Invoke-WebRequest -UseBasicParsing -Uri 'https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe' -OutFile $PythonInstaller
    $PythonHome = Split-Path $LocalPython -Parent
    New-Item -ItemType Directory -Force -Path $PythonHome | Out-Null
    $InstallArgs = @('/quiet', 'InstallAllUsers=0', "TargetDir=`"$PythonHome`"", 'PrependPath=0', 'Include_pip=1', 'Include_launcher=0', 'Include_test=0', 'Include_doc=0', 'Include_tcltk=0')
    $InstallerProcess = Start-Process -FilePath $PythonInstaller -ArgumentList $InstallArgs -Wait -PassThru
    if ($InstallerProcess.ExitCode -ne 0 -or !(Test-Path $LocalPython)) { Fail 'Python installation failed. Install Python 3.12 from python.org and run Start NOVA.bat again.' }
    $Python = $LocalPython
}

if (!(Test-Path $BackendPath)) {
    Write-Step 'Expanding NOVA application source'
    $ExtractCode = @'
import base64, hashlib, pathlib, sys, tarfile
root = pathlib.Path(sys.argv[1]).resolve()
parts = sorted(root.glob("NOVA-Desktop-3.0-core.b64.part*"))
if not parts:
    raise SystemExit("The source archive parts are missing.")
encoded = "".join(p.read_text(encoding="ascii").strip() for p in parts)
data = base64.b64decode(encoded, validate=True)
expected = "a7089c2e86e5bf839b0524c68e1925db45f21cc61516b99258b4a7b58b9a31c2"
if hashlib.sha256(data).hexdigest() != expected:
    raise SystemExit("The source archive checksum did not match.")
archive_path = root / "NOVA-Desktop-3.0-core.tar.xz"
archive_path.write_bytes(data)
with tarfile.open(archive_path, "r:xz") as archive:
    for item in archive.getmembers():
        target = (root / item.name).resolve()
        if target != root and root not in target.parents:
            raise SystemExit("Unsafe path in source bundle: " + item.name)
    archive.extractall(root, filter="data")
'@
    & $Python -c $ExtractCode $Root
    if ($LASTEXITCODE -ne 0) { Fail 'Could not expand the NOVA source archive.' }
}

if (!(Test-Path $BackendPath)) { Fail 'The NOVA backend source is missing after extraction.' }
New-Item -ItemType Directory -Force -Path (Join-Path $Root 'data'), (Join-Path $Root 'models'), (Join-Path $Root 'models\embed'), (Join-Path $Root '.cache') | Out-Null

Write-Step 'Checking Python packages'
& $Python -m pip install --disable-pip-version-check -r (Join-Path $Root 'requirements.txt')
if ($LASTEXITCODE -ne 0) { Fail 'Could not install NOVA Python requirements.' }

# Cache the offline KaTeX browser assets after first setup.
$KatexDir = Join-Path $Root 'web\vendor\katex'
if (!(Test-Path (Join-Path $KatexDir 'katex.min.js'))) {
    Write-Step 'Downloading offline math-rendering files'
    $KatexArchive = Join-Path $Root '.cache\katex-0.19.1.tgz'
    Invoke-WebRequest -UseBasicParsing -Uri 'https://registry.npmjs.org/katex/-/katex-0.19.1.tgz' -OutFile $KatexArchive
    $KatexExtract = Join-Path $Root '.cache\katex-extract'
    if (Test-Path $KatexExtract) { Remove-Item $KatexExtract -Recurse -Force }
    New-Item -ItemType Directory -Force -Path $KatexExtract, $KatexDir | Out-Null
    $ExtractKatex = @'
import pathlib, sys, tarfile
source, destination = sys.argv[1], pathlib.Path(sys.argv[2])
with tarfile.open(source, 'r:gz') as archive:
    for item in archive.getmembers():
        prefix = "package/dist/"
        if not item.name.startswith(prefix) or not item.isfile():
            continue
        relative = pathlib.PurePosixPath(item.name[len(prefix):])
        if relative.is_absolute() or ".." in relative.parts:
            raise SystemExit("Unsafe KaTeX path")
        target = destination.joinpath(*relative.parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        with archive.extractfile(item) as incoming, target.open("wb") as outgoing:
            outgoing.write(incoming.read())
'@
    & $Python -c $ExtractKatex $KatexArchive $KatexDir
    if ($LASTEXITCODE -ne 0 -or !(Test-Path (Join-Path $KatexDir 'katex.min.js'))) { Fail 'Could not install offline KaTeX assets.' }
}

# Fetch a pinned official llama.cpp Windows CPU build and verify its SHA-256.
$LlamaServer = Join-Path $Root 'llama-server.exe'
if (!(Test-Path $LlamaServer)) {
    Write-Step 'Downloading verified llama.cpp Windows CPU engine'
    $LlamaArchive = Join-Path $Root '.cache\llama-b12565-win-cpu-x64.zip'
    $LlamaUrl = 'https://github.com/ggml-org/llama.cpp/releases/download/b12565/llama-b12565-bin-win-cpu-x64.zip'
    $ExpectedHash = 'ba675a702e8f3b2704da64f20fea1e532e63070e47f10f101644162f19415fbe'
    Invoke-WebRequest -UseBasicParsing -Uri $LlamaUrl -OutFile $LlamaArchive
    $ActualHash = (Get-FileHash -Path $LlamaArchive -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($ActualHash -ne $ExpectedHash) { Remove-Item $LlamaArchive -Force; Fail 'llama.cpp download checksum did not match. The file was discarded.' }
    $LlamaExtract = Join-Path $Root '.cache\llama-extract'
    if (Test-Path $LlamaExtract) { Remove-Item $LlamaExtract -Recurse -Force }
    Expand-Archive -Path $LlamaArchive -DestinationPath $LlamaExtract -Force
    $Server = Get-ChildItem -Path $LlamaExtract -Filter 'llama-server.exe' -File -Recurse | Select-Object -First 1
    if (!$Server) { Fail 'The official llama.cpp archive did not contain llama-server.exe.' }
    Copy-Item $Server.FullName $LlamaServer -Force
    Get-ChildItem -Path $LlamaExtract -Filter '*.dll' -File -Recurse | ForEach-Object { Copy-Item $_.FullName (Join-Path $Root $_.Name) -Force }
    Get-ChildItem -Path $LlamaExtract -Include 'LICENSE*','COPYING*' -File -Recurse | ForEach-Object { Copy-Item $_.FullName (Join-Path $Root $_.Name) -Force }
}

# Semantic retrieval is optional; this known public embedding model has a pinned checksum.
$EmbedModel = Join-Path $Root 'models\embed\all-MiniLM-L6-v2-Q8_0.gguf'
if (!(Test-Path $EmbedModel)) {
    Write-Step 'Downloading the optional local embedding model'
    $EmbedTemp = "$EmbedModel.part"
    try {
        Invoke-WebRequest -UseBasicParsing -Uri 'https://huggingface.co/LLukas22/all-MiniLM-L6-v2-GGUF/resolve/main/all-minilm-l6-v2_q8_0.gguf' -OutFile $EmbedTemp
        $EmbedHash = (Get-FileHash -Path $EmbedTemp -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($EmbedHash -ne '771705d3231fb60715dad2e960f5220cfbaa866786257082e845d91fc8b0d0ee') { throw 'Embedding model checksum did not match.' }
        Move-Item $EmbedTemp $EmbedModel -Force
    } catch {
        if (Test-Path $EmbedTemp) { Remove-Item $EmbedTemp -Force }
        Write-Warning "Embedding model setup was skipped. NOVA will use keyword fallback: $($_.Exception.Message)"
    }
}

# Do not start a second copy if this NOVA instance is already available.
try {
    Invoke-RestMethod -Uri 'http://127.0.0.1:8765/api/health' -TimeoutSec 2 | Out-Null
    Write-Host '[NOVA] Already running at http://127.0.0.1:8765'
    Start-Process 'http://127.0.0.1:8765'
    exit 0
} catch { }

Write-Step 'Starting NOVA Desktop 3.0'
$LogOut = Join-Path $Root 'data\backend.log'
$LogErr = Join-Path $Root 'data\backend-error.log'
$env:NOVA_NO_OPEN = '1'
$BackendProcess = Start-Process -FilePath $Python -ArgumentList ('"{0}"' -f $BackendPath) -WorkingDirectory $Root -PassThru -WindowStyle Hidden -RedirectStandardOutput $LogOut -RedirectStandardError $LogErr
$Ready = $false
for ($i = 0; $i -lt 60; $i++) {
    Start-Sleep -Seconds 1
    if ($BackendProcess.HasExited) { break }
    try {
        Invoke-RestMethod -Uri 'http://127.0.0.1:8765/api/health' -TimeoutSec 2 | Out-Null
        $Ready = $true
        break
    } catch { }
}
if (!$Ready) {
    Write-Host '[NOVA] Startup failed. Recent logs:' -ForegroundColor Red
    if (Test-Path $LogOut) { Get-Content $LogOut -Tail 35 }
    if (Test-Path $LogErr) { Get-Content $LogErr -Tail 35 }
    if (!$BackendProcess.HasExited) { Stop-Process -Id $BackendProcess.Id -Force -ErrorAction SilentlyContinue }
    Fail 'NOVA did not start. Check data\backend.log and data\backend-error.log.'
}

$EdgePaths = @("${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe", "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe")
$ChromePaths = @("$env:ProgramFiles\Google\Chrome\Application\chrome.exe", "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe")
$Browser = ($EdgePaths + $ChromePaths | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1)
if ($Browser) { Start-Process -FilePath $Browser -ArgumentList '--app=http://127.0.0.1:8765','--window-size=1240,860' }
else { Start-Process 'http://127.0.0.1:8765' }

Write-Host "`nNOVA Desktop 3.0 is running. Keep this window open." -ForegroundColor Green
Write-Host 'Press ENTER here when you want to stop this NOVA session.'
[void](Read-Host)
try { Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:8765/api/quit' -ContentType 'application/json' -Body '{}' -TimeoutSec 5 | Out-Null } catch { }
try { $BackendProcess.WaitForExit(8000) | Out-Null } catch { }
if (!$BackendProcess.HasExited) { Stop-Process -Id $BackendProcess.Id -Force -ErrorAction SilentlyContinue }
Write-Host 'NOVA has stopped.' -ForegroundColor DarkGray
