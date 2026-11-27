# SPDX-License-Identifier: GPL-2.0-or-later
# Hunter's Atlas Updater for bbport Windows
#
# Checks Supermedo/bloodborne_pc for official bbport releases and
# dizzi1222/bloodborne_pc for prebuilt Hunter's Atlas native-mod host packages.
# - Only updates bbport to a version that already has a matching Atlas host build,
#   so the in-game map never breaks after an update.
# - Verifies SHA-256 checksums on every downloaded archive before touching files.
# - Preserves saves, settings, mods, FSR/DLSS/Seamless files, and creates a
#   timestamped backup (host-backup-atlas-<timestamp>) for one-command rollback.

[CmdletBinding()]
param(
    [Parameter(Mandatory = $false)]
    [string]$Port,

    [switch]$CheckOnly,

    [switch]$Restore,

    [switch]$NoPrerelease,

    [switch]$SkipModUpdate,

    [switch]$Force,

    [int]$WaitSeconds = 120,

    [string]$ForkRepo = 'dizzi1222/bloodborne_pc',

    [string]$UpstreamRepo = 'Supermedo/bloodborne_pc'
)

$ErrorActionPreference = 'Stop'
try {
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 -bor [Net.SecurityProtocolType]::Tls13
} catch {
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
}

function Write-Step {
    param([string]$Message, [string]$Color = 'Cyan')
    Write-Host "[Atlas Updater] $Message" -ForegroundColor $Color
}

function Parse-VersionTuple {
    param([string]$Text)
    if (-not $Text) { return @(0) }
    $matches = [regex]::Matches($Text, '\d+')
    if ($matches.Count -eq 0) { return @(0) }
    return @($matches | ForEach-Object { [int]$_.Value })
}

function Compare-VersionTuple {
    param([int[]]$Left, [int[]]$Right)
    $max = [Math]::Max($Left.Count, $Right.Count)
    for ($i = 0; $i -lt $max; $i++) {
        $a = if ($i -lt $Left.Count) { $Left[$i] } else { 0 }
        $b = if ($i -lt $Right.Count) { $Right[$i] } else { 0 }
        if ($a -lt $b) { return -1 }
        if ($a -gt $b) { return 1 }
    }
    return 0
}

function Resolve-BbportRoot {
    param([string]$ExplicitPort)
    if ($ExplicitPort) {
        return (Resolve-Path -LiteralPath $ExplicitPort -ErrorAction Stop).Path
    }
    $cursor = $PSScriptRoot
    for ($i = 0; $i -lt 6 -and $cursor; $i++) {
        if ((Test-Path -LiteralPath (Join-Path $cursor 'bbport-files.json')) -and
            (Test-Path -LiteralPath (Join-Path $cursor 'Bloodborne.exe'))) {
            return (Resolve-Path -LiteralPath $cursor).Path
        }
        $cursor = Split-Path -Parent $cursor
    }
    try {
        $desktopLink = Join-Path ([Environment]::GetFolderPath('Desktop')) 'Bloodborne.lnk'
        if (Test-Path -LiteralPath $desktopLink) {
            $shell = New-Object -ComObject WScript.Shell
            $target = $shell.CreateShortcut($desktopLink).TargetPath
            if ($target -and (Test-Path -LiteralPath $target)) {
                $dir = Split-Path -Parent $target
                if (Test-Path -LiteralPath (Join-Path $dir 'bbport-files.json')) {
                    return $dir
                }
            }
        }
    } catch {
    }
    $defaultPath = 'C:\Games\Bloodborne-1.6\bbport-windows'
    if (Test-Path -LiteralPath (Join-Path $defaultPath 'bbport-files.json')) {
        return $defaultPath
    }
    throw "No se pudo detectar la carpeta de bbport. Usa -Port `"C:\ruta\a\bbport-windows`"."
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

function Wait-ForPortIdle {
    param([string]$RootPath, [int]$TimeoutSeconds)
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    $notifiedMutex = $false
    while (Test-UpdateMutexHeld) {
        if ((Get-Date) -ge $deadline) {
            throw "El actualizador oficial de bbport sigue en curso despues de $TimeoutSeconds s."
        }
        if (-not $notifiedMutex) {
            Write-Step "Esperando a que termine el actualizador oficial de bbport (Local\bbport-update)..." "Yellow"
            $notifiedMutex = $true
        }
        Start-Sleep -Seconds 1
    }
    $notifiedProc = $false
    while ($true) {
        $procs = Get-RunningPortProcesses -RootPath $RootPath
        if ($procs.Count -eq 0) {
            break
        }
        $names = ($procs | ForEach-Object { $_.ProcessName } | Sort-Object -Unique) -join ', '
        if ((Get-Date) -ge $deadline) {
            throw "Cierra Bloodborne y el launcher antes de actualizar (en ejecucion: $names)."
        }
        if (-not $notifiedProc) {
            Write-Step "Esperando a que se cierren: $names ..." "Yellow"
            $notifiedProc = $true
        }
        Start-Sleep -Seconds 2
    }
}

function Invoke-GitHubJson {
    param([string]$Url)
    $headers = @{
        'Accept'     = 'application/vnd.github+json'
        'User-Agent' = 'HuntersAtlas-Updater/1.0'
    }
    if ($env:GITHUB_TOKEN) {
        $headers['Authorization'] = "Bearer $($env:GITHUB_TOKEN)"
    }
    return Invoke-RestMethod -Uri $Url -Headers $headers -Method Get -TimeoutSec 30
}

function Download-VerifiedFile {
    param(
        [Parameter(Mandatory = $true)][string]$Url,
        [Parameter(Mandatory = $true)][string]$Destination,
        [Parameter(Mandatory = $false)][string]$ExpectedSha256
    )
    New-Item -ItemType Directory -Path (Split-Path -Parent $Destination) -Force | Out-Null
    if (Test-Path -LiteralPath $Destination) {
        Remove-Item -LiteralPath $Destination -Force
    }
    $curl = Get-Command curl.exe -ErrorAction SilentlyContinue
    if ($curl) {
        & $curl.Source -fL --retry 3 --retry-delay 2 -A "HuntersAtlas-Updater/1.0" -o $Destination $Url
        if ($LASTEXITCODE -ne 0) {
            throw "Error descargando $Url (curl exit $LASTEXITCODE)."
        }
    } else {
        Invoke-WebRequest -Uri $Url -OutFile $Destination -UserAgent 'HuntersAtlas-Updater/1.0' -UseBasicParsing
    }
    $actualSha = (Get-FileHash -LiteralPath $Destination -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($ExpectedSha256) {
        $cleanExpected = ($ExpectedSha256 -replace '^sha256:', '').Trim().ToLowerInvariant()
        if ($cleanExpected -and ($actualSha -ne $cleanExpected)) {
            Remove-Item -LiteralPath $Destination -Force -ErrorAction SilentlyContinue
            throw "SHA-256 no coincide para $(Split-Path -Leaf $Destination). Esperado: $cleanExpected, recibido: $actualSha"
        }
    }
    return $actualSha
}

function Restore-LatestHostBackup {
    param([string]$RootPath)
    Wait-ForPortIdle -RootPath $RootPath -TimeoutSeconds $WaitSeconds
    $backups = @(Get-ChildItem -LiteralPath $RootPath -Directory -Filter 'host-backup-atlas-*' -ErrorAction SilentlyContinue |
        Sort-Object Name -Descending)
    if ($backups.Count -eq 0) {
        throw "No se encontro ningun backup host-backup-atlas-* en $RootPath."
    }
    $latest = $backups[0].FullName
    Write-Step "Restaurando backup desde: $latest" "Yellow"
    $infoPath = Join-Path $latest 'restore-info.json'
    if (Test-Path -LiteralPath $infoPath) {
        $info = Get-Content -LiteralPath $infoPath -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($info.replaced_internal -and (Test-Path -LiteralPath (Join-Path $latest '_internal') -PathType Container)) {
            $targetInternal = Join-Path $RootPath '_internal'
            if (Test-Path -LiteralPath $targetInternal) {
                Remove-Item -LiteralPath $targetInternal -Recurse -Force
            }
            Copy-Item -LiteralPath (Join-Path $latest '_internal') -Destination $targetInternal -Recurse -Force
        }
        foreach ($rel in @($info.added_files)) {
            if ($rel) {
                $p = Join-Path $RootPath ($rel.Replace('/', '\'))
                if (Test-Path -LiteralPath $p -PathType Leaf) {
                    Remove-Item -LiteralPath $p -Force
                }
            }
        }
    }
    Get-ChildItem -LiteralPath $latest -File -Recurse | Where-Object { $_.Name -ne 'restore-info.json' } | ForEach-Object {
        $rel = $_.FullName.Substring($latest.Length + 1)
        if (-not $rel.StartsWith('_internal\', [System.StringComparison]::OrdinalIgnoreCase)) {
            $dest = Join-Path $RootPath $rel
            New-Item -ItemType Directory -Path (Split-Path -Parent $dest) -Force | Out-Null
            Copy-Item -LiteralPath $_.FullName -Destination $dest -Force
        }
    }
    $newManifest = Get-Content -LiteralPath (Join-Path $RootPath 'bbport-files.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    Write-Step "Restauracion completada. Version actual: $($newManifest.version)" "Green"
}

function Get-LocalState {
    param([string]$RootPath)
    $listPath = Join-Path $RootPath 'bbport-files.json'
    if (-not (Test-Path -LiteralPath $listPath)) {
        throw "No se encontro bbport-files.json en $RootPath"
    }
    $manifest = Get-Content -LiteralPath $listPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $ver = [string]$manifest.version
    $baseVer = $ver
    $atlasRev = 0
    if ($ver -match '^(\d+(?:\.\d+)*)-atlas\.(\d+)$') {
        $baseVer = $Matches[1]
        $atlasRev = [int]$Matches[2]
    }
    $probePath = Join-Path $RootPath 'bin\bb-probe.exe'
    $probeHash = if (Test-Path -LiteralPath $probePath) {
        (Get-FileHash -LiteralPath $probePath -Algorithm SHA256).Hash.ToLowerInvariant()
    } else { '' }
    $expectedProbeHash = [string]$manifest.files.'bin/bb-probe.exe'
    $hasNativeModsPy = Test-Path -LiteralPath (Join-Path $RootPath 'scripts\native_mods.py')
    $hostIntact = ($atlasRev -gt 0) -and $hasNativeModsPy -and ($probeHash -eq $expectedProbeHash)

    $modDir = Join-Path $RootPath "mods\Hunter's Atlas"
    $modManifestPath = Join-Path $modDir 'bbport-native-mod.json'
    $modDllPath = Join-Path $modDir 'native\hunters_atlas.dll'
    $modInstalled = (Test-Path -LiteralPath $modManifestPath) -and (Test-Path -LiteralPath $modDllPath)
    $modDllHash = if ($modInstalled) {
        (Get-FileHash -LiteralPath $modDllPath -Algorithm SHA256).Hash.ToLowerInvariant()
    } else { '' }

    return [PSCustomObject]@{
        Version      = $ver
        BaseVersion  = $baseVer
        AtlasRev     = $atlasRev
        HostIntact   = $hostIntact
        ProbeHash    = $probeHash
        ModInstalled = $modInstalled
        ModDir       = $modDir
        ModDllHash   = $modDllHash
    }
}

function Get-UpstreamReleases {
    param([string]$Repo)
    $raw = Invoke-GitHubJson -Url "https://api.github.com/repos/$Repo/releases?per_page=30"
    $results = New-Object System.Collections.Generic.List[object]
    foreach ($rel in @($raw)) {
        if ($rel.draft -or $rel.prerelease) { continue }
        $tag = [string]$rel.tag_name
        if ($tag -notmatch '^windows-v(\d+(?:\.\d+)*)$') { continue }
        $baseVer = $Matches[1]
        $zipAsset = @($rel.assets | Where-Object { $_.name -ieq 'Bloodborne-Windows.zip' }) | Select-Object -First 1
        if (-not $zipAsset) {
            $zipAsset = @($rel.assets | Where-Object {
                $_.name -like '*.zip' -and $_.name -notmatch '(^|[-_.])(src|source|sources)([-_.]|$)'
            }) | Select-Object -First 1
        }
        if (-not $zipAsset) { continue }
        $sha = ''
        if ($zipAsset.digest -and ([string]$zipAsset.digest -match '^sha256:([0-9a-fA-F]{64})$')) {
            $sha = $Matches[1].ToLowerInvariant()
        }
        $results.Add([PSCustomObject]@{
            Tag        = $tag
            Version    = $baseVer
            Tuple      = [int[]](Parse-VersionTuple -Text $baseVer)
            ZipUrl     = [string]$zipAsset.browser_download_url
            ZipSha256  = $sha
            ZipSize    = [int64]$zipAsset.size
            HtmlUrl    = [string]$rel.html_url
        })
    }
    return @($results | Sort-Object -Property @{
        Expression = { ($_.Tuple | ForEach-Object { $_.ToString('D6') }) -join '.' }
        Descending = $true
    })
}

function Get-ForkArtifacts {
    param([string]$Repo, [bool]$AllowPrerelease)
    $raw = Invoke-GitHubJson -Url "https://api.github.com/repos/$Repo/releases?per_page=50"
    $hosts = New-Object System.Collections.Generic.List[object]
    $mods = New-Object System.Collections.Generic.List[object]

    foreach ($rel in @($raw)) {
        if ($rel.draft) { continue }
        if ($rel.prerelease -and -not $AllowPrerelease) { continue }
        $tag = [string]$rel.tag_name

        foreach ($asset in @($rel.assets)) {
            $aname = [string]$asset.name
            if ($aname -match '^(?:bbport-atlas-host|Hunters-Atlas-[0-9.]+-bbport-host)-(\d+(?:\.\d+)*)-atlas\.(\d+)\.zip$') {
                $baseVer = $Matches[1]
                $rev = [int]$Matches[2]
                $sha = ''
                if ($asset.digest -and ([string]$asset.digest -match '^sha256:([0-9a-fA-F]{64})$')) {
                    $sha = $Matches[1].ToLowerInvariant()
                }
                $metaAsset = @($rel.assets | Where-Object { $_.name -ieq 'atlas-host.json' }) | Select-Object -First 1
                $hosts.Add([PSCustomObject]@{
                    ReleaseTag  = $tag
                    HostVersion = "$baseVer-atlas.$rev"
                    BaseVersion = $baseVer
                    BaseTuple   = [int[]](Parse-VersionTuple -Text $baseVer)
                    Revision    = $rev
                    Prerelease  = [bool]$rel.prerelease
                    ZipName     = $aname
                    ZipUrl      = [string]$asset.browser_download_url
                    ZipSha256   = $sha
                    ZipSize     = [int64]$asset.size
                    MetaUrl     = if ($metaAsset) { [string]$metaAsset.browser_download_url } else { '' }
                    HtmlUrl     = [string]$rel.html_url
                })
            }
            elseif ($aname -match '^Hunters-Atlas-(\d+(?:\.\d+)*)-bbport-mod\.zip$') {
                $modVer = $Matches[1]
                $sha = ''
                if ($asset.digest -and ([string]$asset.digest -match '^sha256:([0-9a-fA-F]{64})$')) {
                    $sha = $Matches[1].ToLowerInvariant()
                }
                $mods.Add([PSCustomObject]@{
                    ReleaseTag = $tag
                    ModVersion = $modVer
                    ModTuple   = [int[]](Parse-VersionTuple -Text $modVer)
                    ZipName    = $aname
                    ZipUrl     = [string]$asset.browser_download_url
                    ZipSha256  = $sha
                    ZipSize    = [int64]$asset.size
                })
            }
        }
    }

    $sortedHosts = @($hosts | Sort-Object -Property @{
        Expression = { (($_.BaseTuple | ForEach-Object { $_.ToString('D6') }) -join '.') + '.' + $_.Revision.ToString('D6') }
        Descending = $true
    })
    $sortedMods = @($mods | Sort-Object -Property @{
        Expression = { ($_.ModTuple | ForEach-Object { $_.ToString('D6') }) -join '.' }
        Descending = $true
    })

    return [PSCustomObject]@{
        Hosts = $sortedHosts
        Mods  = $sortedMods
    }
}

function Apply-OfficialBbportArchive {
    param(
        [Parameter(Mandatory = $true)][string]$ZipPath,
        [Parameter(Mandatory = $true)][string]$RootPath
    )
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $extractRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("bbport-official-" + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $extractRoot -Force | Out-Null
    try {
        [System.IO.Compression.ZipFile]::ExtractToDirectory($ZipPath, $extractRoot)
        $pkgRoot = $extractRoot
        if (-not (Test-Path -LiteralPath (Join-Path $pkgRoot 'Bloodborne.exe')) -and
            (Test-Path -LiteralPath (Join-Path $pkgRoot 'bbport-windows\Bloodborne.exe'))) {
            $pkgRoot = Join-Path $pkgRoot 'bbport-windows'
        }
        if (-not (Test-Path -LiteralPath (Join-Path $pkgRoot 'Bloodborne.exe')) -or
            -not (Test-Path -LiteralPath (Join-Path $pkgRoot '_internal\base_library.zip'))) {
            throw "El archivo oficial descargado no contiene una instalacion completa de bbport."
        }

        $preserveNames = @(
            'user', 'out', 'mods', 'bbport.ini', 'input.ini', 'mods.json', 'patches.json',
            'fsr4vk', 'seamless', 'bbsc', 'last_run.log'
        )

        # Carry over player-added files in patches/ and fsr4_shaders/ into the new tree before swapping
        foreach ($carryDir in @('patches', 'fsr4_shaders')) {
            $oldCarry = Join-Path $RootPath $carryDir
            $newCarry = Join-Path $pkgRoot $carryDir
            if (Test-Path -LiteralPath $oldCarry -PathType Container) {
                Get-ChildItem -LiteralPath $oldCarry -File -Recurse | ForEach-Object {
                    $rel = $_.FullName.Substring($oldCarry.Length + 1)
                    $dest = Join-Path $newCarry $rel
                    if (-not (Test-Path -LiteralPath $dest)) {
                        New-Item -ItemType Directory -Path (Split-Path -Parent $dest) -Force | Out-Null
                        Copy-Item -LiteralPath $_.FullName -Destination $dest -Force
                    }
                }
            }
        }

        # Copy all entries except _internal and Bloodborne.exe first, then _internal and Bloodborne.exe last
        $entries = @(Get-ChildItem -LiteralPath $pkgRoot -Force | Where-Object {
            $preserveNames -notcontains $_.Name.ToLowerInvariant()
        })
        $ordered = @($entries | Sort-Object -Property @{
            Expression = {
                if ($_.Name -ieq 'Bloodborne.exe') { 2 }
                elseif ($_.Name -ieq '_internal') { 1 }
                else { 0 }
            }
        })

        foreach ($entry in $ordered) {
            $dest = Join-Path $RootPath $entry.Name
            if ($entry.PSIsContainer) {
                if (Test-Path -LiteralPath $dest) {
                    Remove-Item -LiteralPath $dest -Recurse -Force
                }
                Copy-Item -LiteralPath $entry.FullName -Destination $dest -Recurse -Force
            } else {
                Copy-Item -LiteralPath $entry.FullName -Destination $dest -Force
            }
        }
    } finally {
        Remove-Item -LiteralPath $extractRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}

$root = Resolve-BbportRoot -ExplicitPort $Port
if ($Restore) {
    Restore-LatestHostBackup -RootPath $root
    exit 0
}

$local = Get-LocalState -RootPath $root
Write-Step "Instalacion detectada: $root"
Write-Step "Version local: $($local.Version) (base: $($local.BaseVersion), host Atlas activo: $($local.HostIntact))"

$upstreamReleases = Get-UpstreamReleases -Repo $UpstreamRepo
if ($upstreamReleases.Count -eq 0) {
    throw "No se encontraron releases oficiales de Windows en $UpstreamRepo."
}
$latestUpstream = $upstreamReleases[0]

$forkArtifacts = Get-ForkArtifacts -Repo $ForkRepo -AllowPrerelease (-not $NoPrerelease)
if ($forkArtifacts.Hosts.Count -eq 0) {
    throw "No se encontraron paquetes host de Hunter's Atlas en $ForkRepo."
}

# Pick the newest official release that has a matching Atlas host package
$upstreamByVer = @{}
foreach ($u in $upstreamReleases) {
    $upstreamByVer[$u.Version] = $u
}

$bestHost = $null
$matchingUpstream = $null
foreach ($h in $forkArtifacts.Hosts) {
    if ($upstreamByVer.ContainsKey($h.BaseVersion)) {
        $bestHost = $h
        $matchingUpstream = $upstreamByVer[$h.BaseVersion]
        break
    }
}
if (-not $bestHost) {
    $bestHost = $forkArtifacts.Hosts[0]
}

Write-Step "Ultima release oficial de bbport: $($latestUpstream.Version) ($($latestUpstream.Tag))"
Write-Step "Ultimo host Atlas disponible:     $($bestHost.HostVersion) ($($bestHost.ReleaseTag))"

if ((Compare-VersionTuple -Left $latestUpstream.Tuple -Right $bestHost.BaseTuple) -gt 0) {
    Write-Host ""
    Write-Host "AVISO: bbport $($latestUpstream.Version) ya salio, pero el host de Hunter's Atlas para $($latestUpstream.Version) aun no esta disponible." -ForegroundColor Yellow
    Write-Host "       La ultima version compatible con el mapa es $($bestHost.HostVersion)." -ForegroundColor Yellow
    Write-Host ""
}

$localBaseTuple = Parse-VersionTuple -Text $local.BaseVersion
$baseComparison = Compare-VersionTuple -Left $localBaseTuple -Right $bestHost.BaseTuple
$needsOfficialUpdate = ($baseComparison -lt 0)
$needsHostApply = $Force -or $needsOfficialUpdate -or (-not $local.HostIntact) -or
    (($baseComparison -eq 0) -and ($local.AtlasRev -lt $bestHost.Revision))

$latestMod = if ($forkArtifacts.Mods.Count -gt 0) { $forkArtifacts.Mods[0] } else { $null }
$needsModInstall = (-not $SkipModUpdate) -and (-not $local.ModInstalled) -and ($null -ne $latestMod)

if ($baseComparison -gt 0) {
    Write-Host "Tu bbport local ($($local.BaseVersion)) es mas nuevo que el ultimo host Atlas disponible ($($bestHost.HostVersion))." -ForegroundColor Yellow
    Write-Host "No se aplicara un host mas antiguo para no mezclar versiones. Espera a que el CI publique el host para $($local.BaseVersion)." -ForegroundColor Yellow
    exit 0
}

if ($CheckOnly) {
    Write-Host ""
    Write-Host "=== Resumen (--CheckOnly) ===" -ForegroundColor Cyan
    Write-Host "  Carpeta bbport:          $root"
    Write-Host "  Version instalada:       $($local.Version)"
    Write-Host "  Host Atlas integro:      $($local.HostIntact)"
    Write-Host "  Mod instalado:           $($local.ModInstalled)"
    Write-Host "  Ultima oficial bbport:   $($latestUpstream.Version)"
    Write-Host "  Objetivo compatible:     $($bestHost.HostVersion)"
    Write-Host "  Actualizar bbport base:  $needsOfficialUpdate"
    Write-Host "  Aplicar host Atlas:      $needsHostApply"
    Write-Host "  Instalar mod Atlas:      $needsModInstall"
    exit 0
}

if (-not $needsOfficialUpdate -and -not $needsHostApply -and -not $needsModInstall) {
    Write-Step "Todo esta al dia ($($local.Version)). No hace falta actualizar." "Green"
    exit 0
}

Wait-ForPortIdle -RootPath $root -TimeoutSeconds $WaitSeconds

$workDir = Join-Path ([System.IO.Path]::GetTempPath()) ("atlas-updater-" + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $workDir -Force | Out-Null

try {
    # Download and verify the Atlas host package FIRST before touching the installation
    if ($needsHostApply) {
        $hostZipPath = Join-Path $workDir $bestHost.ZipName
        Write-Step "Descargando host Atlas $($bestHost.HostVersion) ($([Math]::Round($bestHost.ZipSize / 1MB, 1)) MB)..."
        [void](Download-VerifiedFile -Url $bestHost.ZipUrl -Destination $hostZipPath -ExpectedSha256 $bestHost.ZipSha256)
        Write-Step "Hash SHA-256 del host Atlas verificado correctamente." "Green"
    }

    # If the installation is on an older bbport base version, download, verify, and apply official bbport first
    if ($needsOfficialUpdate) {
        if (-not $matchingUpstream) {
            throw "No se encontro el paquete oficial Bloodborne-Windows.zip para $($bestHost.BaseVersion)."
        }
        $officialZipPath = Join-Path $workDir "Bloodborne-Windows-$($matchingUpstream.Version).zip"
        Write-Step "Descargando bbport oficial $($matchingUpstream.Version) ($([Math]::Round($matchingUpstream.ZipSize / 1MB, 1)) MB)..."
        [void](Download-VerifiedFile -Url $matchingUpstream.ZipUrl -Destination $officialZipPath -ExpectedSha256 $matchingUpstream.ZipSha256)
        Write-Step "Hash SHA-256 de bbport oficial $($matchingUpstream.Version) verificado." "Green"

        Write-Step "Actualizando bbport base a $($matchingUpstream.Version) (conservando partidas, ajustes y mods)..."
        Apply-OfficialBbportArchive -ZipPath $officialZipPath -RootPath $root
        Write-Step "bbport base actualizado a $($matchingUpstream.Version)." "Green"
    }

    if ($needsHostApply) {
        Add-Type -AssemblyName System.IO.Compression.FileSystem
        $hostExtract = Join-Path $workDir 'host-extracted'
        [System.IO.Compression.ZipFile]::ExtractToDirectory($hostZipPath, $hostExtract)
        $applyScript = Join-Path $hostExtract 'apply-host.ps1'
        if (-not (Test-Path -LiteralPath $applyScript)) {
            $applyScript = Join-Path $PSScriptRoot 'apply-host.ps1'
        }
        Write-Step "Aplicando host Atlas $($bestHost.HostVersion)..."
        & $applyScript -Port $root -ManifestVersion $bestHost.HostVersion -Force
    }

    if ($needsModInstall -and $latestMod) {
        $modZipPath = Join-Path $workDir $latestMod.ZipName
        Write-Step "Descargando mod Hunter's Atlas $($latestMod.ModVersion) ($([Math]::Round($latestMod.ZipSize / 1MB, 1)) MB)..."
        [void](Download-VerifiedFile -Url $latestMod.ZipUrl -Destination $modZipPath -ExpectedSha256 $latestMod.ZipSha256)
        Add-Type -AssemblyName System.IO.Compression.FileSystem
        $modExtract = Join-Path $workDir 'mod-extracted'
        [System.IO.Compression.ZipFile]::ExtractToDirectory($modZipPath, $modExtract)
        $extractedModRoot = $modExtract
        if (Test-Path -LiteralPath (Join-Path $modExtract "Hunter's Atlas\bbport-native-mod.json")) {
            $extractedModRoot = Join-Path $modExtract "Hunter's Atlas"
        }
        $targetModDir = $local.ModDir
        $savedSettings = $null
        $settingsPath = Join-Path $targetModDir 'config\settings.ini'
        if (Test-Path -LiteralPath $settingsPath) {
            $savedSettings = Get-Content -LiteralPath $settingsPath -Raw -Encoding UTF8
        }
        New-Item -ItemType Directory -Path $targetModDir -Force | Out-Null
        Copy-Item -Path (Join-Path $extractedModRoot '*') -Destination $targetModDir -Recurse -Force
        if ($savedSettings) {
            $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
            [System.IO.File]::WriteAllText($settingsPath, $savedSettings, $utf8NoBom)
        }
        Write-Step "Mod Hunter's Atlas $($latestMod.ModVersion) instalado en $targetModDir" "Green"
    }

    Write-Host ""
    Write-Step "Actualizacion completada con exito. Version activa: $($bestHost.HostVersion)" "Green"
} finally {
    Remove-Item -LiteralPath $workDir -Recurse -Force -ErrorAction SilentlyContinue
}
