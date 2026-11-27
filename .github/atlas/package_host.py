#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Packages the compiled Hunter's Atlas host build for bbport Windows:
- Freezes Bloodborne.exe + _internal/ with Windows Python 3.14 & PyInstaller
- Runs check_launcher_runtime.py and verifies native_mods import inside frozen bundle
- Strips bb-probe.exe, bb-gpu-capabilities.exe, bb-fg401-capabilities.exe
- Collects all required MSYS2 CLANG64 runtime DLLs (via ldd + recursive PE import scan)
- Collects licenses and generates licenses/MSYS2-PACKAGES.md
- Writes atlas-host.json, apply-host.ps1, update-atlas.ps1, Update-Hunters-Atlas.bat, README-HOST.md
- Produces bbport-atlas-host-<version>-atlas.<R>.zip, Hunters-Atlas-Updater.zip, SHA256SUMS.txt, and RELEASE-NOTES.md
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
    print("+", " ".join(str(c) for c in cmd), flush=True)
    return subprocess.run(cmd, check=True, text=True, encoding="utf-8", errors="replace", **kwargs)


def find_windows_python314() -> Path:
    winpy = os.environ.get("WINPYTHON", "").strip()
    if winpy and Path(winpy).is_file():
        return Path(winpy).resolve()
    candidates = [
        Path(sys.executable).resolve(),
        Path(r"C:\Python314\python.exe"),
        Path(r"C:\Program Files\Python314\python.exe"),
        Path.home() / r"AppData\Local\Programs\Python\Python314\python.exe",
    ]
    for cand in candidates:
        if cand.is_file() and "msys64" not in str(cand).lower():
            res = subprocess.run(
                [str(cand), "-c", "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"],
                capture_output=True,
                text=True,
            )
            if res.returncode == 0 and res.stdout.strip() == "3.14":
                return cand
    raise RuntimeError("Windows Python 3.14 not found; set WINPYTHON to python.exe 3.14")


def freeze_launcher(repo_root: Path, win_python: Path) -> Path:
    pyenv = repo_root / "out" / "pyenv"
    venv_py = pyenv / "Scripts" / "python.exe"
    if not venv_py.is_file():
        run([str(win_python), "-m", "venv", str(pyenv)])
    run([str(venv_py), "-m", "pip", "install", "-q", "--disable-pip-version-check", "pyinstaller", "pillow"])

    hidden_modules = [
        "argparse", "base64", "bisect", "collections", "contextlib", "hashlib",
        "json", "re", "shutil", "struct", "tempfile", "xml.etree.ElementTree",
        "urllib.request", "ctypes.wintypes",
    ]
    hidden_args = []
    for mod in hidden_modules:
        hidden_args.extend(["--hidden-import", mod])

    check_script = repo_root / "packaging" / "windows" / "check_launcher_runtime.py"
    if check_script.is_file():
        run([
            str(venv_py), "-m", "PyInstaller", "--noconfirm", "--clean", "--log-level", "WARN", "--console",
            "--name", "launcher-runtime-check",
            "--distpath", str(repo_root / "out" / "pyi-check"),
            "--workpath", str(repo_root / "out" / "pyi-check-work"),
            "--specpath", str(repo_root / "out" / "pyi-check-work"),
            "--paths", str(repo_root / "launcher"),
            str(check_script),
        ])
        check_exe = repo_root / "out" / "pyi-check" / "launcher-runtime-check" / "launcher-runtime-check.exe"
        run([str(check_exe)])

    run([
        str(venv_py), "-m", "PyInstaller", "--noconfirm", "--clean", "--log-level", "WARN", "--windowed",
        "--name", "Bloodborne",
        "--icon", str(repo_root / "launcher" / "bloodborne.ico"),
        "--distpath", str(repo_root / "out" / "pyi-dist"),
        "--workpath", str(repo_root / "out" / "pyi-work"),
        "--specpath", str(repo_root / "out" / "pyi-work"),
        "--paths", str(repo_root / "scripts"),
        *hidden_args,
        "--add-data", f"{repo_root / 'launcher' / 'assets'};assets",
        str(repo_root / "launcher" / "bbport_launcher_win.py"),
    ])

    frozen_dir = repo_root / "out" / "pyi-dist" / "Bloodborne"
    launcher_exe = frozen_dir / "Bloodborne.exe"
    if not launcher_exe.is_file():
        raise RuntimeError(f"Frozen Bloodborne.exe missing at {launcher_exe}")

    if check_script.is_file():
        check_exe = repo_root / "out" / "pyi-check" / "launcher-runtime-check" / "launcher-runtime-check.exe"
        run([str(check_exe), "--launcher", str(launcher_exe), str(check_script)])

    # Smoke-test that the frozen launcher bundle imports mods and native_mods
    smoke_script = repo_root / "out" / "check_native_mods_import.py"
    smoke_script.write_text(
        "import mods, native_mods\n"
        "assert hasattr(mods, 'native_manifest'), 'mods.native_manifest missing'\n"
        "assert hasattr(native_mods, 'prepare'), 'native_mods.prepare missing'\n"
        "print('PASS: frozen native_mods import')\n",
        encoding="utf-8",
    )
    # Output goes to a file, not a pipe: the windowed launcher (or a helper it starts) can keep an
    # inherited pipe open forever, and communicate() would wait for EOF until the job times out.
    smoke_log = repo_root / "out" / "check_native_mods_import.log"
    smoke_log.unlink(missing_ok=True)
    print("+", launcher_exe, "--script", smoke_script, flush=True)
    with open(smoke_log, "w", encoding="utf-8") as log_stream:
        proc = subprocess.Popen([str(launcher_exe), "--script", str(smoke_script)],
                                stdin=subprocess.DEVNULL, stdout=log_stream, stderr=subprocess.STDOUT)
        try:
            code = proc.wait(timeout=180)
        except subprocess.TimeoutExpired:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
            code = None
    output = smoke_log.read_text(encoding="utf-8", errors="replace") if smoke_log.is_file() else ""
    if "PASS: frozen native_mods import" not in output:
        raise RuntimeError(f"Frozen native_mods smoke test failed (exit {code}): {output}")
    if code is None:
        print("WARNING: launcher printed PASS but did not exit within 180 s; it was stopped", flush=True)
    print(output.strip(), flush=True)
    return frozen_dir


def collect_clang64_dlls(exes: list[Path], clang64_bin: Path) -> list[Path]:
    by_lower = {p.name.lower(): p for p in clang64_bin.glob("*.dll")}
    found: dict[str, Path] = {}
    queue: list[Path] = list(exes)
    seen: set[Path] = set()

    objdump = clang64_bin / "llvm-objdump.exe"
    ldd_exe = clang64_bin.parent.parent / "usr" / "bin" / "ldd.exe"

    # 1. Recursive PE import walk using llvm-objdump -p
    while queue:
        current = queue.pop(0)
        if current in seen:
            continue
        seen.add(current)
        res = subprocess.run(
            [str(objdump), "-p", str(current)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        for line in res.stdout.splitlines():
            m = re.search(r"DLL Name:\s*(\S+)", line)
            if not m:
                continue
            dll_name = m.group(1).strip()
            low = dll_name.lower()
            if low == "vulkan-1.dll":
                continue
            if low in by_lower:
                dll_path = by_lower[low]
                if low not in found:
                    found[low] = dll_path
                    queue.append(dll_path)

    # 2. Also union with MSYS2 ldd output
    if ldd_exe.is_file():
        res = subprocess.run(
            [str(ldd_exe), *(str(e) for e in exes)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        for line in res.stdout.splitlines():
            if "/clang64/bin/" in line.lower() and "vulkan-1.dll" not in line.lower():
                parts = line.split()
                for part in parts:
                    name = Path(part).name.lower()
                    if name in by_lower and name != "vulkan-1.dll":
                        found[name] = by_lower[name]

    return sorted(found.values(), key=lambda p: p.name.lower())


def collect_msys2_licenses(dlls: list[Path], msys2_root: Path, stage_licenses: Path) -> None:
    stage_licenses.mkdir(parents=True, exist_ok=True)
    pacman = msys2_root / "usr" / "bin" / "pacman.exe"
    if not pacman.is_file():
        return

    rel_paths = [f"/clang64/bin/{d.name}" for d in dlls]
    qo = subprocess.run(
        [str(pacman), "-Qo", *rel_paths],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    pkgs: set[str] = set()
    for line in qo.stdout.splitlines():
        m = re.search(r"is owned by (\S+)\s+(\S+)", line)
        if m:
            pkgs.add(m.group(1))

    rows: list[tuple[str, str, str, str]] = []
    for pkg in sorted(pkgs):
        qi = subprocess.run(
            [str(pacman), "-Qi", pkg],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        ver = ""
        lic = ""
        url = ""
        for line in qi.stdout.splitlines():
            if ":" not in line:
                continue
            k, v = [x.strip() for x in line.split(":", 1)]
            if k == "Version":
                ver = v
            elif k == "Licenses":
                lic = v
            elif k == "URL":
                url = v
        rows.append((pkg, ver, lic, url))

        short = pkg.replace("mingw-w64-clang-x86_64-", "")
        lic_src = msys2_root / "clang64" / "share" / "licenses" / short
        if lic_src.is_dir():
            shutil.copytree(lic_src, stage_licenses / short, dirs_exist_ok=True)

    md_lines = [
        "# MSYS2 CLANG64 runtime packages",
        "",
        "Package recipes and source references: https://github.com/msys2/MINGW-packages",
        "",
        "| Package | Version | License | Upstream |",
        "| --- | --- | --- | --- |",
    ]
    for pkg, ver, lic, url in rows:
        md_lines.append(f"| [{pkg}](https://packages.msys2.org/package/{pkg}) | {ver} | {lic} | {url} |")
    (stage_licenses / "MSYS2-PACKAGES.md").write_text("\n".join(md_lines) + "\n", encoding="utf-8")


def zip_directory(source_dir: Path, zip_path: Path) -> None:
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for file_path in sorted(source_dir.rglob("*")):
            if file_path.is_file():
                arcname = file_path.relative_to(source_dir).as_posix()
                zf.write(file_path, arcname)


def build_updater_exe(ci_dir: Path, repo_root: Path, venv_py: Path) -> Path | None:
    """Freeze the Tkinter updater into a single HuntersAtlasUpdater.exe."""
    updater_dir = ci_dir / "updater"
    if not (updater_dir / "main.py").is_file():
        print("Updater sources not found; skipping exe build", flush=True)
        return None
    out_dir = repo_root / "out" / "updater-dist"
    work_dir = repo_root / "out" / "updater-work"
    cmd = [
        str(venv_py), "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile",
        "--windowed", "--log-level", "WARN", "--name", "HuntersAtlasUpdater",
        "--distpath", str(out_dir), "--workpath", str(work_dir),
        "--specpath", str(work_dir), "--paths", str(updater_dir),
        "--hidden-import", "core", "--hidden-import", "gui",
    ]
    icon = repo_root / "launcher" / "bloodborne.ico"
    if icon.is_file():
        cmd += ["--icon", str(icon)]
    version_file = updater_dir / "version_info.txt"
    if version_file.is_file():
        cmd += ["--version-file", str(version_file)]
    cmd.append(str(updater_dir / "main.py"))
    run(cmd)
    exe = out_dir / "HuntersAtlasUpdater.exe"
    if not exe.is_file():
        raise RuntimeError(f"PyInstaller did not produce {exe}")
    return exe


def main() -> int:
    repo_root = Path.cwd().resolve()
    ci_dir = Path(os.environ["ATLAS_CI_DIR"]).resolve()
    target = json.loads((ci_dir / "target.json").read_text(encoding="utf-8"))

    msys2_root = Path(
        os.environ.get("MSYS2_WIN_ROOT")
        or os.environ.get("MSYS2_ROOT")
        or r"C:\msys64"
    ).resolve()
    clang64_bin = msys2_root / "clang64" / "bin"
    strip_exe = clang64_bin / "llvm-strip.exe"

    host_version = target["host_version"]
    base_version = target["base_version"]
    upstream_tag = target["upstream_tag"]
    built_commit = target["built_commit"]
    atlas_tip = target["atlas_tip"]
    fork_repo = target["fork_repo"]

    win_python = find_windows_python314()
    print(f"Using Windows Python 3.14 at {win_python}")
    frozen_dir = freeze_launcher(repo_root, win_python)
    venv_py = repo_root / "out" / "pyenv" / "Scripts" / "python.exe"
    updater_exe = build_updater_exe(ci_dir, repo_root, venv_py)

    stage = repo_root / "out" / "atlas-host-stage"
    if stage.exists():
        shutil.rmtree(stage)
    (stage / "bin").mkdir(parents=True, exist_ok=True)
    (stage / "scripts").mkdir(parents=True, exist_ok=True)
    (stage / "licenses").mkdir(parents=True, exist_ok=True)

    # 1. Copy frozen launcher Bloodborne.exe + _internal/
    shutil.copy2(frozen_dir / "Bloodborne.exe", stage / "Bloodborne.exe")
    shutil.copytree(frozen_dir / "_internal", stage / "_internal")

    # 2. Strip and copy compiled executables into stage/bin/
    exes_to_ship = ["bb-probe.exe", "bb-gpu-capabilities.exe", "bb-fg401-capabilities.exe"]
    staged_exes: list[Path] = []
    for exe_name in exes_to_ship:
        src_exe = repo_root / "out" / exe_name
        if not src_exe.is_file():
            raise RuntimeError(f"Expected build output {src_exe} is missing")
        dst_exe = stage / "bin" / exe_name
        run([str(strip_exe), "--strip-debug", "-o", str(dst_exe), str(src_exe)])
        staged_exes.append(dst_exe)

    # 3. Collect and copy all required MSYS2 CLANG64 runtime DLLs
    dlls = collect_clang64_dlls(staged_exes, clang64_bin)
    print(f"Bundling {len(dlls)} MSYS2 CLANG64 runtime DLLs into bin/")
    for dll in dlls:
        shutil.copy2(dll, stage / "bin" / dll.name)

    # 4. Copy LocalChalice catalog if present in this bbport version
    chalice_cat = repo_root / "data" / "local_chalice" / "catalog.bin"
    if chalice_cat.is_file():
        (stage / "bin" / "LocalChalice").mkdir(parents=True, exist_ok=True)
        shutil.copy2(chalice_cat, stage / "bin" / "LocalChalice" / "catalog.bin")

    # 5. Copy run.py and scripts/*.py
    shutil.copy2(repo_root / "run.py", stage / "run.py")
    for py_file in sorted((repo_root / "scripts").rglob("*.py")):
        if "__pycache__" in py_file.parts:
            continue
        rel = py_file.relative_to(repo_root / "scripts")
        dst = stage / "scripts" / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(py_file, dst)

    # 6. Copy LICENSE and dependency licenses
    shutil.copy2(repo_root / "LICENSE", stage / "LICENSE")
    collect_msys2_licenses(dlls, msys2_root, stage / "licenses")

    # 7. Copy apply-host.ps1, update-atlas.ps1, Update-Hunters-Atlas.bat, README-UPDATER.md
    for helper_name in ["apply-host.ps1", "update-atlas.ps1", "Update-Hunters-Atlas.bat", "README-UPDATER.md"]:
        helper_src = ci_dir / helper_name
        if helper_src.is_file():
            shutil.copy2(helper_src, stage / helper_name)

    probe_sha = sha256_file(stage / "bin" / "bb-probe.exe")
    launcher_sha = sha256_file(stage / "Bloodborne.exe")
    (stage / "SHA256-BB-PROBE.txt").write_text(f"{probe_sha}  bin/bb-probe.exe\n", encoding="utf-8")

    readme_host = (
        f"# Hunter's Atlas host {host_version}\n\n"
        f"Prebuilt native-mod host for **bbport Windows {base_version}** (`{upstream_tag}`), "
        f"implementing `bbport_native_mod_api_v1` and Hunter's Atlas game services.\n\n"
        f"## Quick automatic update (recommended)\n\n"
        f"Double-click `Update-Hunters-Atlas.bat` (or run `update-atlas.ps1` in PowerShell). "
        f"It verifies the official bbport version and applies this host package automatically.\n\n"
        f"## Manual application onto bbport {base_version}\n\n"
        f"Close Bloodborne and the launcher, extract this archive anywhere, and run:\n\n"
        f"```powershell\n"
        f"powershell -ExecutionPolicy Bypass -File .\\apply-host.ps1 -Port \"C:\\Games\\Bloodborne-1.6\\bbport-windows\"\n"
        f"```\n\n"
        f"The installer backs up replaced files under `host-backup-atlas-<timestamp>`, overlays `bin/`, "
        f"`Bloodborne.exe`, `_internal/`, `run.py` and `scripts/`, and updates `bbport-files.json`.\n\n"
        f"- **Upstream tag**: https://github.com/Supermedo/bloodborne_pc/releases/tag/{upstream_tag}\n"
        f"- **Host source tag**: https://github.com/{fork_repo}/tree/{target['release_tag']}\n"
        f"- **Atlas patch branch**: https://github.com/{fork_repo}/tree/{atlas_tip}\n"
        f"- **bb-probe.exe SHA-256**: `{probe_sha}`\n"
    )
    (stage / "README-HOST.md").write_text(readme_host, encoding="utf-8")

    # Compute file hashes for atlas-host.json
    tracked_files: dict[str, str] = {}
    for p in sorted(stage.rglob("*")):
        if p.is_file() and not p.relative_to(stage).parts[0].startswith(("licenses", "_internal")):
            rel = p.relative_to(stage).as_posix()
            tracked_files[rel] = sha256_file(p)

    host_meta = {
        "schema": 1,
        "host_version": host_version,
        "base_version": base_version,
        "upstream_tag": upstream_tag,
        "upstream_commit": target["upstream_commit"],
        "upstream_zip_url": target.get("upstream_zip_url", ""),
        "upstream_zip_sha256": target.get("upstream_zip_sha256", ""),
        "atlas_revision": target["atlas_revision"],
        "atlas_branch": target["atlas_branch"],
        "atlas_tip": atlas_tip,
        "built_commit": built_commit,
        "native_api": 1,
        "zip_name": target["zip_name"],
        "bb_probe_sha256": probe_sha,
        "launcher_sha256": launcher_sha,
        "files": tracked_files,
    }
    (stage / "atlas-host.json").write_text(json.dumps(host_meta, indent=2) + "\n", encoding="utf-8")

    assets_dir = repo_root / "out" / "atlas-release-assets"
    if assets_dir.exists():
        shutil.rmtree(assets_dir)
    assets_dir.mkdir(parents=True, exist_ok=True)

    # Build main host ZIP
    host_zip_path = assets_dir / target["zip_name"]
    print(f"Creating {host_zip_path.name} ...")
    zip_directory(stage, host_zip_path)
    host_zip_sha = sha256_file(host_zip_path)

    # Build lightweight standalone Updater ZIP
    updater_stage = repo_root / "out" / "atlas-updater-stage"
    if updater_stage.exists():
        shutil.rmtree(updater_stage)
    updater_stage.mkdir(parents=True, exist_ok=True)
    for fname in ["Update-Hunters-Atlas.bat", "update-atlas.ps1", "apply-host.ps1", "README-UPDATER.md"]:
        src = ci_dir / fname
        if src.is_file():
            shutil.copy2(src, updater_stage / fname)
    updater_exe_sha = ""
    if updater_exe and updater_exe.is_file():
        shutil.copy2(updater_exe, updater_stage / updater_exe.name)
        updater_exe_sha = sha256_file(updater_stage / updater_exe.name)
    updater_zip_path = assets_dir / "Hunters-Atlas-Updater.zip"
    zip_directory(updater_stage, updater_zip_path)
    updater_zip_sha = sha256_file(updater_zip_path)

    host_meta["zip_sha256"] = host_zip_sha
    host_meta["updater_zip_sha256"] = updater_zip_sha
    host_meta["updater_exe_sha256"] = updater_exe_sha
    (assets_dir / "atlas-host.json").write_text(json.dumps(host_meta, indent=2) + "\n", encoding="utf-8")

    sums_lines = [
        f"{host_zip_sha}  {host_zip_path.name}",
        f"{updater_zip_sha}  {updater_zip_path.name}",
        f"{probe_sha}  bin/bb-probe.exe",
        f"{launcher_sha}  Bloodborne.exe",
    ]
    if updater_exe_sha:
        sums_lines.insert(2, f"{updater_exe_sha}  HuntersAtlasUpdater.exe")
    (assets_dir / "SHA256SUMS.txt").write_text("\n".join(sums_lines) + "\n", encoding="utf-8")

    notes = (
        f"<!-- atlas-tip: {atlas_tip} -->\n"
        f"<!-- base-version: {base_version} -->\n"
        f"## Hunter's Atlas Host `{host_version}` (for bbport Windows `{base_version}`)\n\n"
        f"Automated MSYS2 CLANG64 host build of [`{upstream_tag}`](https://github.com/Supermedo/bloodborne_pc/releases/tag/{upstream_tag}) "
        f"with the Hunter's Atlas native mod API (`bbport_native_mod_api_v1`) from `{target['atlas_branch']}` (`{atlas_tip[:10]}`).\n\n"
        f"### Checksums (SHA-256)\n"
        f"- `{host_zip_path.name}`: `{host_zip_sha}`\n"
        f"- `Hunters-Atlas-Updater.zip`: `{updater_zip_sha}`\n"
        f"- `HuntersAtlasUpdater.exe`: `{updater_exe_sha or 'see updater zip'}`\n"
        f"- `bin/bb-probe.exe`: `{probe_sha}`\n"
        f"- `Bloodborne.exe`: `{launcher_sha}`\n"
        f"- Official `Bloodborne-Windows.zip` (`{upstream_tag}`): `{target.get('upstream_zip_sha256') or 'see official release'}`\n\n"
        f"### How to update\n"
        f"Download **`Hunters-Atlas-Updater.zip`**, extract it anywhere and run "
        f"**`HuntersAtlasUpdater.exe`** (no PowerShell, no policy prompts). "
        f"It also works from `Update-Hunters-Atlas.bat` inside your bbport folder.\n"
    )
    (assets_dir / "RELEASE-NOTES.md").write_text(notes, encoding="utf-8")
    print(f"Packaged {host_zip_path.name} ({host_zip_path.stat().st_size / (1024*1024):.2f} MiB), sha256={host_zip_sha}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
