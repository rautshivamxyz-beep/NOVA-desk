$ErrorActionPreference = 'Stop'
$Root = (Resolve-Path $PSScriptRoot).Path
Set-Location $Root

function Fail([string]$Message) {
    Write-Host ''
    Write-Host "[NOVA ERROR] $Message" -ForegroundColor Red
    exit 1
}

$BackendPath = Join-Path $Root 'app\nova_backend.py'
$Python = Join-Path $Root 'runtime\python\python.exe'
$LlamaServer = Join-Path $Root 'llama-server.exe'

if (!(Test-Path -LiteralPath $BackendPath -PathType Leaf)) {
    Fail 'NOVA application source is missing. Extract the complete Windows ZIP again.'
}
if (!(Test-Path -LiteralPath $Python -PathType Leaf)) {
    Fail 'The bundled Python runtime is missing. The ZIP may be incomplete; download and extract it again.'
}
& $Python -c 'import sys,pypdf; raise SystemExit(0 if sys.version_info[:2] == (3,12) else 1)' 2>$null
if ($LASTEXITCODE -ne 0) {
    Fail 'The bundled Python runtime or PDF library failed its self-check. Extract a fresh copy of the NOVA ZIP.'
}
if (!(Test-Path -LiteralPath $LlamaServer -PathType Leaf)) {
    Fail 'llama-server.exe is missing. The NOVA engine files may have been removed by antivirus; restore the complete ZIP.'
}
try {
    $null = & $LlamaServer --version 2>$null
    if ($LASTEXITCODE -ne 0) { Fail 'llama.cpp could not start. Install Microsoft Visual C++ 2015-2022 x64 Runtime and restore the NOVA folder if needed.' }
} catch {
    Fail 'llama.cpp could not start. Install Microsoft Visual C++ 2015-2022 x64 Runtime and restore the NOVA folder if needed.'
}

New-Item -ItemType Directory -Force -Path (Join-Path $Root 'data'), (Join-Path $Root 'models'), (Join-Path $Root 'models\embed') | Out-Null
$env:NOVA_NO_OPEN = '1'

$Existing = $null
try { $Existing = Invoke-RestMethod -Uri 'http://127.0.0.1:8765/api/health' -TimeoutSec 2 } catch { }
if ($Existing) {
    if ($Existing.version -eq '3.2.0') {
        Write-Host '[NOVA] This NOVA version is already running. Opening it.' -ForegroundColor Green
        Start-Process 'http://127.0.0.1:8765'
        exit 0
    }
    if ($Existing.version) { Fail "Another NOVA version ($($Existing.version)) is using port 8765. Close it with Stop NOVA.bat before starting this version." }
    Fail 'Port 8765 is already used by another application. Close that application and retry.'
}

Write-Host '[NOVA] Starting full-feature NOVA Desktop 3.2.0...' -ForegroundColor Cyan
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
        if ($Health.version -eq '3.2.0') { $Ready = $true; break }
        if ($Health.version) { $HealthError = "Unexpected service version on port 8765: $($Health.version)"; break }
    } catch { }
}
if (!$Ready) {
    if ($HealthError) { Write-Host "[NOVA] $HealthError" -ForegroundColor Red }
    Write-Host '[NOVA] Startup failed. Recent backend logs:' -ForegroundColor Red
    if (Test-Path $LogOut) { Get-Content $LogOut -Tail 40 }
    if (Test-Path $LogErr) { Get-Content $LogErr -Tail 40 }
    if (!$BackendProcess.HasExited) { Stop-Process -Id $BackendProcess.Id -Force -ErrorAction SilentlyContinue }
    Fail 'NOVA did not start. Check data\backend.log and data\backend-error.log.'
}

$PF86 = [Environment]::GetEnvironmentVariable('ProgramFiles(x86)')
$EdgePaths = @((Join-Path $PF86 'Microsoft\Edge\Application\msedge.exe'), (Join-Path $env:ProgramFiles 'Microsoft\Edge\Application\msedge.exe'))
$ChromePaths = @((Join-Path $env:ProgramFiles 'Google\Chrome\Application\chrome.exe'), (Join-Path $env:LOCALAPPDATA 'Google\Chrome\Application\chrome.exe'))
$Browser = ($EdgePaths + $ChromePaths | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1)
if ($Browser) {
    Start-Process -FilePath $Browser -ArgumentList '--app=http://127.0.0.1:8765','--window-size=1240,860'
} else {
    Start-Process 'http://127.0.0.1:8765'
}

Write-Host ''
Write-Host 'NOVA Desktop 3.2.0 is running. No setup downloads were performed.' -ForegroundColor Green
Write-Host 'Press ENTER here when you want to stop this NOVA session.'
[void](Read-Host)
try { Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:8765/api/quit' -ContentType 'application/json' -Body '{}' -TimeoutSec 5 | Out-Null } catch { }
try { $BackendProcess.WaitForExit(8000) | Out-Null } catch { }
if (!$BackendProcess.HasExited) { Stop-Process -Id $BackendProcess.Id -Force -ErrorAction SilentlyContinue }
Write-Host 'NOVA has stopped.' -ForegroundColor DarkGray
