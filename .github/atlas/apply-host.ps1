# SPDX-License-Identifier: GPL-2.0-or-later
# Hunter's Atlas host patch installer for bbport Windows.
#
# Overlays the native-mod host binaries and scripts onto an existing bbport for
# Windows installation without deleting unrelated files in bin/ (such as FSR 2.4,
# FSR 4.1.1, LocalChalice, DLSS, or Seamless co-op). Every replaced file is
# backed up to host-backup-atlas-<timestamp>/ with a restore manifest, and
# bbport-files.json is rewritten in UTF-8 without BOM.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File .\apply-host.ps1 -Port "C:\Games\Bloodborne-1.6\bbport-windows"

[CmdletBinding()]
param(
    [Parameter(Mandatory = $false)]
    [string]$Port,

    [Parameter(Mandatory = $false)]
    [string]$ManifestVersion,

    [switch]$Force
)

$ErrorActionPreference = 'Stop'

function Resolve-BbportRoot {
    param([string]$ExplicitPort)
    if ($ExplicitPort) {
        $resolved = Resolve-Path -LiteralPath $ExplicitPort -ErrorAction Stop
        return $resolved.Path
    }
    $cursor = $PSScriptRoot
    for ($i = 0; $i -lt 5 -and $cursor; $i++) {
        if ((Test-Path -LiteralPath (Join-Path $cursor 'bbport-files.json')) -and
            (Test-Path -LiteralPath (Join-Path $cursor 'Bloodborne.exe'))) {
            return (Resolve-Path -LiteralPath $cursor).Path
        }
        $cursor = Split-Path -Parent $cursor
    }
    $defaultPath = 'C:\Games\Bloodborne-1.6\bbport-windows'
    if (Test-Path -LiteralPath (Join-Path $defaultPath 'bbport-files.json')) {
        return $defaultPath
    }
    throw "Could not auto-detect the bbport folder. Pass -Port `"C:\path\to\bbport-windows`"."
}

function Test-UpdateMutexHeld {
    try {
        $mutex = $null
        if ([System.Threading.Mutex]::TryOpenExisting('Local\bbport-update', [ref]$mutex)) {
            $mutex.Dispose()
            return $true
        }
    } catch {
    }
    return $false
}

function Get-RunningPortProcesses {
    param([string]$RootPath)
    $prefix = $RootPath.TrimEnd('\', '/') + '\'
    return @(Get-Process -ErrorAction SilentlyContinue | Where-Object {
        try {
            $_.Path -and $_.Path.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase)
        } catch {
            $false
        }
    })
}

$root = Resolve-BbportRoot -ExplicitPort $Port
$listPath = Join-Path $root 'bbport-files.json'
if (-not (Test-Path -LiteralPath $listPath)) {
    throw "Not a bbport installation (bbport-files.json missing): $root"
}

if (Test-UpdateMutexHeld) {
    throw "The official bbport updater (Local\bbport-update) is currently running. Wait for it to finish first."
}

$running = Get-RunningPortProcesses -RootPath $root
if ($running.Count -gt 0) {
    $names = ($running | ForEach-Object { $_.ProcessName } | Sort-Object -Unique) -join ', '
    throw "Close Bloodborne and the launcher before applying the host patch (running: $names)."
}

$hostMetaPath = Join-Path $PSScriptRoot 'atlas-host.json'
$hostMeta = $null
if (Test-Path -LiteralPath $hostMetaPath) {
    $hostMeta = Get-Content -LiteralPath $hostMetaPath -Raw -Encoding UTF8 | ConvertFrom-Json
}

if (-not $ManifestVersion) {
    if ($hostMeta -and $hostMeta.host_version) {
        $ManifestVersion = [string]$hostMeta.host_version
    } else {
        $ManifestVersion = '1.9.8.6-atlas.1'
    }
}

$expectedBase = ($ManifestVersion -replace '-atlas\.\d+$', '')
$list = Get-Content -LiteralPath $listPath -Raw -Encoding UTF8 | ConvertFrom-Json
$currentVersion = [string]$list.version
$currentBase = ($currentVersion -replace '-atlas\.\d+$', '')

if (-not $Force -and $currentBase -and $expectedBase -and ($currentBase -ne $expectedBase)) {
    throw "Host package $ManifestVersion targets bbport $expectedBase, but $root is currently on $currentVersion (base $currentBase). Run Update-Hunters-Atlas.bat to update bbport and the Atlas host together, or pass -Force to override."
}

$requiredEntries = @(
    'bin/bb-probe.exe',
    'run.py',
    'scripts/mods.py',
    'scripts/native_mods.py'
)
foreach ($rel in $requiredEntries) {
    $checkPath = Join-Path $PSScriptRoot ($rel.Replace('/', '\'))
    if (-not (Test-Path -LiteralPath $checkPath)) {
        throw "Host package is incomplete ($rel is missing from $PSScriptRoot)."
    }
}

$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$backup = Join-Path $root "host-backup-atlas-$stamp"
New-Item -ItemType Directory -Path $backup -Force | Out-Null

$backedUpFiles = New-Object System.Collections.Generic.List[string]
$addedFiles = New-Object System.Collections.Generic.List[string]
$removedStaleFiles = New-Object System.Collections.Generic.List[string]

function Backup-RelativeFile {
    param([string]$RelativePath)
    $norm = $RelativePath.Replace('\', '/')
    $target = Join-Path $root ($norm.Replace('/', '\'))
    if (Test-Path -LiteralPath $target -PathType Leaf) {
        $dest = Join-Path $backup ($norm.Replace('/', '\'))
        New-Item -ItemType Directory -Path (Split-Path -Parent $dest) -Force | Out-Null
        Copy-Item -LiteralPath $target -Destination $dest -Force
        if (-not $backedUpFiles.Contains($norm)) {
            $backedUpFiles.Add($norm)
        }
        return $true
    }
    return $false
}

# 1. Back up bbport-files.json
Copy-Item -LiteralPath $listPath -Destination (Join-Path $backup 'bbport-files.json') -Force

# 2. If package ships _internal/, back up and replace _internal/ and Bloodborne.exe as a matched pair
$internalSource = Join-Path $PSScriptRoot '_internal'
$internalTarget = Join-Path $root '_internal'
$replacedInternal = $false
if (Test-Path -LiteralPath $internalSource -PathType Container) {
    if (Test-Path -LiteralPath $internalTarget -PathType Container) {
        Copy-Item -LiteralPath $internalTarget -Destination (Join-Path $backup '_internal') -Recurse -Force
        Remove-Item -LiteralPath $internalTarget -Recurse -Force
    }
    Copy-Item -LiteralPath $internalSource -Destination $internalTarget -Recurse -Force
    $replacedInternal = $true
}

$launcherSource = Join-Path $PSScriptRoot 'Bloodborne.exe'
if (Test-Path -LiteralPath $launcherSource -PathType Leaf) {
    $existed = Backup-RelativeFile -RelativePath 'Bloodborne.exe'
    Copy-Item -LiteralPath $launcherSource -Destination (Join-Path $root 'Bloodborne.exe') -Force
    if (-not $existed) {
        $addedFiles.Add('Bloodborne.exe')
    }
}

# 3. Clean up stale versioned MSYS2 abseil/protobuf DLLs in bin/ if the package ships newer ones
$pkgBin = Join-Path $PSScriptRoot 'bin'
$targetBin = Join-Path $root 'bin'
$pkgAbseilNames = @{}
if (Test-Path -LiteralPath $pkgBin -PathType Container) {
    Get-ChildItem -LiteralPath $pkgBin -Filter 'libabsl_*.dll' -File -ErrorAction SilentlyContinue | ForEach-Object {
        $pkgAbseilNames[$_.Name.ToLowerInvariant()] = $true
    }
}
if ($pkgAbseilNames.Count -gt 0 -and (Test-Path -LiteralPath $targetBin -PathType Container)) {
    Get-ChildItem -LiteralPath $targetBin -Filter 'libabsl_*.dll' -File -ErrorAction SilentlyContinue | ForEach-Object {
        if (-not $pkgAbseilNames.ContainsKey($_.Name.ToLowerInvariant())) {
            $rel = "bin/$($_.Name)"
            [void](Backup-RelativeFile -RelativePath $rel)
            Remove-Item -LiteralPath $_.FullName -Force
            $removedStaleFiles.Add($rel)
            if ($list.files.PSObject.Properties[$rel]) {
                $list.files.PSObject.Properties.Remove($rel)
            }
        }
    }
}

# 4. Overlay bin/, scripts/, and run.py (preserving non-package files in bin/ and scripts/)
foreach ($folderName in @('bin', 'scripts')) {
    $srcFolder = Join-Path $PSScriptRoot $folderName
    if (Test-Path -LiteralPath $srcFolder -PathType Container) {
        Get-ChildItem -LiteralPath $srcFolder -File -Recurse | ForEach-Object {
            $subRel = $_.FullName.Substring($srcFolder.Length + 1).Replace('\', '/')
            $rel = "$folderName/$subRel"
            $existed = Backup-RelativeFile -RelativePath $rel
            $destPath = Join-Path $root ($rel.Replace('/', '\'))
            New-Item -ItemType Directory -Path (Split-Path -Parent $destPath) -Force | Out-Null
            Copy-Item -LiteralPath $_.FullName -Destination $destPath -Force
            if (-not $existed -and -not $addedFiles.Contains($rel)) {
                $addedFiles.Add($rel)
            }
        }
    }
}

$existedRunPy = Backup-RelativeFile -RelativePath 'run.py'
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'run.py') -Destination (Join-Path $root 'run.py') -Force
if (-not $existedRunPy) {
    $addedFiles.Add('run.py')
}

# 5. Refresh bbport-files.json hashes (same rules as scripts/package_files.py) and write UTF-8 without BOM
$list.version = $ManifestVersion

function Set-ManifestHash {
    param([string]$RelativePath)
    $norm = $RelativePath.Replace('\', '/')
    $full = Join-Path $root ($norm.Replace('/', '\'))
    if (Test-Path -LiteralPath $full -PathType Leaf) {
        $leafName = [System.IO.Path]::GetFileName($full).ToLowerInvariant()
        if ($leafName.StartsWith('nvngx')) {
            return
        }
        $hash = (Get-FileHash -LiteralPath $full -Algorithm SHA256).Hash.ToLowerInvariant()
        $list.files | Add-Member -NotePropertyName $norm -NotePropertyValue $hash -Force
    }
}

Set-ManifestHash -RelativePath 'run.py'

if (Test-Path -LiteralPath $targetBin -PathType Container) {
    Get-ChildItem -LiteralPath $targetBin -File -Recurse | ForEach-Object {
        $rel = $_.FullName.Substring($root.Length + 1).Replace('\', '/')
        Set-ManifestHash -RelativePath $rel
    }
}

$targetScripts = Join-Path $root 'scripts'
if (Test-Path -LiteralPath $targetScripts -PathType Container) {
    Get-ChildItem -LiteralPath $targetScripts -Filter '*.py' -File -Recurse | Where-Object {
        $_.FullName -notmatch '[\\/]__pycache__([\\/]|$)'
    } | ForEach-Object {
        $rel = $_.FullName.Substring($root.Length + 1).Replace('\', '/')
        Set-ManifestHash -RelativePath $rel
    }
}

if ($list.files.PSObject.Properties['Bloodborne.exe']) {
    Set-ManifestHash -RelativePath 'Bloodborne.exe'
}

$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
$jsonText = ($list | ConvertTo-Json -Depth 20) + "`n"
[System.IO.File]::WriteAllText($listPath, $jsonText, $utf8NoBom)

$restoreMeta = [ordered]@{
    schema              = 1
    applied_at          = (Get-Date).ToString('o')
    previous_version    = $currentVersion
    applied_version     = $ManifestVersion
    replaced_internal   = $replacedInternal
    backed_up_files     = $backedUpFiles
    added_files         = $addedFiles
    removed_stale_files = $removedStaleFiles
}
$restoreJson = ($restoreMeta | ConvertTo-Json -Depth 10) + "`n"
[System.IO.File]::WriteAllText((Join-Path $backup 'restore-info.json'), $restoreJson, $utf8NoBom)

Write-Host "Hunter's Atlas host $ManifestVersion applied to $root" -ForegroundColor Green
Write-Host "Backup saved at: $backup"
