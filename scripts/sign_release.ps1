param(
    [string]$Path = "dist",
    [string]$CertificateThumbprint = $env:WINDOWS_CODE_SIGNING_THUMBPRINT,
    [string]$TimestampUrl = "http://timestamp.digicert.com",
    [string]$SignToolPath = $env:SIGNTOOL_PATH
)

$ErrorActionPreference = "Stop"

if (-not $SignToolPath) {
    $SignToolPath = "signtool"
}

if (-not $CertificateThumbprint) {
    throw "WINDOWS_CODE_SIGNING_THUMBPRINT is required for direct-download signing."
}

$root = Resolve-Path -LiteralPath $Path
$files = Get-ChildItem -LiteralPath $root -Recurse -File -Include "*.exe", "*.dll"
if (-not $files) {
    throw "No PE files found under $root."
}

foreach ($file in $files) {
    & $SignToolPath sign /fd SHA256 /sha1 $CertificateThumbprint /tr $TimestampUrl /td SHA256 /v $file.FullName
    if ($LASTEXITCODE -ne 0) {
        throw "signtool sign failed for $($file.FullName)"
    }
}

foreach ($file in $files) {
    & $SignToolPath verify /pa /all /v $file.FullName
    if ($LASTEXITCODE -ne 0) {
        throw "signtool verify failed for $($file.FullName)"
    }
}

Write-Host "Signed and verified $($files.Count) PE files with timestamp $TimestampUrl."
