param(
    [string]$Url = 'http://127.0.0.1:4173/',
    [int]$TimeoutSeconds = 180
)

$ErrorActionPreference = 'SilentlyContinue'
$deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
while ([DateTime]::UtcNow -lt $deadline) {
    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri ($Url.TrimEnd('/') + '/api/v1/health') -TimeoutSec 2
        if ($response.StatusCode -eq 200) {
            Start-Process $Url
            exit 0
        }
    }
    catch {
        Start-Sleep -Milliseconds 500
    }
}

Write-Error "Audio Story Studio did not become ready within $TimeoutSeconds seconds."
exit 1
