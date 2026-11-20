$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$Root = (Resolve-Path $PSScriptRoot).Path
$Base = Join-Path $env:LOCALAPPDATA 'Programs\NOVA'
$PythonExe = Join-Path $Base 'Python312\python.exe'
$EngineExe = Join-Path $Root 'llama-server.exe'

function Step([string]$Text) { Write-Host ''; Write-Host "[NOVA setup] $Text" -ForegroundColor Cyan }
function StopSetup([string]$Text) { Write-Host ''; Write-Host "[NOVA setup error] $Text" -ForegroundColor Red; exit 1 }
function DownloadVerified([string]$Url,[string]$Dest,[long]$MinBytes=1,[string]$Sha256='',[int]$Tries=3) {
    $Temp = "$Dest.download"
    $Last = ''
    for ($i=1; $i -le $Tries; $i++) {
        try {
            if (Test-Path $Temp) { Remove-Item $Temp -Force }
            Invoke-WebRequest -UseBasicParsing -Uri $Url -OutFile $Temp -TimeoutSec 600
            if ((Get-Item $Temp).Length -lt $MinBytes) { throw 'Downloaded file was too small.' }
            if ($Sha256) {
                $Actual = (Get-FileHash $Temp -Algorithm SHA256).Hash.ToLowerInvariant()
                if ($Actual -ne $Sha256.ToLowerInvariant()) { throw 'SHA-256 mismatch.' }
            }
            Move-Item $Temp $Dest -Force
            return
        } catch {
            $Last = $_.Exception.Message
            if (Test-Path $Temp) { Remove-Item $Temp -Force -ErrorAction SilentlyContinue }
            if ($i -lt $Tries) { Write-Warning "Attempt $i failed: $Last"; Start-Sleep -Seconds (2 * $i) }
        }
    }
    StopSetup ("Download failed after " + $Tries + " attempts: " + $Url + [Environment]::NewLine + $Last)
}
function IsPython312([string]$Exe) {
    if (!(Test-Path $Exe)) { return $false }
    & $Exe -c 'import sys; raise SystemExit(0 if sys.version_info[:2] == (3,12) else 1)' 2>$null
    return ($LASTEXITCODE -eq 0)
}

New-Item -ItemType Directory -Force -Path $Base,$Root | Out-Null
$Python = $null
if (IsPython312 $PythonExe) { $Python = $PythonExe }
if (!$Python) {
    $Py = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($Py) {
        $Candidate = & $Py.Source -3.12 -c 'import sys; print(sys.executable)' 2>$null
        if ($LASTEXITCODE -eq 0) {
            $Candidate = ($Candidate | Select-Object -Last 1).Trim()
            if (IsPython312 $Candidate) { $Python = $Candidate }
        }
    }
}
if (!$Python) {
    Step 'Installing Python 3.12 once'
    $PythonInstaller = Join-Path $env:TEMP 'nova-python-3.12.10-amd64.exe'
    DownloadVerified 'https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe' $PythonInstaller 20000000
    $Signature = Get-AuthenticodeSignature -FilePath $PythonInstaller
    if ($Signature.Status -ne 'Valid' -or $Signature.SignerCertificate.Subject -notmatch 'Python Software Foundation') {
        StopSetup 'Python installer signature verification failed.'
    }
    $PythonHome = Join-Path $Base 'Python312'
    $InstallArguments = @('/quiet','InstallAllUsers=0',("TargetDir=" + '"' + $PythonHome + '"'),'PrependPath=0','Include_pip=1','Include_launcher=0','Include_test=0','Include_doc=0','Include_tcltk=0')
    $Process = Start-Process -FilePath $PythonInstaller -ArgumentList $InstallArguments -Wait -PassThru
    if ($Process.ExitCode -ne 0 -or !(IsPython312 $PythonExe)) { StopSetup 'Python 3.12 installation failed.' }
    $Python = $PythonExe
}

Step 'Installing PDF support once'
& $Python -m pip install --user --disable-pip-version-check --retries 5 --timeout 30 'pypdf==6.19.0'
if ($LASTEXITCODE -ne 0) { StopSetup 'Could not install pypdf. Check internet and try this installer again.' }
& $Python -c 'import pypdf,sys; print("Python",sys.version.split()[0],"pypdf",pypdf.__version__)'
if ($LASTEXITCODE -ne 0) { StopSetup 'Python package verification failed.' }

$EngineReady = $false
if (Test-Path $EngineExe) {
    try { & $EngineExe --version 2>&1 | Out-Null; $EngineReady = ($LASTEXITCODE -eq 0) } catch { $EngineReady = $false }
}
if (!$EngineReady) {
    Step 'Installing the local llama.cpp engine once'
    $Archive = Join-Path $env:TEMP 'nova-llama-b12565-win-cpu-x64.zip'
    DownloadVerified 'https://github.com/ggml-org/llama.cpp/releases/download/b12565/llama-b12565-bin-win-cpu-x64.zip' $Archive 10000000 'ba675a702e8f3b2704da64f20fea1e532e63070e47f10f101644162f19415fbe' 3
    $Extract = Join-Path $env:TEMP 'nova-llama-extract'
    if (Test-Path $Extract) { Remove-Item $Extract -Recurse -Force }
    Expand-Archive -Path $Archive -DestinationPath $Extract -Force
    $Server = Get-ChildItem $Extract -Filter 'llama-server.exe' -File -Recurse | Select-Object -First 1
    if (!$Server) { StopSetup 'llama.cpp archive did not contain llama-server.exe.' }
    Get-ChildItem -Path $Server.Directory.FullName -Force | Copy-Item -Destination $Root -Recurse -Force
    Get-ChildItem -Path $Extract -Include 'LICENSE*','COPYING*' -File -Recurse | ForEach-Object { Copy-Item $_.FullName $Root -Force }
    if (!(Test-Path $EngineExe)) { StopSetup 'Could not install llama-server.exe.' }
    & $EngineExe --version 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) { StopSetup 'llama.cpp could not start. Check antivirus and rerun this installer.' }
}

Step 'Prerequisites are ready'
Write-Host 'Python 3.12 + pypdf and llama.cpp are installed.' -ForegroundColor Green
Write-Host 'No AI chat model was downloaded. Import your own .gguf file from NOVA Models.' -ForegroundColor Green
Write-Host 'Now double-click Start NOVA.bat.' -ForegroundColor Green
