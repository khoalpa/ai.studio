param(
    [Parameter(Mandatory = $true)]
    [string]$ModelPath,
    [string]$ServerPath = "llama-server",
    [int]$Port = 8080,
    [int]$ContextSize = 16384,
    [int]$GpuLayers = 32,
    [int]$Parallel = 1
)

$ErrorActionPreference = "Stop"
$resolvedModel = (Resolve-Path -LiteralPath $ModelPath).Path
if (-not (Test-Path -LiteralPath $resolvedModel -PathType Leaf)) {
    throw "Model file does not exist: $resolvedModel"
}

$server = Get-Command $ServerPath -ErrorAction Stop
Write-Host "Starting llama.cpp on http://127.0.0.1:$Port"
Write-Host "Model: $resolvedModel"
& $server.Source -m $resolvedModel --host 127.0.0.1 --port $Port -c $ContextSize --n-gpu-layers $GpuLayers --parallel $Parallel
