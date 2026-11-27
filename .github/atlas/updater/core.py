# SPDX-License-Identifier: GPL-2.0-or-later
"""Hunter's Atlas updater core: version resolution, verified downloads, host
overlay, official bbport update, backup and restore. No GUI here."""
from __future__ import annotations

import ctypes
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

FORK_REPO = "dizzi1222/bloodborne_pc"
UPSTREAM_REPO = "Supermedo/bloodborne_pc"
UA = "HuntersAtlas-Updater/2.0"
PRESERVE = {"user", "out", "mods", "bbport.ini", "input.ini", "mods.json", "patches.json",
            "fsr4vk", "seamless", "bbsc", "last_run.log"}
MOD_FOLDER = "Hunter's Atlas"
HOST_RE = re.compile(r"^(?:bbport-atlas-host|Hunters-Atlas-[0-9.]+-bbport-host)-"
                     r"(\d+(?:\.\d+)*)-atlas\.(\d+)\.zip$")
MOD_RE = re.compile(r"^Hunters-Atlas-(\d+(?:\.\d+)*)-bbport-mod\.zip$")


class UpdaterError(RuntimeError):
    pass


class RootNotFound(UpdaterError):
    pass


def ensure_free_space(path: Path, needed: int, what: str) -> None:
    free = shutil.disk_usage(path).free
    if free < needed:
        raise UpdaterError(
            f"No hay espacio suficiente para {what}: hacen falta {needed / 2**30:.1f} GB libres "
            f"en {path.anchor or path} y hay {free / 2**30:.1f} GB. Libera espacio y vuelve a intentarlo. "
            "No se modificó nada.")


def vtuple(text: str) -> tuple[int, ...]:
    return tuple(int(n) for n in re.findall(r"\d+", text or ""))


def vcmp(left: tuple[int, ...], right: tuple[int, ...]) -> int:
    size = max(len(left), len(right))
    for i in range(size):
        a = left[i] if i < len(left) else 0
        b = right[i] if i < len(right) else 0
        if a != b:
            return -1 if a < b else 1
    return 0


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def http_json(url: str):
    req = urllib.request.Request(
        url, headers={"Accept": "application/vnd.github+json", "User-Agent": UA})
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def download(url: str, dest: Path, expected: str = "", progress=None) -> str:
    dest.parent.mkdir(parents=True, exist_ok=True)
    last_error: Exception | None = None
    for attempt in range(1, 4):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            h = hashlib.sha256()
            with urllib.request.urlopen(req, timeout=60) as resp, open(dest, "wb") as out:
                total = int(resp.headers.get("Content-Length") or 0)
                done = 0
                while chunk := resp.read(1 << 20):
                    out.write(chunk)
                    h.update(chunk)
                    done += len(chunk)
                    if progress and total:
                        progress(min(done / total, 1.0), done, total)
            digest = h.hexdigest()
            if expected and digest != expected.lower().removeprefix("sha256:"):
                dest.unlink(missing_ok=True)
                raise UpdaterError(
                    f"SHA-256 no coincide para {dest.name}.\n"
                    f"Esperado: {expected}\nRecibido: {digest}")
            return digest
        except UpdaterError:
            raise
        except Exception as exc:  # network hiccup: retry
            last_error = exc
            if dest.exists():
                dest.unlink(missing_ok=True)
            if attempt == 3:
                break
    raise UpdaterError(f"No se pudo descargar {url}: {last_error}")


def _hidden_run(cmd: list[str]) -> subprocess.CompletedProcess:
    flags = 0x08000000 if os.name == "nt" else 0  # CREATE_NO_WINDOW
    return subprocess.run(cmd, capture_output=True, text=True, flags=flags)


def resolve_root(explicit: str | Path | None = None) -> Path:
    if explicit:
        root = Path(explicit).expanduser().resolve()
        if not (root / "bbport-files.json").is_file():
            raise RootNotFound(f"No es una instalación de bbport: {root}")
        return root
    bases = []
    if getattr(sys, "frozen", False):
        bases.append(Path(sys.executable).resolve().parent)
    bases.append(Path(__file__).resolve().parent)
    for base in bases:
        cursor = base
        for _ in range(6):
            if (cursor / "bbport-files.json").is_file() and (cursor / "Bloodborne.exe").is_file():
                return cursor
            if cursor.parent == cursor:
                break
            cursor = cursor.parent
    for candidate in (Path(r"C:\Games\Bloodborne-1.6\bbport-windows"),
                      Path.home() / "Bloodborne-1.6" / "bbport-windows"):
        if (candidate / "bbport-files.json").is_file():
            return candidate
    # Desktop shortcut fallback (no COM: resolve through PowerShell, hidden).
    try:
        desktop = Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Desktop" / "Bloodborne.lnk"
        if desktop.is_file():
            res = _hidden_run(["powershell", "-NoProfile", "-NonInteractive", "-Command",
                               f"(New-Object -ComObject WScript.Shell).CreateShortcut('{desktop}').TargetPath"])
            target = res.stdout.strip()
            if target and (Path(target).parent / "bbport-files.json").is_file():
                return Path(target).parent
    except Exception:
        pass
    raise RootNotFound("No se encontró la carpeta de bbport. Selecciónala manualmente.")


def running_processes(root: Path) -> list[str]:
    if os.name != "nt":
        return []
    try:
        from ctypes import wintypes
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        count = 4096
        while True:
            arr = (wintypes.DWORD * count)()
            needed = wintypes.DWORD()
            if not psapi.EnumProcesses(arr, ctypes.sizeof(arr), ctypes.byref(needed)):
                return []
            n = needed.value // ctypes.sizeof(wintypes.DWORD)
            if n < count:
                break
            count *= 2
        prefix = str(root).rstrip("\\/").lower() + "\\"
        names: set[str] = set()
        for pid in arr[:n]:
            if not pid:
                continue
            handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if not handle:
                continue
            try:
                size = wintypes.DWORD(32768)
                buf = ctypes.create_unicode_buffer(size.value)
                if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
                    path = buf.value.lower()
                    if path.startswith(prefix):
                        names.add(Path(buf.value).stem)
            finally:
                kernel32.CloseHandle(handle)
        return sorted(names)
    except Exception:
        return []


def update_mutex_held() -> bool:
    if os.name != "nt":
        return False
    try:
        SYNCHRONIZE = 0x00100000
        handle = ctypes.windll.kernel32.OpenMutexW(SYNCHRONIZE, False, "Local\\bbport-update")
        if handle:
            ctypes.windll.kernel32.CloseHandle(handle)
            return True
    except Exception:
        pass
    return False


@dataclass
class UpstreamRelease:
    tag: str
    version: str
    vtuple: tuple[int, ...]
    zip_url: str
    zip_sha: str
    zip_size: int
    html_url: str


@dataclass
class HostRelease:
    release_tag: str
    host_version: str
    base_version: str
    base_tuple: tuple[int, ...]
    revision: int
    zip_name: str
    zip_url: str
    zip_sha: str
    zip_size: int
    meta_url: str
    html_url: str
    prerelease: bool = False


@dataclass
class ModRelease:
    release_tag: str
    mod_version: str
    vtuple: tuple[int, ...]
    zip_name: str
    zip_url: str
    zip_sha: str
    zip_size: int


@dataclass
class LocalState:
    root: Path
    version: str
    base_version: str
    atlas_rev: int
    host_intact: bool
    probe_hash: str
    mod_installed: bool
    mod_dir: Path
    mod_dll_hash: str


@dataclass
class Plan:
    local: LocalState
    latest_upstream: UpstreamRelease | None
    best_host: HostRelease | None
    matching_upstream: UpstreamRelease | None
    latest_mod: ModRelease | None
    needs_official: bool = False
    needs_host: bool = False
    needs_mod: bool = False
    up_to_date: bool = False
    warning: str = ""
    notes: list[str] = field(default_factory=list)

    @property
    def target_version(self) -> str:
        return self.best_host.host_version if self.best_host else self.local.version

    @property
    def has_work(self) -> bool:
        return self.needs_official or self.needs_host or self.needs_mod


class Updater:
    def __init__(self, root: Path, log=None, progress=None,
                 fork_repo: str = FORK_REPO, upstream_repo: str = UPSTREAM_REPO,
                 include_prerelease: bool = True):
        self.root = Path(root)
        self._log = log or (lambda message, level="info": None)
        self._progress = progress or (lambda fraction, text: None)
        self.fork_repo = fork_repo
        self.upstream_repo = upstream_repo
        self.include_prerelease = include_prerelease

    def log(self, message: str, level: str = "info") -> None:
        self._log(message, level)

    def progress(self, fraction: float, text: str = "") -> None:
        self._progress(fraction, text)

    # ------------------------------------------------------------------ state
    def local_state(self) -> LocalState:
        manifest_path = self.root / "bbport-files.json"
        if not manifest_path.is_file():
            raise UpdaterError(f"No se encontró bbport-files.json en {self.root}")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
        version = str(manifest.get("version", ""))
        match = re.match(r"^(\d+(?:\.\d+)*)-atlas\.(\d+)$", version)
        base_version = match.group(1) if match else version
        atlas_rev = int(match.group(2)) if match else 0
        probe = self.root / "bin" / "bb-probe.exe"
        probe_hash = sha256_file(probe) if probe.is_file() else ""
        expected = str((manifest.get("files") or {}).get("bin/bb-probe.exe", ""))
        host_intact = bool(atlas_rev > 0 and (self.root / "scripts" / "native_mods.py").is_file()
                           and probe_hash and probe_hash == expected)
        mod_dir = self.root / "mods" / MOD_FOLDER
        mod_installed = ((mod_dir / "bbport-native-mod.json").is_file()
                         and (mod_dir / "native" / "hunters_atlas.dll").is_file())
        mod_dll = mod_dir / "native" / "hunters_atlas.dll"
        return LocalState(
            root=self.root, version=version, base_version=base_version,
            atlas_rev=atlas_rev, host_intact=host_intact, probe_hash=probe_hash,
            mod_installed=mod_installed, mod_dir=mod_dir,
            mod_dll_hash=sha256_file(mod_dll) if mod_installed else "")

    # --------------------------------------------------------------- releases
    def upstream_releases(self) -> list[UpstreamRelease]:
        raw = http_json(f"https://api.github.com/repos/{self.upstream_repo}/releases?per_page=30")
        releases: list[UpstreamRelease] = []
        for rel in raw:
            if rel.get("draft") or rel.get("prerelease"):
                continue
            match = re.match(r"^windows-v(\d+(?:\.\d+)*)$", rel.get("tag_name", ""))
            if not match:
                continue
            assets = rel.get("assets") or []
            asset = next((a for a in assets if a.get("name", "").lower()
                          == "bloodborne-windows.zip"), None)
            if not asset:
                asset = next((a for a in assets if a.get("name", "").lower().endswith(".zip")
                              and not re.search(r"(^|[-_.])(src|source|sources)([-_.]|$)",
                                                a.get("name", "").lower())), None)
            if not asset:
                continue
            digest = str(asset.get("digest") or "")
            sha = digest.removeprefix("sha256:") if digest.startswith("sha256:") else ""
            releases.append(UpstreamRelease(
                tag=rel["tag_name"], version=match.group(1), vtuple=vtuple(match.group(1)),
                zip_url=asset.get("browser_download_url", ""), zip_sha=sha.lower(),
                zip_size=int(asset.get("size") or 0), html_url=rel.get("html_url", "")))
        releases.sort(key=lambda r: r.vtuple, reverse=True)
        return releases

    def fork_artifacts(self) -> tuple[list[HostRelease], list[ModRelease]]:
        raw = http_json(f"https://api.github.com/repos/{self.fork_repo}/releases?per_page=50")
        hosts: list[HostRelease] = []
        mods: list[ModRelease] = []
        for rel in raw:
            if rel.get("draft"):
                continue
            if rel.get("prerelease") and not self.include_prerelease:
                continue
            assets = rel.get("assets") or []
            meta = next((a for a in assets if a.get("name", "").lower() == "atlas-host.json"), None)
            for asset in assets:
                name = asset.get("name", "")
                digest = str(asset.get("digest") or "")
                sha = digest.removeprefix("sha256:") if digest.startswith("sha256:") else ""
                host_match = HOST_RE.match(name)
                if host_match:
                    hosts.append(HostRelease(
                        release_tag=rel["tag_name"], host_version=f"{host_match.group(1)}-atlas.{host_match.group(2)}",
                        base_version=host_match.group(1), base_tuple=vtuple(host_match.group(1)),
                        revision=int(host_match.group(2)), zip_name=name,
                        zip_url=asset.get("browser_download_url", ""), zip_sha=sha.lower(),
                        zip_size=int(asset.get("size") or 0),
                        meta_url=meta.get("browser_download_url", "") if meta else "",
                        html_url=rel.get("html_url", ""), prerelease=bool(rel.get("prerelease"))))
                    continue
                mod_match = MOD_RE.match(name)
                if mod_match:
                    mods.append(ModRelease(
                        release_tag=rel["tag_name"], mod_version=mod_match.group(1),
                        vtuple=vtuple(mod_match.group(1)), zip_name=name,
                        zip_url=asset.get("browser_download_url", ""), zip_sha=sha.lower(),
                        zip_size=int(asset.get("size") or 0)))
        hosts.sort(key=lambda h: (h.base_tuple, h.revision), reverse=True)
        mods.sort(key=lambda m: m.vtuple, reverse=True)
        return hosts, mods

    # ------------------------------------------------------------------- plan
    def plan(self, force: bool = False, skip_mod: bool = False) -> Plan:
        local = self.local_state()
        upstream = self.upstream_releases()
        if not upstream:
            raise UpdaterError(f"No se encontraron releases oficiales de Windows en {self.upstream_repo}.")
        latest = upstream[0]
        hosts, mods = self.fork_artifacts()
        if not hosts:
            raise UpdaterError(f"No se encontraron paquetes host de Hunter's Atlas en {self.fork_repo}.")
        by_version = {u.version: u for u in upstream}
        best_host = next((h for h in hosts if h.base_version in by_version), hosts[0])
        matching = by_version.get(best_host.base_version)
        latest_mod = mods[0] if mods else None

        plan = Plan(local=local, latest_upstream=latest, best_host=best_host,
                    matching_upstream=matching, latest_mod=latest_mod)
        if vcmp(latest.vtuple, best_host.base_tuple) > 0:
            plan.warning = (
                f"bbport {latest.version} ya salió, pero el host de Hunter's Atlas para "
                f"{latest.version} aún no está disponible. La última versión compatible con el mapa "
                f"es {best_host.host_version}.")
        local_cmp = vcmp(vtuple(local.base_version), best_host.base_tuple)
        if local_cmp > 0:
            plan.up_to_date = True
            plan.warning = (
                f"Tu bbport local ({local.base_version}) es más nuevo que el último host Atlas "
                f"disponible ({best_host.host_version}). No se aplicará un host más antiguo.")
            return plan
        plan.needs_official = local_cmp < 0
        plan.needs_host = bool(force or plan.needs_official or not local.host_intact
                               or (local_cmp == 0 and local.atlas_rev < best_host.revision))
        plan.needs_mod = bool(not skip_mod and not local.mod_installed and latest_mod)
        plan.up_to_date = not plan.has_work
        return plan

    # -------------------------------------------------------------------- run
    def wait_idle(self, timeout: int = 120) -> None:
        import time
        deadline = time.monotonic() + timeout
        told_mutex = told_proc = False
        while update_mutex_held():
            if time.monotonic() >= deadline:
                raise UpdaterError(
                    f"El actualizador oficial de bbport sigue en curso después de {timeout} s.")
            if not told_mutex:
                self.log("Esperando a que termine el actualizador oficial de bbport…", "warn")
                told_mutex = True
            time.sleep(0.5)
        while True:
            names = running_processes(self.root)
            if not names:
                return
            if time.monotonic() >= deadline:
                raise UpdaterError(
                    "Cierra Bloodborne y el launcher antes de actualizar "
                    f"(en ejecución: {', '.join(names)}).")
            if not told_proc:
                self.log(f"Esperando a que se cierren: {', '.join(names)} …", "warn")
                told_proc = True
            time.sleep(1.0)

    def _meta_sha(self, host: HostRelease) -> str:
        if host.zip_sha or not host.meta_url:
            return host.zip_sha
        try:
            meta = http_json(host.meta_url)
            return str(meta.get("zip_sha256") or "").lower()
        except Exception as exc:
            self.log(f"No se pudo leer atlas-host.json: {exc}", "warn")
            return ""

    def _fetch(self, url: str, name: str, sha: str, label: str, work: Path) -> Path:
        dest = work / name
        size_mb = 0
        if not sha:
            raise UpdaterError(f"{label}: el release no publica SHA-256; se cancela por seguridad.")
        self.log(f"Descargando {label}…")
        download(url, dest, sha, lambda frac, done, total: self.progress(
            frac, f"{label}: {done // (1 << 20)} / {total // (1 << 20)} MB"))
        size_mb = dest.stat().st_size // (1 << 20)
        self.log(f"SHA-256 verificado ({size_mb} MB).", "ok")
        return dest

    def run(self, plan: Plan, force: bool = False) -> str:
        if not plan.has_work:
            self.log(f"Todo está al día ({plan.local.version}).", "ok")
            return plan.local.version
        self.wait_idle()
        # Downloads + the official package written in place + _internal staging + host backup.
        ensure_free_space(self.root, (2_500 if plan.needs_official else 800) * 2**20,
                          "esta actualización")
        work = Path(tempfile.mkdtemp(prefix="atlas-updater-"))
        try:
            host_zip: Path | None = None
            official_zip: Path | None = None
            if plan.needs_host and plan.best_host:
                host = plan.best_host
                host_zip = self._fetch(host.zip_url, host.zip_name, self._meta_sha(host),
                                       f"host Atlas {host.host_version}", work)
            if plan.needs_official:
                official = plan.matching_upstream
                if not official:
                    raise UpdaterError(
                        f"No se encontró el paquete oficial Bloodborne-Windows.zip para "
                        f"{plan.best_host.base_version if plan.best_host else '?'}.")
                official_zip = self._fetch(official.zip_url, f"Bloodborne-Windows-{official.version}.zip",
                                           official.zip_sha, f"bbport oficial {official.version}", work)
            if official_zip:
                self.log(f"Actualizando bbport base a {plan.matching_upstream.version} "
                         f"(conservando partidas, ajustes y mods)…")
                self.apply_official(official_zip)
                self.log("bbport base actualizado.", "ok")
            if host_zip and plan.best_host:
                self.log(f"Aplicando host Atlas {plan.best_host.host_version}…")
                self.apply_host(host_zip, plan.best_host.host_version, force=force)
                self.log("Host Atlas aplicado.", "ok")
            if plan.needs_mod and plan.latest_mod:
                self.install_mod(plan.latest_mod, work)
            target = plan.target_version
            self.log(f"Actualización completada. Versión activa: {target}", "ok")
            self.progress(1.0, "Listo")
            return target
        finally:
            shutil.rmtree(work, ignore_errors=True)

    # --------------------------------------------------------------- installs
    def apply_official(self, zip_path: Path) -> None:
        """Puts the official package over the installation without deleting anything first.

        Files are streamed from the ZIP straight into place (no temporary extraction), so a full
        disk stops the copy with the old files still there. _internal is staged beside the
        installation and swapped by renaming; Bloodborne.exe and bbport-files.json go in last,
        and every hash of the official manifest is checked at the end."""
        with zipfile.ZipFile(zip_path) as archive:
            members = [i for i in archive.infolist() if not i.is_dir()]
            prefix = ""
            if not any(i.filename == "Bloodborne.exe" for i in members):
                if any(i.filename == "bbport-windows/Bloodborne.exe" for i in members):
                    prefix = "bbport-windows/"
            names = {i.filename for i in members}
            for required in ("Bloodborne.exe", "_internal/base_library.zip", "bbport-files.json"):
                if prefix + required not in names:
                    raise UpdaterError("El archivo oficial descargado no contiene una instalación completa de bbport.")
            needed = sum(i.file_size for i in members) + 300 * 1024 * 1024
            ensure_free_space(self.root, needed, "actualizar bbport")

            stage = self.root / ".atlas-update"
            shutil.rmtree(stage, ignore_errors=True)
            new_internal = stage / "_internal"
            last: list[tuple[zipfile.ZipInfo, str]] = []
            total = len(members)
            for index, info in enumerate(members, 1):
                if not info.filename.startswith(prefix):
                    continue
                rel = info.filename[len(prefix):]
                top = rel.split("/")[0]
                if top.lower() in PRESERVE:
                    continue
                if rel in ("Bloodborne.exe", "bbport-files.json"):
                    last.append((info, rel))
                    continue
                if top == "_internal":
                    dest = new_internal / rel[len("_internal/"):]
                else:
                    dest = self.root / rel
                    if top in ("patches", "fsr4_shaders") and dest.exists():
                        continue  # the player's own patch/shader files stay as they are
                if index % 25 == 0:
                    self.progress(index / max(total, 1), f"Copiando {rel}")
                dest.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info) as src, open(dest, "wb") as out:
                    shutil.copyfileobj(src, out, 1 << 20)

            old_internal = stage / "_internal-old"
            if (self.root / "_internal").is_dir():
                (self.root / "_internal").rename(old_internal)
            try:
                new_internal.rename(self.root / "_internal")
            except OSError:
                if old_internal.is_dir():
                    old_internal.rename(self.root / "_internal")
                raise
            for info, rel in last:
                with archive.open(info) as src, open(self.root / rel, "wb") as out:
                    shutil.copyfileobj(src, out, 1 << 20)
        shutil.rmtree(stage, ignore_errors=True)

        manifest = json.loads((self.root / "bbport-files.json").read_text(encoding="utf-8-sig"))
        bad = [name for name, digest in (manifest.get("files") or {}).items()
               if not (self.root / name).is_file() or sha256_file(self.root / name) != digest]
        if bad:
            raise UpdaterError("bbport oficial quedó incompleto (" + ", ".join(bad[:5]) +
                               "). Libera espacio y vuelve a ejecutar el actualizador.")

    def apply_host(self, zip_path: Path, host_version: str, force: bool = False) -> None:
        work = Path(tempfile.mkdtemp(prefix="atlas-host-"))
        try:
            self.extract(zip_path, work, f"Extrayendo host {host_version}")
            pkg = work
            manifest_path = self.root / "bbport-files.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
            current = str(manifest.get("version", ""))
            current_base = re.sub(r"-atlas\.\d+$", "", current)
            expected_base = re.sub(r"-atlas\.\d+$", "", host_version)
            if not force and current_base and expected_base and current_base != expected_base:
                raise UpdaterError(
                    f"El host {host_version} es para bbport {expected_base}, pero la instalación "
                    f"está en {current}. Actualiza bbport y el host juntos.")
            for rel in ("bin/bb-probe.exe", "run.py", "scripts/mods.py", "scripts/native_mods.py"):
                if not (pkg / rel).is_file():
                    raise UpdaterError(f"El paquete host está incompleto: falta {rel}.")
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            backup = self.root / f"host-backup-atlas-{stamp}"
            suffix = 1
            while backup.exists():
                suffix += 1
                backup = self.root / f"host-backup-atlas-{stamp}-{suffix}"
            backup.mkdir(parents=True)
            shutil.copy2(manifest_path, backup / "bbport-files.json")
            backed_up: list[str] = []
            added: list[str] = []

            def backup_file(rel: str) -> bool:
                src = self.root / rel
                if src.is_file():
                    dst = backup / rel
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dst)
                    if rel not in backed_up:
                        backed_up.append(rel)
                    return True
                return False

            replaced_internal = False
            if (pkg / "_internal").is_dir():
                if (self.root / "_internal").is_dir():
                    shutil.copytree(self.root / "_internal", backup / "_internal")
                    shutil.rmtree(self.root / "_internal")
                shutil.copytree(pkg / "_internal", self.root / "_internal")
                replaced_internal = True
            if (pkg / "Bloodborne.exe").is_file():
                existed = backup_file("Bloodborne.exe")
                shutil.copy2(pkg / "Bloodborne.exe", self.root / "Bloodborne.exe")
                if not existed:
                    added.append("Bloodborne.exe")

            pkg_bin, target_bin = pkg / "bin", self.root / "bin"
            if pkg_bin.is_dir() and target_bin.is_dir():
                keep = {p.name.lower() for p in pkg_bin.glob("libabsl_*.dll")}
                if keep:
                    files = manifest.get("files") or {}
                    for old in target_bin.glob("libabsl_*.dll"):
                        if old.name.lower() not in keep:
                            rel = f"bin/{old.name}"
                            backup_file(rel)
                            old.unlink()
                            files.pop(rel, None)

            for folder in ("bin", "scripts"):
                src_dir = pkg / folder
                if not src_dir.is_dir():
                    continue
                for src in src_dir.rglob("*"):
                    if not src.is_file():
                        continue
                    rel = f"{folder}/{src.relative_to(src_dir).as_posix()}"
                    existed = backup_file(rel)
                    dst = self.root / rel
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dst)
                    if not existed and rel not in added:
                        added.append(rel)
            existed = backup_file("run.py")
            shutil.copy2(pkg / "run.py", self.root / "run.py")
            if not existed:
                added.append("run.py")

            manifest["version"] = host_version
            files = manifest.setdefault("files", {})

            def set_hash(rel: str) -> None:
                full = self.root / rel
                if not full.is_file() or full.name.lower().startswith("nvngx"):
                    return
                files[rel] = sha256_file(full)

            set_hash("run.py")
            if target_bin.is_dir():
                for path in target_bin.rglob("*"):
                    if path.is_file():
                        set_hash(path.relative_to(self.root).as_posix())
            scripts = self.root / "scripts"
            if scripts.is_dir():
                for path in scripts.rglob("*.py"):
                    if "__pycache__" not in path.parts:
                        set_hash(path.relative_to(self.root).as_posix())
            if "Bloodborne.exe" in files:
                set_hash("Bloodborne.exe")
            manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

            restore = {
                "schema": 1,
                "applied_at": datetime.now().astimezone().isoformat(),
                "previous_version": current,
                "applied_version": host_version,
                "replaced_internal": replaced_internal,
                "backed_up_files": backed_up,
                "added_files": added,
                "removed_stale_files": [],
            }
            (backup / "restore-info.json").write_text(
                json.dumps(restore, indent=2) + "\n", encoding="utf-8")
            self.log(f"Backup guardado en {backup.name}", "muted")
        finally:
            shutil.rmtree(work, ignore_errors=True)

    def install_mod(self, mod: ModRelease, work: Path) -> None:
        zip_path = self._fetch(mod.zip_url, mod.zip_name, mod.zip_sha,
                               f"mod Hunter's Atlas {mod.mod_version}", work)
        extracted = work / "mod"
        self.extract(zip_path, extracted, "Extrayendo mod")
        src = extracted
        if not (src / "bbport-native-mod.json").is_file() and \
                (src / MOD_FOLDER / "bbport-native-mod.json").is_file():
            src = src / MOD_FOLDER
        target = self.root / "mods" / MOD_FOLDER
        settings = target / "config" / "settings.ini"
        saved = settings.read_text(encoding="utf-8") if settings.is_file() else None
        target.mkdir(parents=True, exist_ok=True)
        shutil.copytree(src, target, dirs_exist_ok=True)
        if saved is not None:
            settings.parent.mkdir(parents=True, exist_ok=True)
            settings.write_text(saved, encoding="utf-8")
        self.log(f"Mod Hunter's Atlas {mod.mod_version} instalado.", "ok")

    def restore(self) -> str:
        self.wait_idle()
        backups = sorted((p for p in self.root.glob("host-backup-atlas-*") if p.is_dir()),
                         key=lambda p: p.name, reverse=True)
        if not backups:
            raise UpdaterError(f"No se encontró ningún backup host-backup-atlas-* en {self.root}.")
        latest = backups[0]
        self.log(f"Restaurando backup {latest.name}…")
        info_path = latest / "restore-info.json"
        info = json.loads(info_path.read_text(encoding="utf-8-sig")) if info_path.is_file() else {}
        if info.get("replaced_internal") and (latest / "_internal").is_dir():
            target_internal = self.root / "_internal"
            if target_internal.exists():
                shutil.rmtree(target_internal)
            shutil.copytree(latest / "_internal", target_internal)
        for rel in info.get("added_files") or []:
            target = self.root / str(rel).replace("\\", "/")
            if target.is_file():
                target.unlink()
        for src in latest.rglob("*"):
            if not src.is_file() or src.name == "restore-info.json":
                continue
            rel = src.relative_to(latest).as_posix()
            if rel.startswith("_internal/"):
                continue
            dst = self.root / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
        manifest = json.loads((self.root / "bbport-files.json").read_text(encoding="utf-8-sig"))
        version = str(manifest.get("version", ""))
        self.log(f"Restauración completada. Versión actual: {version}", "ok")
        return version

    def extract(self, zip_path: Path, dest: Path, label: str) -> None:
        dest.mkdir(parents=True, exist_ok=True)
        self.log(f"{label}…")
        with zipfile.ZipFile(zip_path) as zf:
            members = zf.infolist()
            total = max(len(members), 1)
            for index, member in enumerate(members, 1):
                zf.extract(member, dest)
                self.progress(index / total, f"{label}: {member.filename}")

