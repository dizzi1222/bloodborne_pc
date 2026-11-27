# Hunter's Atlas Updater for bbport (Windows)

`HuntersAtlasUpdater.exe` keeps **bbport for Windows** and the **Hunter's Atlas** native-mod host synchronized without compiling anything on your PC. It is a self-contained graphical app (Python + Tkinter, the same stack bbport's own launcher uses): no PowerShell, no execution-policy prompts, no console window.

`Update-Hunters-Atlas.bat` (`update-atlas.ps1`) remains as a fallback for anyone who prefers scripts.

## How it works

1. Checks the latest official release in [`Supermedo/bloodborne_pc`](https://github.com/Supermedo/bloodborne_pc/releases) and the latest prebuilt Atlas host in [`dizzi1222/bloodborne_pc`](https://github.com/dizzi1222/bloodborne_pc/releases).
2. **Safe version gate**:
   - If a new official `bbport` release is out and the matching Atlas host is already built, the updater downloads the official `Bloodborne-Windows.zip` (verifying GitHub's SHA-256 digest), updates `bbport` while preserving your saves, settings, mods, and FSR/DLSS/Seamless files, and immediately applies the matching Atlas host on top.
   - If you already updated `bbport` from the official launcher, the updater skips downloading `Bloodborne-Windows.zip` and only downloads and applies the matching Atlas host (~60 MB).
   - If a brand-new `bbport` release just came out and the Atlas CI build is not ready yet, the updater **does not overwrite** your working Atlas installation and lets you know which version is currently supported.
3. Saves a timestamped backup under `host-backup-atlas-<timestamp>` in your `bbport-windows` folder and rewrites `bbport-files.json` (UTF-8 without BOM) so the launcher never shows a mixed-version warning.

## Usage

### HuntersAtlasUpdater.exe (recommended)

1. Download `Hunters-Atlas-Updater.zip` from the [Atlas host release](https://github.com/dizzi1222/bloodborne_pc/releases).
2. Extract it anywhere — inside `bbport-windows` or `bbport-windows\mods\Hunter's Atlas` is ideal, because the app auto-detects the installation from its own location.
3. Double-click **`HuntersAtlasUpdater.exe`**. It shows your installed version, whether the Atlas host is active, the latest official bbport, and the newest compatible host. Press **Actualizar a …** when offered.
4. Use **Restaurar backup** to roll back the last host change.

The executable can also be run with `--check` (read-only report) or `--restore` from a terminal, and it writes `--json <path>` when you want a machine-readable status.

### Update-Hunters-Atlas.bat

Place `Update-Hunters-Atlas.bat` next to `HuntersAtlasUpdater.exe` (or in `bbport-windows\mods\Hunter's Atlas\updater\`) and double-click it. The `.bat` launches the `.exe` when present and otherwise falls back to PowerShell.

### PowerShell options

```powershell
# Check status without changing any files:
powershell -ExecutionPolicy Bypass -File .\update-atlas.ps1 -CheckOnly

# Update a specific bbport installation folder:
powershell -ExecutionPolicy Bypass -File .\update-atlas.ps1 -Port "C:\Games\Bloodborne-1.6\bbport-windows"

# Roll back to the previous host backup:
powershell -ExecutionPolicy Bypass -File .\update-atlas.ps1 -Restore
```
