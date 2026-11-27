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
    parser.add_argument("--port", help="ruta a bbport-windows")
    parser.add_argument("--check", action="store_true", help="solo consultar, sin modificar nada")
    parser.add_argument("--json", metavar="RUTA", help="guardar el resultado de --check en JSON")
    parser.add_argument("--restore", action="store_true", help="restaurar el último backup de host")
    parser.add_argument("--no-prerelease", action="store_true",
                        help="ignorar hosts publicados como pre-release")
    parser.add_argument("--force", action="store_true", help="forzar la reaplicación del host")
    parser.add_argument("--skip-mod", action="store_true", help="no instalar el mod si falta")
    args = parser.parse_args(argv)

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
            emit(f"Carpeta bbport:        {data['root']}")
            emit(f"Versión instalada:     {data['version']}")
            emit(f"Host Atlas íntegro:    {data['host_intact']}")
            emit(f"Mod instalado:         {data['mod_installed']}")
            emit(f"Última oficial bbport: {data['latest_upstream']}")
            emit(f"Host compatible:       {data['best_host']}")
            emit(f"Actualizar bbport:     {data['needs_official']}")
            emit(f"Aplicar host Atlas:    {data['needs_host']}")
            emit(f"Instalar mod Atlas:    {data['needs_mod']}")
            if data["warning"]:
                emit(f"AVISO: {data['warning']}")
            return 0 if data["up_to_date"] else 10
        import gui
        return gui.run(args.port)
    except Exception as exc:
        emit(f"ERROR: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
