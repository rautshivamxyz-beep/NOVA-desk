$ErrorActionPreference = 'Stop'
$Root = (Resolve-Path $PSScriptRoot).Path
Set-Location $Root

function Fail([string]$Message) {
    Write-Host ''
    Write-Host "[NOVA ERROR] $Message" -ForegroundColor Red
    exit 1
}
function Test-NovaPython([string]$Executable) {
    if (!$Executable -or !(Test-Path -LiteralPath $Executable -PathType Leaf)) { return $false }
    & $Executable -c 'import sys,pypdf; raise SystemExit(0 if sys.version_info[:2] == (3,12) else 1)' 2>$null
    return ($LASTEXITCODE -eq 0)
}

$BackendPath = Join-Path $Root 'app\nova_backend.py'
if (!(Test-Path -LiteralPath $BackendPath -PathType Leaf)) {
    Fail 'NOVA application files are missing. Extract the complete ZIP again.'
}

$Python = $null
$LocalPython = Join-Path $env:LOCALAPPDATA 'Programs\NOVA\Python312\python.exe'
if (Test-NovaPython $LocalPython) { $Python = $LocalPython }
if (!$Python) {
    $Py = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($Py) {
        $Candidate = & $Py.Source -3.12 -c 'import sys; print(sys.executable)' 2>$null
        if ($LASTEXITCODE -eq 0) {
            $Candidate = ($Candidate | Select-Object -Last 1).Trim()
            if (Test-NovaPython $Candidate) { $Python = $Candidate }
        }
    }
}
if (!$Python) {
    $Cmd = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($Cmd) {
        $Candidate = & $Cmd.Source -c 'import sys; print(sys.executable)' 2>$null
        if ($LASTEXITCODE -eq 0) {
            $Candidate = ($Candidate | Select-Object -Last 1).Trim()
            if (Test-NovaPython $Candidate) { $Python = $Candidate }
        }
    }
}
if (!$Python) {
    Fail 'Python 3.12 with pypdf is not ready. Run "Install NOVA Prerequisites.bat" once. Start NOVA does not download or install anything.'
}

$LlamaServer = Join-Path $Root 'llama-server.exe'
$EngineReady = $false
if (Test-Path -LiteralPath $LlamaServer -PathType Leaf) {
    try {
        & $LlamaServer --version 2>&1 | Out-Null
        $EngineReady = ($LASTEXITCODE -eq 0)
    } catch { $EngineReady = $false }
}
if (!$EngineReady) {
    Fail 'llama.cpp is not ready. Run "Install NOVA Prerequisites.bat" once. Start NOVA does not download or install anything.'
}

New-Item -ItemType Directory -Force -Path (Join-Path $Root 'data'), (Join-Path $Root 'models'), (Join-Path $Root 'models\embed') | Out-Null
$env:NOVA_NO_OPEN = '1'

$Existing = $null
try { $Existing = Invoke-RestMethod -Uri 'http://127.0.0.1:8765/api/health' -TimeoutSec 2 } catch { }
if ($Existing) {
    if ($Existing.version -eq '3.1.0') {
        Write-Host '[NOVA] This version is already running. Opening it.' -ForegroundColor Green
        Start-Process 'http://127.0.0.1:8765'
        exit 0
    }
    if ($Existing.version) { Fail "Another NOVA version ($($Existing.version)) is using port 8765. Close it with Stop NOVA.bat first." }
    Fail 'Port 8765 is already used by another application. Close that application and retry.'
}

Write-Host '[NOVA] Starting full-feature NOVA Desktop 3.1.0 Lite...' -ForegroundColor Cyan
$LogOut = Join-Path $Root 'data\backend.log'
$LogErr = Join-Path $Root 'data\backend-error.log'
$BackendProcess = Start-Process -FilePath $Python -ArgumentList ('"{0}"' -f $BackendPath) -WorkingDirectory $Root -PassThru -WindowStyle Hidden -RedirectStandardOutput $LogOut -RedirectStandardError $LogErr
$Ready = $false
$HealthError = ''
for ($i = 0; $i -lt 60; $i++) {
    Start-Sleep -Seconds 1
    if ($BackendProcess.HasExited) { break }
    try {
        $Health = Invoke-RestMethod -Uri 'http://127.0.0.1:8765/api/health' -TimeoutSec 2
        if ($Health.version -eq '3.1.0') { $Ready = $true; break }
        if ($Health.version) { $HealthError = "Unexpected service version on port 8765: $($Health.version)"; break }
    } catch { }
}
if (!$Ready) {
    if ($HealthError) { Write-Host "[NOVA] $HealthError" -ForegroundColor Red }
    Write-Host '[NOVA] Startup failed. Recent backend logs:' -ForegroundColor Red
    if (Test-Path $LogOut) { Get-Content $LogOut -Tail 30 }
    if (Test-Path $LogErr) { Get-Content $LogErr -Tail 30 }
    if (!$BackendProcess.HasExited) { Stop-Process -Id $BackendProcess.Id -Force -ErrorAction SilentlyContinue }
    Fail 'NOVA did not start. See data\backend.log and data\backend-error.log.'
}

$Browser = Get-Command msedge.exe -ErrorAction SilentlyContinue
if (!$Browser) { $Browser = Get-Command chrome.exe -ErrorAction SilentlyContinue }
if ($Browser) {
    Start-Process -FilePath $Browser.Source -ArgumentList '--app=http://127.0.0.1:8765','--window-size=1240,860'
} else {
    Start-Process 'http://127.0.0.1:8765'
}

Write-Host ''
Write-Host 'NOVA Desktop 3.1.0 Lite is running. No setup downloads were performed.' -ForegroundColor Green
Write-Host 'Press ENTER here when you want to stop this NOVA session.'
[void](Read-Host)
try { Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:8765/api/quit' -ContentType 'application/json' -Body '{}' -TimeoutSec 5 | Out-Null } catch { }
try { $BackendProcess.WaitForExit(8000) | Out-Null } catch { }
if (!$BackendProcess.HasExited) { Stop-Process -Id $BackendProcess.Id -Force -ErrorAction SilentlyContinue }
Write-Host 'NOVA has stopped.' -ForegroundColor DarkGray
