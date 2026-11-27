# SPDX-License-Identifier: GPL-2.0-or-later
"""Entry point for HuntersAtlasUpdater.exe.

No arguments opens the graphical updater. ``--check`` prints the resolved plan
(and can write it as JSON) without touching the installation; ``--restore``
rolls back the latest host backup from the command line.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import core
import i18n
from i18n import tr


def emit(text: str = "") -> None:
    if sys.stdout:
        print(text, flush=True)


def plan_dict(plan: core.Plan) -> dict:
    local = plan.local
    return {
        "root": str(local.root),
        "version": local.version,
        "base_version": local.base_version,
        "atlas_rev": local.atlas_rev,
        "host_intact": local.host_intact,
        "mod_installed": local.mod_installed,
        "latest_upstream": plan.latest_upstream.version if plan.latest_upstream else "",
        "best_host": plan.best_host.host_version if plan.best_host else "",
        "matching_upstream": plan.matching_upstream.version if plan.matching_upstream else "",
        "needs_official": plan.needs_official,
        "needs_host": plan.needs_host,
        "needs_mod": plan.needs_mod,
        "up_to_date": plan.up_to_date,
        "warning": plan.warning,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="HuntersAtlasUpdater")
    parser.add_argument("--port", help="bbport-windows folder / carpeta bbport-windows")
    parser.add_argument("--lang", choices=i18n.LANGS, help="es | en (default: Windows language)")
    parser.add_argument("--check", action="store_true", help="only report, change nothing / solo consultar")
    parser.add_argument("--json", metavar="RUTA", help="write the --check result as JSON / guardar en JSON")
    parser.add_argument("--restore", action="store_true", help="restore the latest host backup / restaurar el último backup")
    parser.add_argument("--no-prerelease", action="store_true",
                        help="ignore pre-release hosts / ignorar pre-releases")
    parser.add_argument("--force", action="store_true", help="re-apply the host / forzar la reaplicación del host")
    parser.add_argument("--skip-mod", action="store_true", help="do not install the mod / no instalar el mod")
    args = parser.parse_args(argv)
    i18n.set_language(args.lang)

    headless = args.check or args.restore
    try:
        root = core.resolve_root(args.port)
    except core.RootNotFound as exc:
        if headless:
            emit(f"ERROR: {exc}")
            return 2
        import gui
        return gui.run(args.port)

    def log(message: str, level: str = "info") -> None:
        if headless:
            emit(message)

    def progress(fraction: float, text: str = "") -> None:
        if headless and text:
            emit(f"  {text}")

    updater = core.Updater(root, log, progress, include_prerelease=not args.no_prerelease)
    try:
        if args.restore:
            emit(updater.restore())
            return 0
        if args.check:
            plan = updater.plan(force=args.force, skip_mod=args.skip_mod)
            data = plan_dict(plan)
            if args.json:
                Path(args.json).write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
            emit(tr("Carpeta bbport:        ", "bbport folder:         ") + data['root'])
            emit(tr("Versión instalada:     ", "Installed version:     ") + str(data['version']))
            emit(tr("Host Atlas íntegro:    ", "Atlas host intact:     ") + str(data['host_intact']))
            emit(tr("Mod instalado:         ", "Mod installed:         ") + str(data['mod_installed']))
            emit(tr("Última oficial bbport: ", "Latest official bbport:") + " " * (0 if i18n.LANG == "es" else 1) + str(data['latest_upstream']))
            emit(tr("Host compatible:       ", "Compatible host:       ") + str(data['best_host']))
            emit(tr("Actualizar bbport:     ", "Update bbport:         ") + str(data['needs_official']))
            emit(tr("Aplicar host Atlas:    ", "Apply Atlas host:      ") + str(data['needs_host']))
            emit(tr("Instalar mod Atlas:    ", "Install Atlas mod:     ") + str(data['needs_mod']))
            if data["warning"]:
                emit(tr("AVISO: ", "WARNING: ") + data['warning'])
            return 0 if data["up_to_date"] else 10
        import gui
        return gui.run(args.port)
    except Exception as exc:
        emit(f"ERROR: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
