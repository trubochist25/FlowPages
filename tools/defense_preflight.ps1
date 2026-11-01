param(
    [string]$StoreUrl = "http://bookstore/",
    [string]$SearchUrl = "http://127.0.0.1:8765"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Failures = [System.Collections.Generic.List[string]]::new()

function Test-Condition([bool]$Condition, [string]$Label) {
    if ($Condition) {
        Write-Host "[OK] $Label" -ForegroundColor Green
    }
    else {
        Write-Host "[FAIL] $Label" -ForegroundColor Red
        $Failures.Add($Label)
    }
}

Push-Location $ProjectRoot
try {
    try {
        $Store = Invoke-WebRequest -Uri $StoreUrl -UseBasicParsing -TimeoutSec 15
        Test-Condition ($Store.StatusCode -eq 200) "FlowPages storefront responds"
    }
    catch {
        Test-Condition $false "FlowPages storefront responds"
    }

    $Health = $null
    try {
        $Health = Invoke-RestMethod -Uri ($SearchUrl + "/health") -TimeoutSec 10
    }
    catch {
        Test-Condition $false "ML search health endpoint responds"
    }

    if ($null -ne $Health) {
        Test-Condition ($Health.status -eq "ok") "ML search status is healthy"
        Test-Condition ($Health.model -eq "multilingual-e5-small-finetuned-lr1e-5-epoch3") "Selected fine-tuned model is active"
        Test-Condition ($Health.books -eq 1000) "Search index contains 1000 books"
        Test-Condition ([bool]$Health.fuzzy_title_resolver) "Fuzzy title resolver is active"
        Test-Condition ([bool]$Health.multi_vector_reranker) "Multi-vector reranker is active"
    }

    $ExperimentRoot = Join-Path $ProjectRoot "ml_search\experiments\e5_finetuning_v1"
    $Artifacts = @(
        @{ Path = Join-Path $ProjectRoot "data\book_catalog\catalog.json"; Hash = "115c7e689447db05d2e34bc5d83ab66238305b24b287601b36bd7fa3774bf5ee"; Label = "Catalog checksum matches" },
        @{ Path = Join-Path $ExperimentRoot "comparison\index\book-index.npz"; Hash = "d728e5f6be0860d7c22d15588c1deac23fd32f8463a22a99b73520e6f8d85fd6"; Label = "Main index checksum matches" },
        @{ Path = Join-Path $ExperimentRoot "reranking_v1\field-vectors.npz"; Hash = "8971b7f78a7a1f5f8404967b93a0df36ab5738082462053d4a6fe39f5300d389"; Label = "Field index checksum matches" },
        @{ Path = Join-Path $ExperimentRoot "limited_experiment\selected-model\model.safetensors"; Hash = "1c1813ae9a621a9ead0886b161177b746d70e9f9942b88752c3f1ac5ef35721a"; Label = "Model checksum matches" }
    )

    foreach ($Artifact in $Artifacts) {
        if (-not (Test-Path -LiteralPath $Artifact.Path)) {
            Test-Condition $false ($Artifact.Label + " (file is missing)")
            continue
        }
        $ActualHash = (Get-FileHash -LiteralPath $Artifact.Path -Algorithm SHA256).Hash.ToLowerInvariant()
        Test-Condition ($ActualHash -eq $Artifact.Hash) $Artifact.Label
    }

    if ($null -ne $Health) {
        $Body = '{"query":"\u0413\u0430\u0440\u0440\u0438 \u041f\u043e\u0442\u0442\u0435\u0440 \u0438 \u0444\u0438\u043b\u043e\u0441\u043e\u0444\u0441\u043a\u0438\u0439 \u043a\u0430\u043c\u0435\u043d\u044c","limit":1}'
        try {
            $Response = Invoke-RestMethod -Uri ($SearchUrl + "/search") -Method Post -ContentType "application/json; charset=utf-8" -Body ([Text.Encoding]::UTF8.GetBytes($Body)) -TimeoutSec 15
            $TopProductId = if ($Response.results.Count -gt 0) { [int]$Response.results[0].product_id } else { 0 }
            Test-Condition ($TopProductId -eq 57) "Exact-title smoke test returns the expected book"
        }
        catch {
            Test-Condition $false "Exact-title smoke test returns the expected book"
        }
    }

    if ($Failures.Count -gt 0) {
        Write-Host "Preflight failed: $($Failures.Count) check(s)." -ForegroundColor Red
        Write-Host "If ML search is unavailable, start ml_search\run.ps1 and run this check again."
        exit 1
    }

    Write-Host "All defense preflight checks passed." -ForegroundColor Green
    exit 0
}
finally {
    Pop-Location
}
