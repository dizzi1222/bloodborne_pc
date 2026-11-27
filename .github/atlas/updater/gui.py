# SPDX-License-Identifier: GPL-2.0-or-later
"""Dark, gold-trimmed Tkinter front-end for the Hunter's Atlas updater."""
from __future__ import annotations

import ctypes
import json
import os
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import core
from i18n import tr

BG = "#0f0d0b"
PANEL = "#191512"
PANEL_2 = "#211b15"
INK = "#0a0807"
GOLD = "#c9a35a"
GOLD_DIM = "#7d6437"
TEXT = "#e9dfcc"
MUTED = "#9a8a74"
GREEN = "#8bbd6e"
AMBER = "#d9a94e"
RED = "#d0735f"
LINE = "#32271b"

FONT_TITLE = ("Georgia", 24, "bold")
FONT_HEAD = ("Georgia", 12, "bold")
FONT_BODY = ("Segoe UI", 10)
FONT_SMALL = ("Segoe UI", 9)
FONT_MONO = ("Consolas", 9)


def pref_path() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA", str(Path.home())))
    return base / "HuntersAtlasUpdater" / "config.json"


def load_port_pref() -> str:
    try:
        return str(json.loads(pref_path().read_text(encoding="utf-8")).get("port", ""))
    except Exception:
        return ""


def save_port_pref(port: Path) -> None:
    try:
        pref_path().parent.mkdir(parents=True, exist_ok=True)
        pref_path().write_text(json.dumps({"port": str(port)}, indent=2), encoding="utf-8")
    except Exception:
        pass


class App:
    def __init__(self, root: tk.Tk, port: str | None = None):
        self.win = root
        self.port = port or ""
        self.updater: core.Updater | None = None
        self.plan: core.Plan | None = None
        self.events: queue.Queue = queue.Queue()
        self.busy = False
        self._build()
        self.win.update_idletasks()
        self._dark_titlebar()
        self.win.after(120, self._bootstrap)
        self.win.after(100, self._drain)

    def _dark_titlebar(self) -> None:
        if os.name != "nt":
            return
        try:
            hwnd = ctypes.windll.user32.GetParent(self.win.winfo_id())
            enabled = ctypes.c_int(1)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, 20, ctypes.byref(enabled), ctypes.sizeof(enabled))
        except Exception:
            pass

    # ------------------------------------------------------------------- ui
    def _build(self) -> None:
        self.win.title(tr("Hunter's Atlas — Actualizador", "Hunter's Atlas — Updater"))
        self.win.configure(bg=BG)
        self.win.geometry("780x660")
        self.win.minsize(720, 600)
        self.win.protocol("WM_DELETE_WINDOW", self._on_close)

        style = ttk.Style(self.win)
        style.theme_use("clam")
        style.configure("Gold.Horizontal.TProgressbar", troughcolor=INK, bordercolor=LINE,
                        background=GOLD, lightcolor=GOLD, darkcolor=GOLD_DIM, thickness=6)

        header = tk.Frame(self.win, bg=BG, padx=26, pady=18)
        header.pack(fill="x")
        tk.Label(header, text="HUNTER'S ATLAS", bg=BG, fg=GOLD, font=FONT_TITLE).pack(anchor="w")
        tk.Label(header, text=tr("Actualizador de bbport · Bloodborne", "bbport · Bloodborne updater"), bg=BG, fg=MUTED,
                 font=FONT_BODY).pack(anchor="w", pady=(2, 0))
        tk.Frame(self.win, bg=LINE, height=1).pack(fill="x", padx=26)

        body = tk.Frame(self.win, bg=BG, padx=26, pady=16)
        body.pack(fill="both", expand=True)

        card = tk.Frame(body, bg=PANEL, highlightbackground=LINE, highlightthickness=1)
        card.pack(fill="x")
        self.status: dict[str, tk.Label] = {}
        cells = (("version", tr("INSTALACIÓN", "INSTALLATION")), ("host", tr("HOST ATLAS", "ATLAS HOST")), ("mod", "MOD"))
        for col, (key, caption) in enumerate(cells):
            cell = tk.Frame(card, bg=PANEL, padx=16, pady=12)
            cell.grid(row=0, column=col, sticky="nsew")
            card.grid_columnconfigure(col, weight=1)
            tk.Label(cell, text=caption, bg=PANEL, fg=MUTED, font=FONT_SMALL).pack(anchor="w")
            value = tk.Label(cell, text="—", bg=PANEL, fg=TEXT, font=FONT_HEAD)
            value.pack(anchor="w", pady=(3, 0))
            self.status[key] = value

        plan_card = tk.Frame(body, bg=PANEL, highlightbackground=LINE, highlightthickness=1)
        plan_card.pack(fill="x", pady=(12, 0))
        inner = tk.Frame(plan_card, bg=PANEL, padx=16, pady=12)
        inner.pack(fill="x")
        self.latest = self._row(inner, tr("Última versión oficial de bbport", "Latest official bbport"))
        self.host_target = self._row(inner, tr("Último host Atlas compatible", "Latest compatible Atlas host"))
        self.summary = tk.Label(plan_card, text=tr("Buscando la última versión…", "Looking for the latest version…"), bg=PANEL, fg=MUTED,
                                font=FONT_BODY, wraplength=690, justify="left", padx=16, pady=12)
        self.summary.pack(fill="x")

        buttons = tk.Frame(body, bg=BG)
        buttons.pack(fill="x", pady=(14, 0))
        self.btn_check = self._button(buttons, tr("Buscar actualización", "Check for updates"), self.check, secondary=True)
        self.btn_check.pack(side="left")
        self.btn_update = self._button(buttons, tr("Actualizar", "Update"), self.update, primary=True)
        self.btn_update.pack(side="left", padx=8)
        self.btn_restore = self._button(buttons, tr("Restaurar backup", "Restore backup"), self.restore, secondary=True)
        self.btn_restore.pack(side="left")
        self.btn_folder = self._button(buttons, tr("Abrir carpeta", "Open folder"), self.open_folder, secondary=True)
        self.btn_folder.pack(side="right")
        self.btn_update.configure(state="disabled")

        progress_row = tk.Frame(body, bg=BG)
        progress_row.pack(fill="x", pady=(14, 2))
        self.progress = ttk.Progressbar(progress_row, style="Gold.Horizontal.TProgressbar",
                                        mode="determinate", maximum=100)
        self.progress.pack(fill="x")
        self.progress_label = tk.Label(body, text=tr("Listo.", "Ready."), bg=BG, fg=MUTED, font=FONT_SMALL)
        self.progress_label.pack(anchor="w", pady=(4, 0))

        log_frame = tk.Frame(body, bg=INK, highlightbackground=LINE, highlightthickness=1)
        log_frame.pack(fill="both", expand=True, pady=(12, 0))
        self.log = tk.Text(log_frame, bg=INK, fg=TEXT, insertbackground=GOLD, font=FONT_MONO,
                           relief="flat", padx=10, pady=8, wrap="word", height=9,
                           state="disabled", borderwidth=0)
        scroll = tk.Scrollbar(log_frame, command=self.log.yview, bg=PANEL, troughcolor=INK,
                              activebackground=GOLD_DIM, width=10, borderwidth=0)
        self.log.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.log.pack(side="left", fill="both", expand=True)
        self.log.tag_configure("ok", foreground=GREEN)
        self.log.tag_configure("warn", foreground=AMBER)
        self.log.tag_configure("error", foreground=RED)
        self.log.tag_configure("muted", foreground=MUTED)

        tk.Label(body, text=tr("Las partidas, ajustes, mods y archivos FSR/DLSS/Seamless se conservan. "
                               "Cada cambio crea un backup host-backup-atlas-*.",
                               "Saves, settings, mods and FSR/DLSS/Seamless files are kept. "
                               "Every change creates a host-backup-atlas-* backup."),
                 bg=BG, fg=MUTED, font=FONT_SMALL, wraplength=700, justify="left").pack(
            anchor="w", pady=(10, 0))

    def _row(self, parent: tk.Frame, caption: str) -> tk.Label:
        row = tk.Frame(parent, bg=PANEL)
        row.pack(fill="x", pady=2)
        tk.Label(row, text=caption, bg=PANEL, fg=MUTED, font=FONT_SMALL).pack(side="left")
        value = tk.Label(row, text="—", bg=PANEL, fg=TEXT, font=FONT_BODY)
        value.pack(side="right")
        return value

    def _button(self, parent, text, command, primary=False, secondary=False) -> tk.Button:
        if primary:
            bg, fg, active = GOLD, INK, "#d9b877"
        else:
            bg, fg, active = PANEL_2, TEXT, "#2b231b"
        return tk.Button(parent, text=text, command=command, bg=bg, fg=fg,
                         activebackground=active, activeforeground=fg, relief="flat",
                         font=("Segoe UI", 10, "bold" if primary else "normal"),
                         padx=16, pady=8, cursor="hand2", borderwidth=0,
                         highlightbackground=LINE, highlightthickness=1 if secondary else 0)

    # --------------------------------------------------------------- helpers
    def write(self, text: str, level: str = "info") -> None:
        tag = level if level in ("ok", "warn", "error", "muted") else ""
        self.log.configure(state="normal")
        self.log.insert("end", text.rstrip() + "\n", tag)
        self.log.see("end")
        self.log.configure(state="disabled")

    def set_progress(self, fraction: float, text: str = "") -> None:
        if fraction < 0:
            self.progress.configure(mode="indeterminate")
            self.progress.start(12)
        else:
            self.progress.stop()
            self.progress.configure(mode="determinate", value=max(0.0, min(1.0, fraction)) * 100)
        if text:
            self.progress_label.configure(text=text)

    def set_busy(self, busy: bool) -> None:
        self.busy = busy
        state = "disabled" if busy else "normal"
        for button in (self.btn_check, self.btn_restore, self.btn_folder):
            button.configure(state=state)
        if busy:
            self.btn_update.configure(state="disabled")
        elif self.plan:
            self.btn_update.configure(state="normal" if self.plan.has_work else "disabled")

    def _drain(self) -> None:
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "log":
                    self.write(*payload)
                elif kind == "progress":
                    self.set_progress(*payload)
                elif kind == "plan":
                    self._show_plan(payload)
                    self.set_busy(False)
                elif kind == "done":
                    self.set_busy(False)
                    self.set_progress(1.0, payload)
                    self.check(log_note=False)
                elif kind == "restored":
                    self.set_busy(False)
                    self.set_progress(1.0, tr(f"Restaurado a {payload}", f"Restored to {payload}"))
                    self.check(log_note=False)
                elif kind == "error":
                    self.set_busy(False)
                    self.set_progress(0.0, "Error")
                    self.write(payload, "error")
                    messagebox.showerror("Hunter's Atlas", payload)
        except queue.Empty:
            pass
        self.win.after(120, self._drain)

    # ----------------------------------------------------------------- flow
    def _bootstrap(self) -> None:
        try:
            self.root_path = core.resolve_root(self.port or load_port_pref() or None)
            save_port_pref(self.root_path)
            self.updater = core.Updater(self.root_path, self._log_threadsafe, self._progress_threadsafe)
            self.write(tr(f"Instalación detectada: {self.root_path}", f"Installation found: {self.root_path}"), "muted")
            self.check()
        except core.RootNotFound:
            chosen = filedialog.askdirectory(title=tr("Selecciona la carpeta bbport-windows", "Select the bbport-windows folder"))
            if not chosen:
                self.win.destroy()
                return
            try:
                self.root_path = core.resolve_root(chosen)
                save_port_pref(self.root_path)
                self.port = str(self.root_path)
                self.updater = core.Updater(self.root_path, self._log_threadsafe, self._progress_threadsafe)
                self.check()
            except Exception as exc:
                messagebox.showerror("Hunter's Atlas", str(exc))
                self.win.destroy()
        except Exception as exc:
            messagebox.showerror("Hunter's Atlas", str(exc))
            self.win.destroy()

    def _log_threadsafe(self, message: str, level: str = "info") -> None:
        self.events.put(("log", (message, level)))

    def _progress_threadsafe(self, fraction: float, text: str = "") -> None:
        self.events.put(("progress", (fraction, text)))

    def check(self, log_note: bool = True) -> None:
        if self.busy or not self.updater:
            return
        self.set_busy(True)
        self.set_progress(-1, tr("Consultando GitHub…", "Checking GitHub…"))
        if log_note:
            self.write(tr("Buscando actualizaciones…", "Checking for updates…"), "muted")

        def work():
            try:
                plan = self.updater.plan()
                self.events.put(("plan", plan))
            except Exception as exc:
                self.events.put(("error", str(exc)))

        threading.Thread(target=work, daemon=True).start()

    def _show_plan(self, plan: core.Plan) -> None:
        self.plan = plan
        local = plan.local
        self.status["version"].configure(text=local.version or "—")
        self.status["host"].configure(text=tr("Activo", "Active") if local.host_intact else tr("No aplicado", "Not applied"),
                                      fg=GREEN if local.host_intact else AMBER)
        self.status["mod"].configure(text=tr("Instalado", "Installed") if local.mod_installed else tr("No instalado", "Not installed"),
                                     fg=GREEN if local.mod_installed else MUTED)
        self.latest.configure(text=plan.latest_upstream.version if plan.latest_upstream else "—")
        self.host_target.configure(text=plan.best_host.host_version if plan.best_host else "—")
        self.set_progress(0.0, tr("Listo.", "Ready."))
        if plan.up_to_date:
            self.summary.configure(text=tr(f"Todo está al día. Versión activa: {local.version}.", f"Everything is up to date. Active version: {local.version}."), fg=GREEN)
            self.btn_update.configure(state="disabled", text=tr("Actualizar", "Update"))
            return
        self.btn_update.configure(state="normal")
        self.btn_update.configure(text=tr(f"Actualizar a {plan.target_version}", f"Update to {plan.target_version}")
                                  if (plan.needs_official or plan.needs_host) else tr("Instalar mod", "Install mod"))
        pieces = []
        if plan.needs_official and plan.matching_upstream:
            pieces.append(tr(f"Se actualizará bbport {local.base_version} → {plan.matching_upstream.version}", f"bbport {local.base_version} → {plan.matching_upstream.version} will be updated"))
        if plan.needs_host:
            pieces.append(tr(f"Se aplicará el host {plan.target_version}", f"Host {plan.target_version} will be applied"))
        if plan.needs_mod and plan.latest_mod:
            pieces.append(tr(f"Se instalará el mod Hunter's Atlas {plan.latest_mod.mod_version}", f"Hunter's Atlas mod {plan.latest_mod.mod_version} will be installed"))
        self.summary.configure(text=". ".join(pieces) + ".", fg=TEXT)
        if plan.warning:
            self.write(plan.warning, "warn")

    def update(self) -> None:
        if self.busy or not self.updater or not self.plan or not self.plan.has_work:
            return
        plan = self.plan
        self.set_busy(True)
        self.set_progress(0.0, tr("Preparando…", "Preparing…"))
        self.write(tr(f"Actualizando a {plan.target_version}…", f"Updating to {plan.target_version}…"))

        def work():
            try:
                version = self.updater.run(plan)
                self.events.put(("done", version))
            except Exception as exc:
                self.events.put(("error", str(exc)))

        threading.Thread(target=work, daemon=True).start()

    def restore(self) -> None:
        if self.busy or not self.updater:
            return
        if not messagebox.askyesno(
                tr("Restaurar backup", "Restore backup"),
                tr("Se restaurará el último backup host-backup-atlas-* y se deshará el último "
                   "cambio de host.\n\n¿Continuar?",
                   "The latest host-backup-atlas-* backup will be restored, undoing the last "
                   "host change.\n\nContinue?")):
            return
        self.set_busy(True)
        self.set_progress(-1, tr("Restaurando…", "Restoring…"))

        def work():
            try:
                version = self.updater.restore()
                self.events.put(("restored", version))
            except Exception as exc:
                self.events.put(("error", str(exc)))

        threading.Thread(target=work, daemon=True).start()

    def open_folder(self) -> None:
        try:
            os.startfile(self.root_path)
        except Exception as exc:
            self.write(str(exc), "error")

    def _on_close(self) -> None:
        if self.busy and not messagebox.askyesno(
                "Hunter's Atlas", tr("Hay una actualización en curso. ¿Cerrar de todos modos?", "An update is in progress. Close anyway?")):
            return
        self.win.destroy()


def run(port: str | None = None) -> int:
    root = tk.Tk()
    App(root, port)
    root.mainloop()
    return 0
