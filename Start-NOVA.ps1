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
function Get-Download([string]$Uri, [string]$Destination, [long]$MinimumBytes = 1,
                      [string]$ExpectedSha256 = '', [int]$Retries = 3) {
    $Partial = "$Destination.download"
    $LastError = ''
    for ($Attempt = 1; $Attempt -le $Retries; $Attempt++) {
        try {
            if (Test-Path $Partial) { Remove-Item $Partial -Force }
            Invoke-WebRequest -UseBasicParsing -Uri $Uri -OutFile $Partial -TimeoutSec 600
            $Item = Get-Item $Partial -ErrorAction Stop
            if ($Item.Length -lt $MinimumBytes) { throw "Downloaded file is too small ($($Item.Length) bytes)." }
            if ($ExpectedSha256) {
                $Actual = (Get-FileHash -Path $Partial -Algorithm SHA256).Hash.ToLowerInvariant()
                if ($Actual -ne $ExpectedSha256.ToLowerInvariant()) { throw 'SHA-256 checksum mismatch.' }
            }
            Move-Item -Path $Partial -Destination $Destination -Force
            return
        } catch {
            $LastError = $_.Exception.Message
            if (Test-Path $Partial) { Remove-Item $Partial -Force -ErrorAction SilentlyContinue }
            if ($Attempt -lt $Retries) {
                Write-Warning "Download attempt $Attempt of $Retries failed: $LastError. Retrying..."
                Start-Sleep -Seconds ([Math]::Min(12, 2 * $Attempt))
            }
        }
    }
    Fail "Download failed after $Retries attempts: $Uri`n$LastError"
}
function Test-Python312([string]$Executable) {
    if (!$Executable -or !(Test-Path $Executable)) { return $false }
    & $Executable -c 'import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 12) else 1)' 2>$null
    return ($LASTEXITCODE -eq 0)
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
if (Test-Python312 $LocalPython) { $Python = $LocalPython }
if (!$Python) {
    $PyLauncher = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($PyLauncher) {
        $Candidate = & $PyLauncher.Source -3.12 -c 'import sys; print(sys.executable)' 2>$null
        if ($LASTEXITCODE -eq 0) {
            $Candidate = ($Candidate | Select-Object -Last 1).Trim()
            if (Test-Python312 $Candidate) { $Python = $Candidate }
        }
    }
}
if (!$Python) {
    $PythonCommand = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($PythonCommand) {
        $Candidate = & $PythonCommand.Source -c 'import sys; print(sys.version_info[:2]); print(sys.executable)' 2>$null
        if ($LASTEXITCODE -eq 0 -and (($Candidate -join ' ') -match '\(3, 12\)')) { $Probe = ($Candidate | Select-Object -Last 1).Trim(); if (Test-Python312 $Probe) { $Python = $Probe } }
    }
}
if (!$Python) {
    Write-Step 'Installing a private Python 3.12 runtime (one time)'
    $PythonInstaller = Join-Path $env:TEMP 'nova-python-3.12.10-amd64.exe'
    Get-Download 'https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe' $PythonInstaller 20000000
    $PythonSignature = Get-AuthenticodeSignature -FilePath $PythonInstaller
    if ($PythonSignature.Status -ne 'Valid' -or $PythonSignature.SignerCertificate.Subject -notmatch 'Python Software Foundation') { Remove-Item $PythonInstaller -Force -ErrorAction SilentlyContinue; Fail 'The Python installer signature could not be verified.' }
    $PythonHome = Split-Path $LocalPython -Parent
    New-Item -ItemType Directory -Force -Path $PythonHome | Out-Null
    $InstallArgs = @('/quiet', 'InstallAllUsers=0', "TargetDir=`"$PythonHome`"", 'PrependPath=0', 'Include_pip=1', 'Include_launcher=0', 'Include_test=0', 'Include_doc=0', 'Include_tcltk=0')
    $InstallerProcess = Start-Process -FilePath $PythonInstaller -ArgumentList $InstallArgs -Wait -PassThru
    if ($InstallerProcess.ExitCode -ne 0 -or !(Test-Python312 $LocalPython)) { Fail 'Python installation failed or the installed runtime did not pass its version check. Install Python 3.12 from python.org and run Start NOVA.bat again.' }
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
& $Python -m pip install --disable-pip-version-check --retries 5 --timeout 30 -r (Join-Path $Root 'requirements.txt')
if ($LASTEXITCODE -ne 0) { Fail 'Could not install NOVA Python requirements. Check the internet connection and try again.' }
& $Python -c 'import pypdf; print("[NOVA] Python packages verified")'
if ($LASTEXITCODE -ne 0) { Fail 'The Python package check failed after installation.' }

# Cache the offline KaTeX browser assets after first setup.
$KatexDir = Join-Path $Root 'web\vendor\katex'
$KatexReady = (Test-Path (Join-Path $KatexDir 'katex.min.js')) -and (Test-Path (Join-Path $KatexDir 'katex.min.css'))
if (!$KatexReady) {
    Write-Step 'Downloading offline math-rendering files'
    $KatexArchive = Join-Path $Root '.cache\katex-0.19.1.tgz'
    Get-Download 'https://registry.npmjs.org/katex/-/katex-0.19.1.tgz' $KatexArchive 100000
    $KatexExtract = Join-Path $Root '.cache\katex-extract'
    if (Test-Path $KatexExtract) { Remove-Item $KatexExtract -Recurse -Force }
    if (Test-Path $KatexDir) { Remove-Item $KatexDir -Recurse -Force }
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
    if ($LASTEXITCODE -ne 0 -or !(Test-Path (Join-Path $KatexDir 'katex.min.js')) -or !(Test-Path (Join-Path $KatexDir 'katex.min.css')) -or !(Test-Path (Join-Path $KatexDir 'fonts\KaTeX_Main-Regular.woff2'))) { Fail 'Could not install offline KaTeX assets. Check the download and try again.' }
}

# Fetch a pinned official llama.cpp Windows CPU build and verify its SHA-256.
$LlamaServer = Join-Path $Root 'llama-server.exe'
$EngineReady = $false
if (Test-Path $LlamaServer) {
    try { & $LlamaServer --version 2>&1 | Out-Null; $EngineReady = ($LASTEXITCODE -eq 0) }
    catch { $EngineReady = $false }
}
if (!$EngineReady) {
    Write-Step 'Downloading verified llama.cpp Windows CPU engine'
    $LlamaArchive = Join-Path $Root '.cache\llama-b12565-win-cpu-x64.zip'
    $LlamaUrl = 'https://github.com/ggml-org/llama.cpp/releases/download/b12565/llama-b12565-bin-win-cpu-x64.zip'
    $ExpectedHash = 'ba675a702e8f3b2704da64f20fea1e532e63070e47f10f101644162f19415fbe'
    Get-Download $LlamaUrl $LlamaArchive 10000000 $ExpectedHash 3
    $LlamaExtract = Join-Path $Root '.cache\llama-extract'
    if (Test-Path $LlamaExtract) { Remove-Item $LlamaExtract -Recurse -Force }
    Expand-Archive -Path $LlamaArchive -DestinationPath $LlamaExtract -Force
    $Server = Get-ChildItem -Path $LlamaExtract -Filter 'llama-server.exe' -File -Recurse | Select-Object -First 1
    if (!$Server) { Fail 'The official llama.cpp archive did not contain llama-server.exe.' }
    if (Test-Path $LlamaServer) { Remove-Item $LlamaServer -Force }
    Copy-Item $Server.FullName $LlamaServer -Force
    Get-ChildItem -Path $LlamaExtract -Filter '*.dll' -File -Recurse | ForEach-Object { Copy-Item $_.FullName (Join-Path $Root $_.Name) -Force }
    Get-ChildItem -Path $LlamaExtract -Include 'LICENSE*','COPYING*' -File -Recurse | ForEach-Object { Copy-Item $_.FullName (Join-Path $Root $_.Name) -Force }
    & $LlamaServer --version 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) { Fail 'llama.cpp could not run. The extracted engine or its Windows DLL dependencies are incomplete.' }
}

# Semantic retrieval is optional; this known public embedding model has a pinned checksum.
$EmbedModel = Join-Path $Root 'models\embed\all-MiniLM-L6-v2-Q8_0.gguf'
if (!(Test-Path $EmbedModel)) {
    Write-Step 'Downloading the optional local embedding model'
    $EmbedTemp = "$EmbedModel.part"
    try {
        Get-Download 'https://huggingface.co/LLukas22/all-MiniLM-L6-v2-GGUF/resolve/main/all-minilm-l6-v2_q8_0.gguf' $EmbedTemp 1000000 '771705d3231fb60715dad2e960f5220cfbaa866786257082e845d91fc8b0d0ee' 3
        Move-Item $EmbedTemp $EmbedModel -Force
    } catch {
        if (Test-Path $EmbedTemp) { Remove-Item $EmbedTemp -Force }
        Write-Warning "Embedding model setup was skipped. NOVA will use keyword fallback: $($_.Exception.Message)"
    }
}

# Do not start a second copy if this NOVA instance is already available.
try {
    $Existing = Invoke-RestMethod -Uri 'http://127.0.0.1:8765/api/health' -TimeoutSec 2
    if ($Existing.version -eq '3.0.2') {
        Write-Host '[NOVA] This NOVA version is already running at http://127.0.0.1:8765'
        Start-Process 'http://127.0.0.1:8765'
        exit 0
    }
    if ($Existing.version) { Fail "Another NOVA version ($($Existing.version)) is already using port 8765. Close it with Stop NOVA.bat before starting this version." }
    Fail 'Port 8765 is being used by another application. Close that application before starting NOVA.'
} catch {
    if ($_.Exception.Message -like '*Another NOVA version*' -or $_.Exception.Message -like '*Port 8765*') { throw }
}

Write-Step 'Starting NOVA Desktop 3.0.2'
$LogOut = Join-Path $Root 'data\backend.log'
$LogErr = Join-Path $Root 'data\backend-error.log'
$env:NOVA_NO_OPEN = '1'
$BackendProcess = Start-Process -FilePath $Python -ArgumentList ('"{0}"' -f $BackendPath) -WorkingDirectory $Root -PassThru -WindowStyle Hidden -RedirectStandardOutput $LogOut -RedirectStandardError $LogErr
$Ready = $false
for ($i = 0; $i -lt 60; $i++) {
    Start-Sleep -Seconds 1
    if ($BackendProcess.HasExited) { break }
    try {
        $Health = Invoke-RestMethod -Uri 'http://127.0.0.1:8765/api/health' -TimeoutSec 2
        if ($Health.version -eq '3.0.2') { $Ready = $true; break }
        if ($Health.version) { throw "Unexpected NOVA version on port 8765: $($Health.version)" }
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

Write-Host "`nNOVA Desktop 3.0.2 is running. Keep this window open." -ForegroundColor Green
Write-Host 'Press ENTER here when you want to stop this NOVA session.'
[void](Read-Host)
try { Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:8765/api/quit' -ContentType 'application/json' -Body '{}' -TimeoutSec 5 | Out-Null } catch { }
try { $BackendProcess.WaitForExit(8000) | Out-Null } catch { }
if (!$BackendProcess.HasExited) { Stop-Process -Id $BackendProcess.Id -Force -ErrorAction SilentlyContinue }
Write-Host 'NOVA has stopped.' -ForegroundColor DarkGray
