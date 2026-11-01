param(
    [ValidateSet("small")]
    [string]$Model = "small"
)

$ErrorActionPreference = "Stop"

$DataRoot = Join-Path (Split-Path -Parent $PSScriptRoot) "data\ml_search"
$Profiles = @{
    "small" = @{
        Repository = "intfloat/multilingual-e5-small"
        RelativePath = "local-model"
        ModelSize = 470641600
        ModelSha256 = "1a55775f53449dac10a2bcbc312469fac40b96d53198c407081a831f81c98477"
    }
}
$Profile = $Profiles[$Model]
$ModelRoot = Join-Path $DataRoot $Profile.RelativePath
$PoolingRoot = Join-Path $ModelRoot "1_Pooling"
$BaseUrl = "https://huggingface.co/$($Profile.Repository)/resolve/main"
$ExpectedModelSize = $Profile.ModelSize
$ExpectedModelSha256 = $Profile.ModelSha256

New-Item -ItemType Directory -Path $PoolingRoot -Force | Out-Null

$Files = @{
    "config.json" = "$BaseUrl/config.json"
    "modules.json" = "$BaseUrl/modules.json"
    "sentence_bert_config.json" = "$BaseUrl/sentence_bert_config.json"
    "1_Pooling\config.json" = "$BaseUrl/1_Pooling/config.json"
    "sentencepiece.bpe.model" = "$BaseUrl/sentencepiece.bpe.model"
    "special_tokens_map.json" = "$BaseUrl/special_tokens_map.json"
    "tokenizer.json" = "$BaseUrl/tokenizer.json"
    "tokenizer_config.json" = "$BaseUrl/tokenizer_config.json"
}

foreach ($Entry in $Files.GetEnumerator()) {
    $Target = Join-Path $ModelRoot $Entry.Key
    if (-not (Test-Path -LiteralPath $Target)) {
        & curl.exe --fail --location $Entry.Value -o $Target
        if ($LASTEXITCODE -ne 0) {
            throw "Failed to download $($Entry.Key)"
        }
    }
}

$ModelTarget = Join-Path $ModelRoot "model.safetensors"
if (Test-Path -LiteralPath $ModelTarget) {
    $ModelFile = Get-Item -LiteralPath $ModelTarget
    if ($ModelFile.Length -eq $ExpectedModelSize) {
        $ActualHash = (Get-FileHash -LiteralPath $ModelTarget -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($ActualHash -eq $ExpectedModelSha256) {
            Write-Output "$($Profile.Repository) is already downloaded and verified."
            exit 0
        }
        Remove-Item -LiteralPath $ModelTarget -Force
    }
}

& curl.exe --fail --location --continue-at - "$BaseUrl/model.safetensors" -o $ModelTarget
if ($LASTEXITCODE -ne 0) {
    throw "Failed to download model.safetensors"
}

$Downloaded = Get-Item -LiteralPath $ModelTarget
if ($Downloaded.Length -ne $ExpectedModelSize) {
    throw "Unexpected model size: $($Downloaded.Length)"
}

$DownloadedHash = (Get-FileHash -LiteralPath $ModelTarget -Algorithm SHA256).Hash.ToLowerInvariant()
if ($DownloadedHash -ne $ExpectedModelSha256) {
    throw "Model SHA-256 verification failed"
}

Write-Output "$($Profile.Repository) downloaded and verified."
