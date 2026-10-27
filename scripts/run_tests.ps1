$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $python -PathType Leaf)) {
    Write-Error "Project venv not found. Create it with 'py -3.11 -m venv .venv' and install '.[dev,desktop]'."
    exit 1
}

$env:PYTHONPATH = if ($env:PYTHONPATH) {
    (Join-Path $repoRoot "src") + ";" + $env:PYTHONPATH
} else {
    Join-Path $repoRoot "src"
}
$env:QT_QPA_PLATFORM = "offscreen"

Push-Location $repoRoot
try {
    & $python -m pytest
    exit $LASTEXITCODE
} finally {
    Pop-Location
}
