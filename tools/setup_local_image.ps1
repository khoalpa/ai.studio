param(
    [ValidateSet('cu130')]
    [string]$CudaIndex = "cu130"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $ProjectRoot

$NvidiaSmi = Get-Command nvidia-smi -ErrorAction SilentlyContinue
if ($null -ne $NvidiaSmi) {
    $GpuNames = & $NvidiaSmi.Source --query-gpu=name --format=csv,noheader
    if ($LASTEXITCODE -ne 0 -or -not $GpuNames) {
        throw "nvidia-smi is installed but GPU detection failed"
    }
    Write-Host "NVIDIA GPU detected: $($GpuNames -join ', ')"
    Write-Host "Syncing the locked CUDA environment ($CudaIndex)..."
    uv sync --locked --dev --extra cuda
    if ($LASTEXITCODE -ne 0) {
        throw "Locked CUDA environment sync failed"
    }
    $env:AI_STORY_EXPECT_TORCH = "2.14.0+cu130"
    $env:AI_STORY_EXPECT_TORCHVISION = "0.29.0+cu130"
    $env:AI_STORY_EXPECT_CUDA = "13.0"
} else {
    Write-Host "No NVIDIA GPU detected; syncing the locked CPU image environment."
    uv sync --locked --dev --extra local-image
    if ($LASTEXITCODE -ne 0) {
        throw "Locked CPU image environment sync failed"
    }
    $env:AI_STORY_EXPECT_TORCH = "2.14.0"
    $env:AI_STORY_EXPECT_TORCHVISION = "0.29.0"
    $env:AI_STORY_EXPECT_CUDA = ""
}

& .\.venv\Scripts\python.exe -c @'
import json
import os
import torch
import torchvision

result = {
    "torch": torch.__version__,
    "torchvision": torchvision.__version__,
    "cuda_build": torch.version.cuda,
    "cuda_available": torch.cuda.is_available(),
    "gpu": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
}
print(json.dumps(result, indent=2))
expected = {
    "torch": os.environ["AI_STORY_EXPECT_TORCH"],
    "torchvision": os.environ["AI_STORY_EXPECT_TORCHVISION"],
    "cuda_build": os.environ["AI_STORY_EXPECT_CUDA"] or None,
}
actual = {key: result[key] for key in expected}
if actual != expected:
    raise SystemExit(f"Locked runtime mismatch: expected={expected}, actual={actual}")
if expected["cuda_build"] and not torch.cuda.is_available():
    raise SystemExit("The locked CUDA build is installed but CUDA is unavailable")
'@
if ($LASTEXITCODE -ne 0) {
    throw "PyTorch runtime verification failed"
}
Remove-Item Env:AI_STORY_EXPECT_TORCH, Env:AI_STORY_EXPECT_TORCHVISION, `
    Env:AI_STORY_EXPECT_CUDA -ErrorAction SilentlyContinue
