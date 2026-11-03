"""OBS-Plugins, die GVL Media Studio und GVL Regie brauchen, automatisch installieren.

Beide Plugins werden nicht mit ausgeliefert, sondern bei der Installation unveraendert aus ihrem offiziellen
GitHub-Release geladen und geprueft. Ziel ist %ProgramData%\\obs-studio\\plugins\\<name>: Dort laedt OBS unter Windows
Plugins ausserhalb des Programmordners, und Benutzer duerfen den Ordner ohne Admin-Rechte anlegen. Den Ordner
%APPDATA%\\obs-studio\\plugins, den das Skript des Bild-Plugins nimmt, liest OBS 32.1 nicht.

- GVL Konferenz-Modul (ninja-obs-plugin, AGPL-3.0): neuestes Release, geprueft gegen dessen checksums.txt. Welcher
  Build passt, haengt von der OBS-Version ab: 32.0 bis 32.1 brauchen den Legacy-Build (FFmpeg 7), 32.2 und 33 den
  normalen (FFmpeg 8).
- Move Transition (GPL-2.0): feste Version, geprueft gegen die hier hinterlegte SHA-256, weil das Release keine
  Pruefsummen-Datei hat.

Ist ein Plugin schon systemweit im OBS-Ordner installiert, bleibt es dabei, damit OBS es nicht doppelt laedt.
Ein noch nicht installiertes Plugin darf auch bei laufendem OBS kopiert werden, OBS laedt es beim naechsten Start.
"""
import ctypes
import hashlib
import json
import os
import re
import shutil
import tempfile
import urllib.request
import winreg
import zipfile

from . import obs

PLUGIN_ROOT = os.path.join(os.environ.get("ProgramData", r"C:\ProgramData"), "obs-studio", "plugins")
MARKER_NAME = "gvl_module.json"
TIMEOUT = 60
CHUNK = 256 * 1024

REPO = "steveseguin/ninja-obs-plugin"
LATEST_API = f"https://api.github.com/repos/{REPO}/releases/latest"
DOWNLOAD_PREFIX = f"https://github.com/{REPO}/releases/download/"
PAGE = f"https://github.com/{REPO}/releases/latest"
DLL = "obs-vdoninja.dll"
USER_DIR = os.path.join(PLUGIN_ROOT, "obs-vdoninja")
OLD_USER_DIR = os.path.join(obs.OBS_DIR, "plugins", "obs-vdoninja")
MARKER = os.path.join(USER_DIR, MARKER_NAME)
ASSET_CURRENT = "obs-vdoninja-windows-x64.zip"
ASSET_LEGACY = "obs-vdoninja-windows-x64-obs32.0-32.1.zip"
ZIP_PARTS = (("obs-plugins/64bit/", os.path.join("bin", "64bit")), ("data/obs-plugins/obs-vdoninja/", "data"))

MOVE_VERSION = "3.2.1"
MOVE_URL = f"https://github.com/exeldro/obs-move-transition/releases/download/{MOVE_VERSION}/move-transition-{MOVE_VERSION}-windows-programdata.zip"
MOVE_SHA256 = "54bdd712e10f88fc66ea4abfe25503e3080da66a4afe964b924af38ed7079cc8"
MOVE_DLL = "move-transition.dll"
MOVE_DIR = os.path.join(PLUGIN_ROOT, "move-transition")
MOVE_PARTS = (("move-transition/bin/64bit/", os.path.join("bin", "64bit")), ("move-transition/data/", "data"))


class ModuleError(Exception):
    pass


def obs_root():
    for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\OBS Studio", 0, winreg.KEY_READ | view) as key:
                path = winreg.QueryValueEx(key, "")[0]
            if os.path.isfile(os.path.join(path, "bin", "64bit", "obs64.exe")):
                return path
        except OSError:
            pass
    default = os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "obs-studio")
    return default if os.path.isfile(os.path.join(default, "bin", "64bit", "obs64.exe")) else ""


def file_version(path):
    """OBS setzt nur die Text-Version (z. B. "32.1.2"), die feste Versionsnummer ist 0.0.0."""
    version = ctypes.WinDLL("version")
    size = version.GetFileVersionInfoSizeW(path, None)
    if not size:
        return ()
    buffer = ctypes.create_string_buffer(size)
    if not version.GetFileVersionInfoW(path, 0, size, buffer):
        return ()
    pointer = ctypes.c_void_p()
    length = ctypes.c_uint()
    languages = ["040904b0"]
    if version.VerQueryValueW(buffer, "\\VarFileInfo\\Translation", ctypes.byref(pointer), ctypes.byref(length)) and length.value >= 4:
        pair = ctypes.cast(pointer, ctypes.POINTER(ctypes.c_uint16 * 2)).contents
        languages.insert(0, f"{pair[0]:04x}{pair[1]:04x}")
    for language in languages:
        if version.VerQueryValueW(buffer, f"\\StringFileInfo\\{language}\\ProductVersion", ctypes.byref(pointer), ctypes.byref(length)) and length.value:
            numbers = re.findall(r"\d+", ctypes.wstring_at(pointer, length.value))
            if len(numbers) >= 2:
                return tuple(int(n) for n in (numbers + ["0"])[:3])
    return ()


def obs_version():
    root = obs_root()
    return file_version(os.path.join(root, "bin", "64bit", "obs64.exe")) if root else ()


def asset_for(version):
    if (32, 2) <= version[:2] < (34, 0):
        return ASSET_CURRENT
    if (32, 0) <= version[:2] < (32, 2):
        return ASSET_LEGACY
    return ""


def system_install(dll):
    root = obs_root()
    return bool(root) and os.path.isfile(os.path.join(root, "obs-plugins", "64bit", dll))


def read_marker(folder):
    try:
        with open(os.path.join(folder, MARKER_NAME), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def marker():
    return read_marker(USER_DIR)


def status():
    """Liefert (zustand, text) fuer das Konferenz-Modul. Zustaende: ok, system, missing, wrong, unsupported, no-obs."""
    version = obs_version()
    if not version:
        return "no-obs", "OBS wurde auf diesem PC nicht gefunden."
    if system_install(DLL):
        return "system", "Das Konferenz-Modul ist im OBS-Ordner installiert."
    wanted = asset_for(version)
    if not wanted:
        return "unsupported", f"OBS {'.'.join(map(str, version))} wird vom Konferenz-Modul nicht unterstützt. Bitte OBS 32.2 oder neuer installieren."
    if not os.path.isfile(os.path.join(USER_DIR, "bin", "64bit", DLL)):
        return "missing", "Das Konferenz-Modul ist noch nicht installiert."
    if marker().get("asset") not in (None, wanted):
        return "wrong", "Das Konferenz-Modul passt nicht mehr zur OBS-Version und wird neu installiert."
    return "ok", f"Konferenz-Modul {marker().get('version') or ''} ist installiert.".replace("  ", " ")


def request(url):
    return urllib.request.Request(url, headers={"User-Agent": "GVL-OBS", "Accept": "application/vnd.github+json"})


def download(url, path):
    with urllib.request.urlopen(request(url), timeout=TIMEOUT) as resp, open(path, "wb") as f:
        while chunk := resp.read(CHUNK):
            f.write(chunk)


def release(asset):
    with urllib.request.urlopen(request(LATEST_API), timeout=TIMEOUT) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    urls = {a.get("name"): a.get("browser_download_url") or "" for a in data.get("assets") or []}
    if not urls.get(asset, "").startswith(DOWNLOAD_PREFIX) or not urls.get("checksums.txt", "").startswith(DOWNLOAD_PREFIX):
        raise ModuleError(f"Im neuesten Release fehlt {asset}. Bitte von Hand installieren: {PAGE}")
    return str(data.get("tag_name") or ""), urls[asset], urls["checksums.txt"]


def expected_hash(checksums, asset):
    for line in checksums.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1].lstrip("*") == asset:
            return parts[0].lower()
    raise ModuleError(f"Keine Prüfsumme für {asset} gefunden.")


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def extract(archive, target, parts=ZIP_PARTS, dll=DLL):
    """Kopiert nur die Plugin-Teile der ZIP (bin\\64bit und data), keine Skripte."""
    with zipfile.ZipFile(archive) as z:
        for info in z.infolist():
            name = info.filename.replace("\\", "/")
            if info.is_dir() or ".." in name.split("/") or name.endswith(".pdb"):
                continue
            for prefix, folder in parts:
                if name.startswith(prefix):
                    path = os.path.join(target, folder, *name[len(prefix):].split("/"))
                    os.makedirs(os.path.dirname(path), exist_ok=True)
                    with z.open(info) as source, open(path, "wb") as out:
                        shutil.copyfileobj(source, out)
    if not os.path.isfile(os.path.join(target, "bin", "64bit", dll)):
        raise ModuleError(f"{dll} fehlt in der heruntergeladenen Datei.")


def place(staged, folder, info):
    shutil.rmtree(folder, ignore_errors=True)
    shutil.copytree(staged, folder)
    with open(os.path.join(folder, MARKER_NAME), "w", encoding="utf-8") as f:
        json.dump(info, f)


def remove_old_copy():
    if os.path.isfile(os.path.join(OLD_USER_DIR, MARKER_NAME)):
        shutil.rmtree(OLD_USER_DIR, ignore_errors=True)


def install(log=print, allow_running=False):
    """Installiert oder ersetzt das Konferenz-Modul."""
    remove_old_copy()
    state, text = status()
    if state in ("ok", "system"):
        log(text)
        return state
    if state in ("no-obs", "unsupported"):
        raise ModuleError(text)
    if obs.obs_running() and not (allow_running and state == "missing"):
        raise ModuleError("Bitte zuerst OBS schließen.")
    asset = asset_for(obs_version())
    tag, url, checksums_url = release(asset)
    log(f"Lade Konferenz-Modul {tag} ...")
    with tempfile.TemporaryDirectory(prefix="gvl-module-") as folder:
        archive = os.path.join(folder, asset)
        sums = os.path.join(folder, "checksums.txt")
        download(url, archive)
        download(checksums_url, sums)
        with open(sums, encoding="utf-8") as f:
            wanted = expected_hash(f.read(), asset)
        if sha256(archive) != wanted:
            raise ModuleError("Die Prüfsumme des Konferenz-Moduls stimmt nicht. Download abgebrochen.")
        staged = os.path.join(folder, "module")
        extract(archive, staged)
        place(staged, USER_DIR, {"version": tag, "asset": asset})
    log(f"Konferenz-Modul {tag} installiert.")
    return "installed"


def uninstall():
    """Entfernt nur ein Modul, das wir selbst installiert haben."""
    remove_old_copy()
    if marker():
        shutil.rmtree(USER_DIR, ignore_errors=True)
        return True
    return False


def move_status():
    """Zustaende: ok, system, missing, old."""
    if system_install(MOVE_DLL):
        return "system"
    if not os.path.isfile(os.path.join(MOVE_DIR, "bin", "64bit", MOVE_DLL)):
        return "missing"
    installed = read_marker(MOVE_DIR).get("version")
    return "old" if installed and installed != MOVE_VERSION else "ok"


def install_move(log=print, allow_running=False):
    """Installiert Move Transition in der hier festgelegten Version."""
    state = move_status()
    if state in ("ok", "system"):
        return state
    if state == "missing" and os.path.isdir(MOVE_DIR) and not read_marker(MOVE_DIR):
        return "foreign"
    if obs.obs_running() and not (allow_running and state == "missing"):
        raise ModuleError("Bitte zuerst OBS schließen.")
    log(f"Lade Move Transition {MOVE_VERSION} ...")
    with tempfile.TemporaryDirectory(prefix="gvl-move-") as folder:
        archive = os.path.join(folder, "move.zip")
        download(MOVE_URL, archive)
        if sha256(archive) != MOVE_SHA256:
            raise ModuleError("Die Prüfsumme von Move Transition stimmt nicht. Download abgebrochen.")
        staged = os.path.join(folder, "move")
        extract(archive, staged, MOVE_PARTS, MOVE_DLL)
        place(staged, MOVE_DIR, {"version": MOVE_VERSION})
    log(f"Move Transition {MOVE_VERSION} installiert.")
    return "installed"


def uninstall_move():
    if read_marker(MOVE_DIR):
        shutil.rmtree(MOVE_DIR, ignore_errors=True)
        return True
    return False


def install_all(log=print, allow_running=False, move=False):
    """Installiert alles, was fehlt. Fehler werden gemeldet, brechen aber nichts anderes ab."""
    problems = []
    try:
        install(log, allow_running)
    except (ModuleError, OSError, ValueError) as e:
        problems.append(f"Konferenz-Modul: {e}")
    if move:
        try:
            install_move(log, allow_running)
        except (ModuleError, OSError, ValueError) as e:
            problems.append(f"Move Transition: {e}")
    return problems
