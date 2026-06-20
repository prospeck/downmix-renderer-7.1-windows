param(
    [string]$DistName = "Finalised Version",
    [switch]$Sign
)

$ErrorActionPreference = "Stop"
$root = Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")

Push-Location $root
try {
    $targetExe = Join-Path $root (Join-Path $DistName "Downmixrenderer.exe")
    Get-CimInstance Win32_Process |
        Where-Object { $_.ExecutablePath -and $_.ExecutablePath -eq $targetExe } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force }

    python scripts/build_native_backend.py
    if ($LASTEXITCODE -ne 0) {
        throw "Native backend build failed."
    }

    $env:DOWNMIX_RENDERER_DIST_NAME = $DistName
    pyinstaller --clean --noconfirm --distpath "." --workpath build renderer_app.spec
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller package build failed."
    }

    if ($Sign) {
        powershell -ExecutionPolicy Bypass -File scripts/sign_release.ps1 -Path $DistName
        if ($LASTEXITCODE -ne 0) {
            throw "Release signing failed."
        }
    }

    $buildDir = Join-Path $root "build"
    if (Test-Path -LiteralPath $buildDir) {
        Remove-Item -LiteralPath $buildDir -Recurse -Force
    }
} finally {
    Pop-Location
}
