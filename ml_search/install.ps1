param(
    [ValidateSet("small")]
    [string]$Model = "small"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $Python)) {
    python -m venv (Join-Path $PSScriptRoot ".venv")
}

& $Python -m pip install --upgrade pip
& $Python -m pip install -r (Join-Path $PSScriptRoot "requirements.txt")
& (Join-Path $PSScriptRoot "download_model.ps1") -Model $Model
Push-Location $ProjectRoot
try {
    & $Python -m ml_search build-index --model $Model
}
finally {
    Pop-Location
}
