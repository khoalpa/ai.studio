param(
    [string]$ComfyRoot = 'D:\Comfy-Desktop\ComfyUI-Installs\ComfyUI\ComfyUI',
    [string]$ModelConfig = 'C:\Users\lpak\AppData\Roaming\ComfyUI\extra_models_config.yaml',
    [int]$Port = 8188
)

$ErrorActionPreference = 'Stop'
$python = Join-Path $ComfyRoot '.venv\Scripts\python.exe'
$entrypoint = Join-Path $ComfyRoot 'main.py'
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "ComfyUI Python runtime not found: $python"
}
if (-not (Test-Path -LiteralPath $entrypoint -PathType Leaf)) {
    throw "ComfyUI entrypoint not found: $entrypoint"
}
if (-not (Test-Path -LiteralPath $ModelConfig -PathType Leaf)) {
    throw "Model path configuration not found: $ModelConfig"
}
if ($Port -lt 1 -or $Port -gt 65535) {
    throw "Invalid loopback port: $Port"
}

# ComfyUI Desktop forwards these arguments to its bundled server. All network
# capable manager/API-node features are disabled and custom nodes are excluded.
$arguments = @(
    '--listen', '127.0.0.1',
    '--port', "$Port",
    '--extra-model-paths-config', $ModelConfig,
    '--disable-all-custom-nodes',
    '--disable-api-nodes',
    '--disable-manager-ui',
    '--disable-auto-launch',
    '--deterministic'
)

Start-Process -FilePath $python -WorkingDirectory $ComfyRoot -ArgumentList @($entrypoint) + $arguments
