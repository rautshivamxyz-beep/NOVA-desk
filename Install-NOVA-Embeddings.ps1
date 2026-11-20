$ErrorActionPreference = 'Stop'
$Root = (Resolve-Path $PSScriptRoot).Path
$EmbedDir = Join-Path $Root 'models\embed'
$Target = Join-Path $EmbedDir 'all-MiniLM-L6-v2-Q8_0.gguf'
$Url = 'https://huggingface.co/LLukas22/all-MiniLM-L6-v2-GGUF/resolve/main/all-minilm-l6-v2_q8_0.gguf'
$Expected = '771705d3231fb60715dad2e960f5220cfbaa866786257082e845d91fc8b0d0ee'
New-Item -ItemType Directory -Force -Path $EmbedDir | Out-Null
if (Test-Path $Target) {
    $Current = (Get-FileHash $Target -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($Current -eq $Expected) { Write-Host 'NOVA embeddings are already installed.' -ForegroundColor Green; exit 0 }
}
$Temp = "$Target.download"
try {
    Invoke-WebRequest -UseBasicParsing -Uri $Url -OutFile $Temp -TimeoutSec 600
    if ((Get-Item $Temp).Length -lt 1000000) { throw 'Embedding file is unexpectedly small.' }
    $Actual = (Get-FileHash $Temp -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($Actual -ne $Expected) { throw 'Embedding model SHA-256 verification failed.' }
    Move-Item $Temp $Target -Force
    Write-Host 'Semantic embeddings installed. Restart NOVA to enable vector search.' -ForegroundColor Green
} catch {
    if (Test-Path $Temp) { Remove-Item $Temp -Force -ErrorAction SilentlyContinue }
    Write-Host "Embedding installation failed: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
