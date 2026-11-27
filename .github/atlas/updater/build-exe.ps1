# SPDX-License-Identifier: GPL-2.0-or-later
# Builds HuntersAtlasUpdater.exe locally (CI runs the same command from package_host.py).
[CmdletBinding()]
param(
    [string]$Python = 'python',
    [switch]$SkipInstall
)

$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$repo = Resolve-Path (Join-Path $here '..\..\..')
Push-Location $repo
try {
    if (-not $SkipInstall) {
        & $Python -m pip install --quiet --disable-pip-version-check pyinstaller
        if ($LASTEXITCODE -ne 0) { throw 'pip install pyinstaller failed' }
    }
    $icon = Join-Path $repo 'launcher\bloodborne.ico'
    $args = @(
        '-m', 'PyInstaller', '--noconfirm', '--clean', '--onefile', '--windowed',
        '--log-level', 'WARN', '--name', 'HuntersAtlasUpdater',
        '--distpath', (Join-Path $repo 'out\updater-dist'),
        '--workpath', (Join-Path $repo 'out\updater-work'),
        '--specpath', (Join-Path $repo 'out\updater-work'),
        '--paths', $here,
        '--hidden-import', 'core', '--hidden-import', 'gui'
    )
    if (Test-Path $icon) { $args += @('--icon', $icon) }
    $versionFile = Join-Path $here 'version_info.txt'
    if (Test-Path $versionFile) { $args += @('--version-file', $versionFile) }
    $args += Join-Path $here 'main.py'
    & $Python @args
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed ($LASTEXITCODE)" }
    $exe = Join-Path $repo 'out\updater-dist\HuntersAtlasUpdater.exe'
    $hash = (Get-FileHash -LiteralPath $exe -Algorithm SHA256).Hash.ToLowerInvariant()
    Write-Host "Built $exe" -ForegroundColor Green
    Write-Host "SHA-256: $hash"
    Write-Host "Size:    $([Math]::Round((Get-Item $exe).Length / 1MB, 1)) MB"
} finally {
    Pop-Location
}
