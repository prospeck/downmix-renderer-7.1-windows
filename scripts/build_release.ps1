param(
    [string]$DistName = "Finalised Version",
    [switch]$Sign
)

$ErrorActionPreference = "Stop"
$root = Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")

Push-Location $root
try {
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
} finally {
    Pop-Location
}
