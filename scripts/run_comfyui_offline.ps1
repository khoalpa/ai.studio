param(
    [string]$ComfyRoot = 'D:\project\ComfyUI',
    [string]$ModelConfig = 'C:\Users\lpak\AppData\Roaming\ComfyUI\extra_models_config.yaml',
    [int]$Port = 8188
)

$ErrorActionPreference = 'Stop'
$exe = Join-Path $ComfyRoot 'ComfyUI.exe'
if (-not (Test-Path -LiteralPath $exe -PathType Leaf)) {
    throw "ComfyUI executable not found: $exe"
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

Start-Process -FilePath $exe -WorkingDirectory $ComfyRoot -ArgumentList $arguments
