$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $ProjectRoot

$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$Root = Join-Path $ProjectRoot "artifacts\image-ab"
$Sources = Join-Path $Root "source-packages"
$Baseline = Join-Path $Root "baseline-depth-off"
$Candidate = Join-Path $Root "candidate-depth-on"
$Promotion = Join-Path $Root "promotion-evidence.json"
$Status = Join-Path $Root "benchmark-status.json"

function Write-Status([string]$State, [string]$Phase, [string]$Detail) {
    @{
        schema_version = "1.0"
        state = $State
        phase = $Phase
        detail = $Detail
        updated_at = [DateTimeOffset]::UtcNow.ToString("o")
    } | ConvertTo-Json | Set-Content -LiteralPath $Status -Encoding utf8
}

try {
    Write-Status "RUNNING" "BASELINE_DEPTH_OFF" "Running canonical golden set"
    $env:AI_STORY_DEPTH_CONTROLNET = "0"
    & $Python -m ai_story run-image-baseline-suite `
        --source-packages $Sources --output $Baseline `
        --provider-mode local --quality-preset balanced --resume
    if ($LASTEXITCODE -ne 0) { throw "Depth-off baseline failed with exit code $LASTEXITCODE" }

    Write-Status "RUNNING" "CANDIDATE_DEPTH_ON" "Running canonical golden set"
    $env:AI_STORY_DEPTH_CONTROLNET = "1"
    & $Python -m ai_story run-image-baseline-suite `
        --source-packages $Sources --output $Candidate `
        --provider-mode local --quality-preset balanced --resume
    if ($LASTEXITCODE -ne 0) { throw "Depth-on candidate failed with exit code $LASTEXITCODE" }

    Write-Status "RUNNING" "PROMOTION_EVALUATION" "Automated gates; human review remains independent"
    & $Python -m ai_story evaluate-image-benchmark `
        --baseline (Join-Path $Baseline "baseline.json") `
        --candidate (Join-Path $Candidate "baseline.json") `
        --output $Promotion
    if ($LASTEXITCODE -ne 0) { throw "Promotion evaluation failed with exit code $LASTEXITCODE" }

    Write-Status "COMPLETED" "DONE" "Promotion evidence created; human review gate is expected to remain pending"
} catch {
    Write-Status "FAILED" "ERROR" $_.Exception.Message
    throw
} finally {
    Remove-Item Env:AI_STORY_DEPTH_CONTROLNET -ErrorAction SilentlyContinue
}
