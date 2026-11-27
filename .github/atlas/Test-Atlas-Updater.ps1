# Prueba en seco del updater sobre una COPIA (no toca tu instalacion real).
#   powershell -ExecutionPolicy Bypass -File .\Test-Atlas-Updater.ps1
[CmdletBinding()]
param(
    [string]$SourcePort = 'C:\Games\Bloodborne-1.6\bbport-windows',
    [string]$TestPort   = 'C:\Games\bbport-atlas-test',
    [string]$UpdaterDir = '',
    [switch]$SkipCopy,
    [switch]$SkipRestore
)
$ErrorActionPreference = 'Stop'
if (-not $UpdaterDir) { $UpdaterDir = Join-Path $SourcePort "mods\Hunter's Atlas\updater" }
$updater = Join-Path $UpdaterDir 'update-atlas.ps1'
if (-not (Test-Path -LiteralPath $updater)) { throw "No se encontro $updater" }
function Say($t, $c = 'Cyan') { Write-Host "[TEST] $t" -ForegroundColor $c }

if (-not $SkipCopy) {
    if (Test-Path -LiteralPath $TestPort) {
        Say "Borrando copia anterior en $TestPort" 'Yellow'
        Remove-Item -LiteralPath $TestPort -Recurse -Force
    }
    Say "Copiando $SourcePort -> $TestPort (1.3 GB)..."
    New-Item -ItemType Directory -Path $TestPort -Force | Out-Null
    robocopy $SourcePort $TestPort /E /NFL /NDL /NJH /NJS /NP /R:1 /W:1 | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "robocopy fallo ($LASTEXITCODE)" }
}
$free = [math]::Round((Get-PSDrive C).Free / 1GB, 1)
Say "Espacio libre en C: $free GB"

Say "--- 1) CheckOnly sobre la copia ---" 'Cyan'
& $updater -Port $TestPort -CheckOnly

Say "--- 2) Actualizacion real sobre la copia ---" 'Cyan'
& $updater -Port $TestPort

Say "--- 3) Verificaciones ---" 'Cyan'
$listPath = Join-Path $TestPort 'bbport-files.json'
$bytes = [System.IO.File]::ReadAllBytes($listPath)
$hasBom = ($bytes.Length -ge 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF)
$manifest = Get-Content -LiteralPath $listPath -Raw -Encoding UTF8 | ConvertFrom-Json
$probe = Join-Path $TestPort 'bin\bb-probe.exe'
$probeHash = if (Test-Path -LiteralPath $probe) { (Get-FileHash $probe -Algorithm SHA256).Hash.ToLower() } else { '' }
$nativeMods = Test-Path -LiteralPath (Join-Path $TestPort 'scripts\native_mods.py')
$fsr24 = Test-Path -LiteralPath (Join-Path $TestPort 'bin\fsr24')
$chalice = Test-Path -LiteralPath (Join-Path $TestPort 'bin\LocalChalice\catalog.bin')
$modDir = Join-Path $TestPort "mods\Hunter's Atlas"
$modOk = Test-Path -LiteralPath (Join-Path $modDir 'native\hunters_atlas.dll')
$saveDir = Join-Path $TestPort 'user'
$saveOk = Test-Path -LiteralPath $saveDir
$backup = @(Get-ChildItem -LiteralPath $TestPort -Directory -Filter 'host-backup-atlas-*' | Sort-Object Name -Descending)
$restoreInfo = $backup.Count -gt 0 -and (Test-Path -LiteralPath (Join-Path $backup[0].FullName 'restore-info.json'))

$report = [ordered]@{
    Version          = $manifest.version
    BOM_en_json      = $hasBom
    Probe_coincide   = ($probeHash -eq [string]$manifest.files.'bin/bb-probe.exe')
    native_mods_py   = $nativeMods
    bin_fsr24        = $fsr24
    LocalChalice     = $chalice
    Mod_Atlas        = $modOk
    User_conservado  = $saveOk
    Backups          = $backup.Count
    Restore_info     = $restoreInfo
}
$report.GetEnumerator() | ForEach-Object { "{0,-16} {1}" -f $_.Key, $_.Value }

if (-not $SkipRestore) {
    Say "--- 4) Restore sobre la copia ---" 'Cyan'
    & $updater -Port $TestPort -Restore
    $after = Get-Content -LiteralPath $listPath -Raw -Encoding UTF8 | ConvertFrom-Json
    Say "Version tras restore: $($after.version)"
}
Say "Listo. Copia de prueba en: $TestPort" 'Green'
