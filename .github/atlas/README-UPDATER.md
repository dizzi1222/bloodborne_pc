# Hunter's Atlas Updater for bbport (Windows)

`Update-Hunters-Atlas.bat` (`update-atlas.ps1`) keeps **bbport for Windows** and the **Hunter's Atlas** native-mod host synchronized without compiling anything on your PC.

## How it works

1. Checks the latest official release in [`Supermedo/bloodborne_pc`](https://github.com/Supermedo/bloodborne_pc/releases) and the latest prebuilt Atlas host in [`dizzi1222/bloodborne_pc`](https://github.com/dizzi1222/bloodborne_pc/releases).
2. **Safe version gate**:
   - If a new official `bbport` release is out and the matching Atlas host is already built, the updater downloads the official `Bloodborne-Windows.zip` (verifying GitHub's SHA-256 digest), updates `bbport` while preserving your saves, settings, mods, and FSR/DLSS/Seamless files, and immediately applies the matching Atlas host on top.
   - If you already updated `bbport` from the official launcher, the updater skips downloading `Bloodborne-Windows.zip` and only downloads and applies the matching Atlas host (~60 MB).
   - If a brand-new `bbport` release just came out and the Atlas CI build is not ready yet, the updater **does not overwrite** your working Atlas installation and lets you know which version is currently supported.
3. Saves a timestamped backup under `host-backup-atlas-<timestamp>` in your `bbport-windows` folder and rewrites `bbport-files.json` (UTF-8 without BOM) so the launcher never shows a mixed-version warning.

## Usage

### Double-click (recommended)

Place `Update-Hunters-Atlas.bat` and `update-atlas.ps1` inside your `bbport-windows` folder (or inside `bbport-windows\mods\Hunter's Atlas\`) and double-click **`Update-Hunters-Atlas.bat`**.

### PowerShell options

```powershell
# Check status without changing any files:
powershell -ExecutionPolicy Bypass -File .\update-atlas.ps1 -CheckOnly

# Update a specific bbport installation folder:
powershell -ExecutionPolicy Bypass -File .\update-atlas.ps1 -Port "C:\Games\Bloodborne-1.6\bbport-windows"

# Roll back to the previous host backup:
powershell -ExecutionPolicy Bypass -File .\update-atlas.ps1 -Restore
```
