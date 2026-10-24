$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $ProjectRoot

$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$ArtifactRoot = Join-Path $ProjectRoot "artifacts\local-e2e-sdxl"
$BenchmarkStatus = Join-Path $ProjectRoot "artifacts\image-ab\benchmark-status.json"
$StatusPath = Join-Path $ArtifactRoot "workflow-status.json"
$SummaryPath = Join-Path $ArtifactRoot "workflow-summary.json"
$LlamaOut = Join-Path $ArtifactRoot "llama-server.stdout.log"
$LlamaErr = Join-Path $ArtifactRoot "llama-server.stderr.log"
$LlamaPort = 18080
$ProviderConfigPath = Join-Path $ArtifactRoot "providers.local-e2e.json"
$ModelPath = "D:\project\ai.studio\models\qwen2.5-14b-q4km\qwen2.5-14b-instruct-q4_k_m-00001-of-00003.gguf"
$RunToken = [DateTimeOffset]::UtcNow.ToString("yyyyMMddHHmmss")
$Stage1RunId = "run-local-stage1-$RunToken"
$Stage2RunId = "run-local-stage2-$RunToken"
$Stage3RunId = "run-local-stage3-$RunToken"
$Stage4RunId = "run-local-stage4-$RunToken"

New-Item -ItemType Directory -Force -Path $ArtifactRoot | Out-Null
$ProviderConfig = Get-Content -LiteralPath (Join-Path $ProjectRoot "spec\providers.json") -Raw | ConvertFrom-Json
$ProviderConfig.runtimes.llama_cpp.endpoint = "http://127.0.0.1:$LlamaPort"
$ProviderConfig | ConvertTo-Json -Depth 100 | Set-Content -LiteralPath $ProviderConfigPath -Encoding utf8

function Write-Status([string]$State, [string]$Phase, [string]$Detail) {
    @{
        schema_version = "1.0"
        state = $State
        phase = $Phase
        detail = $Detail
        updated_at = [DateTimeOffset]::UtcNow.ToString("o")
    } | ConvertTo-Json | Set-Content -LiteralPath $StatusPath -Encoding utf8
}

function Invoke-Stage([string[]]$Arguments) {
    $raw = & $Python @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "ai-story command failed: $($Arguments -join ' ')"
    }
    return ($raw | ConvertFrom-Json)
}

$LlamaProcess = $null
try {
    Write-Status "QUEUED" "WAITING_FOR_GPU" "Waiting for the canonical image A/B benchmark"
    while ($true) {
        if (Test-Path -LiteralPath $BenchmarkStatus) {
            $benchmark = Get-Content -LiteralPath $BenchmarkStatus | ConvertFrom-Json
            if ($benchmark.state -ne "RUNNING") { break }
        }
        Start-Sleep -Seconds 60
    }

    Write-Status "RUNNING" "STARTING_LLM" "Starting llama.cpp on CPU"
    $LlamaServer = (Get-Command llama-server -ErrorAction Stop).Source
    $LlamaProcess = Start-Process -FilePath $LlamaServer `
        -ArgumentList @('-m', $ModelPath, '--host', '127.0.0.1', '--port', $LlamaPort, '-c', '16384', '--n-gpu-layers', '0', '--parallel', '1') `
        -WorkingDirectory $ProjectRoot -WindowStyle Hidden `
        -RedirectStandardOutput $LlamaOut -RedirectStandardError $LlamaErr -PassThru
    $ready = $false
    for ($attempt = 0; $attempt -lt 60; $attempt++) {
        Start-Sleep -Seconds 2
        if ($LlamaProcess.HasExited) { throw "llama-server exited before becoming ready" }
        try {
            $health = Invoke-RestMethod -Uri "http://127.0.0.1:$LlamaPort/health" -TimeoutSec 2
            if ($health.status -eq 'ok') { $ready = $true; break }
        } catch {}
    }
    if (-not $ready) { throw "llama-server did not become ready within 120 seconds" }

    $env:AI_STORY_DEPTH_CONTROLNET = "1"
    $env:AI_STORY_PROVIDER_CONFIG = $ProviderConfigPath
    Write-Status "RUNNING" "STAGE1" "Local Qwen story/safety plus SD 3.5 character references"
    $stage1 = Invoke-Stage @(
        '-m', 'ai_story', 'generate-stage1', '--root', $ArtifactRoot,
        '--run-id', $Stage1RunId, '--profile', 'YOUTH_SAFE', '--minutes', '5',
        '--confirm-duration', '--provider-mode', 'local', '--quality-preset', 'balanced',
        '--brief', 'Hai chị em đưa một chú chim non bị lạc trở về tổ trước khi trời mưa và nhờ mẹ giúp đỡ để hành động an toàn.'
    )

    Write-Status "RUNNING" "STAGE2" "SD 3.5 landscape, layered QA and learned upscale"
    $stage2 = Invoke-Stage @(
        '-m', 'ai_story', 'generate-stage2', '--root', $ArtifactRoot,
        '--run-id', $Stage2RunId, '--input-package', $stage1.package.archive_path,
        '--provider-mode', 'local', '--quality-preset', 'balanced'
    )

    Write-Status "RUNNING" "STAGE3" "SD 3.5 portrait generation, parity QA and learned upscale"
    $stage3 = Invoke-Stage @(
        '-m', 'ai_story', 'generate-stage3', '--root', $ArtifactRoot,
        '--run-id', $Stage3RunId, '--input-package', $stage2.package.archive_path,
        '--provider-mode', 'local', '--quality-preset', 'balanced'
    )

    Write-Status "RUNNING" "STAGE4" "Building the canonical production plan"
    $stage4 = Invoke-Stage @(
        '-m', 'ai_story', 'generate-stage4', '--root', $ArtifactRoot,
        '--run-id', $Stage4RunId, '--input-package', $stage3.package.archive_path,
        '--confirm-large-plan'
    )

    @{
        schema_version = "1.0"
        provider_mode = "local"
        quality_preset = "balanced"
        depth_controlnet = $true
        visual_review = "PENDING_HUMAN_REVIEW"
        stage1_package = $stage1.package.archive_path
        stage2_package = $stage2.package.archive_path
        stage3_package = $stage3.package.archive_path
        stage4_package = $stage4.package.archive_path
        completed_at = [DateTimeOffset]::UtcNow.ToString("o")
    } | ConvertTo-Json | Set-Content -LiteralPath $SummaryPath -Encoding utf8
    Write-Status "COMPLETED" "DONE" "Local Stage 1-4 workflow completed"
} catch {
    Write-Status "FAILED" "ERROR" $_.Exception.Message
    throw
} finally {
    Remove-Item Env:AI_STORY_DEPTH_CONTROLNET -ErrorAction SilentlyContinue
    Remove-Item Env:AI_STORY_PROVIDER_CONFIG -ErrorAction SilentlyContinue
    if ($null -ne $LlamaProcess -and -not $LlamaProcess.HasExited) {
        Stop-Process -Id $LlamaProcess.Id
    }
}
