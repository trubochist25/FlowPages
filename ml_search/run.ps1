param(
    [ValidateSet("selected", "legacy")]
    [string]$Profile = "selected",

    [ValidateSet("small")]
    [string]$Model = "small"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
$ExperimentRoot = Join-Path $PSScriptRoot "experiments\e5_finetuning_v1"

$env:ML_SEARCH_OFFLINE = "1"
$env:HF_HUB_OFFLINE = "1"
$env:TRANSFORMERS_OFFLINE = "1"
$env:ML_SEARCH_MODEL = $Model

if (-not (Test-Path -LiteralPath $Python)) {
    throw "ML search is not installed. Run ml_search\install.ps1 first."
}

$ProfileVariables = @(
    "ML_SEARCH_MODEL_NAME",
    "ML_SEARCH_LOCAL_MODEL",
    "ML_SEARCH_INDEX",
    "ML_SEARCH_MANIFEST",
    "ML_SEARCH_FUZZY_TITLE_RESOLVER",
    "ML_SEARCH_MULTI_VECTOR_RERANKER",
    "ML_SEARCH_MULTI_VECTOR_INDEX"
)

foreach ($VariableName in $ProfileVariables) {
    Remove-Item -LiteralPath ("Env:" + $VariableName) -ErrorAction SilentlyContinue
}

if ($Profile -eq "selected") {
    $ModelPath = Join-Path $ExperimentRoot "limited_experiment\selected-model"
    $IndexPath = Join-Path $ExperimentRoot "comparison\index\book-index.npz"
    $ManifestPath = Join-Path $ExperimentRoot "comparison\index\manifest.json"
    $MultiVectorIndexPath = Join-Path $ExperimentRoot "reranking_v1\field-vectors.npz"
    $MultiVectorManifestPath = Join-Path $ExperimentRoot "reranking_v1\field-vectors.manifest.json"

    foreach ($RequiredPath in @($ModelPath, $IndexPath, $ManifestPath, $MultiVectorIndexPath, $MultiVectorManifestPath)) {
        if (-not (Test-Path -LiteralPath $RequiredPath)) {
            throw "Selected search artifact is missing: $RequiredPath"
        }
    }

    $env:ML_SEARCH_MODEL_NAME = "multilingual-e5-small-finetuned-lr1e-5-epoch3"
    $env:ML_SEARCH_LOCAL_MODEL = $ModelPath
    $env:ML_SEARCH_INDEX = $IndexPath
    $env:ML_SEARCH_MANIFEST = $ManifestPath
    $env:ML_SEARCH_FUZZY_TITLE_RESOLVER = "1"
    $env:ML_SEARCH_MULTI_VECTOR_RERANKER = "1"
    $env:ML_SEARCH_MULTI_VECTOR_INDEX = $MultiVectorIndexPath
}

Write-Host "Starting FlowPages ML search profile: $Profile"

Push-Location $ProjectRoot
try {
    & $Python -m ml_search serve --model $Model
}
finally {
    Pop-Location
}
