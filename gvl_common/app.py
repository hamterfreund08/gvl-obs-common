"""Fenster der EXE: installieren, aktualisieren, reparieren und deinstallieren.

Oeffnet sich beim Doppelklick auf die EXE im entpackten Ordner oder ueber "App öffnen" im Dock. Welches Programm
es verwaltet, bestimmen das uebergebene installer-Modul und der Updater.
"""
import ctypes
import json
import os
import queue
import subprocess
import sys
import threading
import tkinter
import tkinter.font

from . import FONT, LOGO

EXE_DIR = os.path.dirname(os.path.abspath(sys.executable if getattr(sys, "frozen", False) else __file__))
BG = "#1b1c20"
PANEL = "#26272d"
LINE = "#383a42"
TEXT = "#eceef2"
MUTED = "#9a9dab"
ACCENT = "#d20515"
ACCENT_HOVER = "#ae0411"
HOVER = "#33353d"
WARN = "#d9a406"
WIDTH = 460
POLL_MS = 100
OBS_CHECK_MS = 2000
FR_PRIVATE = 0x10
NO_WINDOW = 0x08000000

EN = {
    "Diese Datei": "This file", "Installiert": "Installed",
    "Neueste Version": "Latest version", "Ordner": "Folder", "nicht installiert": "not installed",
    "älter als 1.9.0": "older than 1.9.0", "wird geprüft ...": "checking ...", "nicht erreichbar": "not reachable",
    "Installieren": "Install", "Reparieren": "Repair", "Aktualisieren auf {v}": "Update to {v}",
    "Deinstallieren": "Uninstall", "Auf GitHub ansehen": "View on GitHub", "Schließen": "Close",
    "OBS läuft gerade. Zum Installieren, Aktualisieren oder Deinstallieren OBS schließen.": "OBS is running. Close OBS to install, update or uninstall.",
    "Bitte zuerst OBS schließen.": "Please close OBS first.", "OBS wurde auf diesem PC nicht gefunden.": "OBS was not found on this PC.",
    "Installiere ...": "Installing ...", "Entferne ...": "Removing ...", "Update wird geladen ... {p} %": "Downloading update ... {p} %",
    "Update wird eingespielt ...": "Applying update ...", "Fehlgeschlagen: {e}": "Failed: {e}",
    "Update auf {v} fertig.": "Updated to {v}.",
    "Version {v} ist auf GitHub, aber ohne Download. Bitte dort laden.": "Version {v} is on GitHub without a download. Please get it there.",
}


class Texts:
    def __init__(self, settings_dir, extra):
        self.table = {**EN, **extra}
        try:
            with open(os.path.join(settings_dir, "settings.json"), encoding="utf-8") as f:
                self.language = json.load(f).get("language") or "de"
        except (OSError, ValueError, AttributeError):
            self.language = "de"

    def __call__(self, text, **values):
        text = self.table.get(text, text) if self.language == "en" else text
        for key, value in values.items():
            text = text.replace("{" + key + "}", str(value))
        return text


def load_font():
    if os.path.isfile(FONT):
        ctypes.windll.gdi32.AddFontResourceExW(FONT, FR_PRIVATE, 0)


class FlatButton(tkinter.Label):
    def __init__(self, parent, text, command, primary=False):
        self.normal = ACCENT if primary else PANEL
        self.hover = ACCENT_HOVER if primary else HOVER
        super().__init__(parent, text=text, bg=self.normal, fg="#ffffff" if primary else TEXT, font=("Montserrat", 10, "bold"),
                         padx=10, pady=9, cursor="hand2", highlightthickness=1, highlightbackground=self.normal if primary else LINE)
        self.command = command
        self.enabled = True
        self.bind("<Enter>", lambda _: self.enabled and self.config(bg=self.hover))
        self.bind("<Leave>", lambda _: self.config(bg=self.normal))
        self.bind("<Button-1>", lambda _: self.enabled and self.command())

    def set(self, text=None, enabled=None):
        if text is not None:
            self.config(text=text)
        if enabled is not None:
            self.enabled = enabled
            self.config(fg=("#ffffff" if self.normal == ACCENT else TEXT) if enabled else "#6b6e7a", cursor="hand2" if enabled else "arrow")


class App:
    def __init__(self, version, installer, updater, name, subtitle, uninstall_question, extra_en):
        self.version = version
        self.installer = installer
        self.updater = updater
        self.name = name
        self.t = Texts(installer.SETTINGS_DIR, extra_en)
        self.subtitle = subtitle
        self.uninstall_question = uninstall_question
        self.busy = False
        self.remote = None
        self.remote_failed = False
        self.inbox = queue.Queue()
        self.root = tkinter.Tk()
        self.root.title(installer.TITLE)
        self.root.configure(bg=BG)
        self.root.resizable(False, False)
        family = "Montserrat" if "Montserrat" in tkinter.font.families() else "Segoe UI"
        self.font = lambda size, weight="normal": (family, size, weight)
        self.logo = tkinter.PhotoImage(file=LOGO).subsample(3) if os.path.isfile(LOGO) else None
        if self.logo:
            self.root.iconphoto(True, tkinter.PhotoImage(file=LOGO))
        self.build()
        self.refresh()
        result = updater.take_result()
        if result:
            self.status(self.t("Fehlgeschlagen: {e}", e=result["error"]) if result.get("error") else self.t("Update auf {v} fertig.", v=self.version),
                        WARN if result.get("error") else TEXT)
        threading.Thread(target=self.check_remote, daemon=True).start()
        self.root.after(POLL_MS, self.poll)
        self.root.after(OBS_CHECK_MS, self.watch_obs)
        self.center()

    def build(self):
        t = self.t
        body = tkinter.Frame(self.root, bg=BG, padx=18, pady=18)
        body.pack(fill="both", expand=True)
        head = tkinter.Frame(body, bg=BG)
        head.pack(fill="x")
        if self.logo:
            tkinter.Label(head, image=self.logo, bg=BG).pack(side="left", padx=(0, 12))
        names = tkinter.Frame(head, bg=BG)
        names.pack(side="left")
        tkinter.Label(names, text=self.name, bg=BG, fg=TEXT, font=self.font(16, "bold")).pack(anchor="w")
        tkinter.Label(names, text=t(self.subtitle), bg=BG, fg=MUTED, font=self.font(9)).pack(anchor="w")

        card = tkinter.Frame(body, bg=PANEL, highlightthickness=1, highlightbackground=LINE, padx=12, pady=10)
        card.pack(fill="x", pady=(16, 12))
        card.columnconfigure(1, weight=1)
        self.values = {}
        for row, key in enumerate(("Diese Datei", "Installiert", "Neueste Version", "Ordner")):
            tkinter.Label(card, text=t(key), bg=PANEL, fg=MUTED, font=self.font(9, "bold")).grid(row=row, column=0, sticky="nw", pady=3, padx=(0, 14))
            value = tkinter.Label(card, text="", bg=PANEL, fg=TEXT, font=self.font(9, "bold"), anchor="w", justify="left", wraplength=280)
            value.grid(row=row, column=1, sticky="w", pady=3)
            self.values[key] = value

        self.main = FlatButton(body, "", self.main_action, primary=True)
        self.main.pack(fill="x")
        self.remove = FlatButton(body, t("Deinstallieren"), self.uninstall)
        self.remove.pack(fill="x", pady=(6, 0))
        row = tkinter.Frame(body, bg=BG)
        row.pack(fill="x", pady=(6, 0))
        row.columnconfigure((0, 1), weight=1, uniform="b")
        FlatButton(row, t("Auf GitHub ansehen"), self.open_release).grid(row=0, column=0, sticky="ew", padx=(0, 3))
        FlatButton(row, t("Schließen"), self.root.destroy).grid(row=0, column=1, sticky="ew", padx=(3, 0))
        self.message = tkinter.Label(body, text="", bg=BG, fg=MUTED, font=self.font(9), wraplength=WIDTH - 36, justify="left", anchor="w")
        self.message.pack(fill="x", pady=(12, 0))

    def center(self):
        self.root.update_idletasks()
        w, h = max(WIDTH, self.root.winfo_reqwidth()), self.root.winfo_reqheight()
        x = (self.root.winfo_screenwidth() - w) // 2
        y = (self.root.winfo_screenheight() - h) // 3
        self.root.geometry(f"{w}x{h}+{x}+{y}")

    def status(self, text, color=MUTED):
        self.message.config(text=text, fg=color)

    def plan(self):
        t, installer, updater = self.t, self.installer, self.updater
        folder = installer.installed_folder()
        installed = installer.version_in(folder) if folder else ""
        if not folder:
            return folder, installed, "install", t("Installieren")
        here = os.path.normcase(EXE_DIR) == os.path.normcase(folder)
        if not here and updater.is_newer(self.version, installed or "0"):
            return folder, installed, "install", t("Aktualisieren auf {v}", v=self.version)
        if self.remote and self.remote["url"] and updater.is_newer(self.remote["version"], installed or "0"):
            return folder, installed, "download", t("Aktualisieren auf {v}", v=self.remote["version"])
        return folder, installed, "install", t("Reparieren")

    def refresh(self):
        t = self.t
        folder, installed, self.kind, label = self.plan()
        self.values["Diese Datei"].config(text=self.version)
        self.values["Installiert"].config(text=(installed or t("älter als 1.9.0")) if folder else t("nicht installiert"))
        remote = self.remote["version"] if self.remote else t("nicht erreichbar") if self.remote_failed else t("wird geprüft ...")
        self.values["Neueste Version"].config(text=remote)
        self.values["Ordner"].config(text=folder or self.installer.TARGET)
        self.main.set(label, not self.busy)
        self.remove.set(enabled=bool(folder) and not self.busy)
        self.root.after_idle(self.center)

    def check_remote(self):
        try:
            self.inbox.put(("remote", self.updater.latest()))
        except (OSError, ValueError):
            self.inbox.put(("remote", None))

    def poll(self):
        while not self.inbox.empty():
            kind, value = self.inbox.get()
            if kind == "remote":
                self.remote = value
                self.remote_failed = value is None
                if value and not value["url"] and self.updater.is_newer(value["version"], self.version):
                    self.status(self.t("Version {v} ist auf GitHub, aber ohne Download. Bitte dort laden.", v=value["version"]), WARN)
            elif kind == "status":
                self.status(*value)
            elif kind == "done":
                self.busy = False
            elif kind == "quit":
                self.root.destroy()
                return
            self.refresh()
        self.root.after(POLL_MS, self.poll)

    def watch_obs(self):
        if not self.busy and self.installer.obs_running() and not self.message.cget("text"):
            self.status(self.t("OBS läuft gerade. Zum Installieren, Aktualisieren oder Deinstallieren OBS schließen."), WARN)
        self.root.after(OBS_CHECK_MS, self.watch_obs)

    def ready(self):
        if not os.path.isdir(self.installer.OBS_DIR):
            self.status(self.t("OBS wurde auf diesem PC nicht gefunden."), WARN)
            return False
        if self.installer.obs_running():
            self.status(self.t("Bitte zuerst OBS schließen."), WARN)
            return False
        return True

    def work(self, job, text):
        if self.busy or not self.ready():
            return
        self.busy = True
        self.status(text)
        self.refresh()

        def runner():
            try:
                job()
            except Exception as e:
                self.inbox.put(("status", (self.t("Fehlgeschlagen: {e}", e=self.installer.describe(e)), WARN)))
            self.inbox.put(("done", None))

        threading.Thread(target=runner, daemon=True).start()

    def main_action(self):
        if self.kind == "download":
            self.work(self.download, self.t("Update wird geladen ... {p} %", p=0))
        else:
            self.work(lambda: self.inbox.put(("status", (self.t(self.installer.install()), TEXT))), self.t("Installiere ..."))

    def download(self):
        folder = self.installer.installed_folder()
        stage = os.path.join(folder, self.updater.STAGE)
        self.updater.download(self.remote["url"], stage, lambda p: self.inbox.put(("status", (self.t("Update wird geladen ... {p} %", p=p), MUTED))))
        self.inbox.put(("status", (self.t("Update wird eingespielt ..."), MUTED)))
        self.updater.start(stage, folder, "app")
        self.inbox.put(("quit", None))

    def uninstall(self):
        if self.busy or not self.ready():
            return
        if ctypes.windll.user32.MessageBoxW(self.root.winfo_id(), self.t(self.uninstall_question), self.installer.TITLE, 0x24) != 6:
            return
        self.work(self.remove_all, self.t("Entferne ..."))

    def remove_all(self):
        self.inbox.put(("status", (self.t(self.installer.uninstall()), TEXT)))
        own = os.path.normcase(EXE_DIR)
        if own in {os.path.normcase(self.installer.USER_TARGET), os.path.normcase(self.installer.SHARED_TARGET)}:
            subprocess.Popen(f'cmd /c ping -n 4 127.0.0.1 >nul & rmdir /s /q "{EXE_DIR}"', creationflags=NO_WINDOW, cwd=os.environ.get("TEMP", "C:\\"))
            self.inbox.put(("quit", None))

    def open_release(self):
        os.startfile((self.remote or {}).get("page") or self.updater.RELEASE_PAGE)


def run(version, installer, updater, name, subtitle, uninstall_question, extra_en):
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        pass
    load_font()
    App(version, installer, updater, name, subtitle, uninstall_question, extra_en).root.mainloop()
