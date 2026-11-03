"""GVL Konferenz-Modul: laedt das Bild-Plugin (ninja-obs-plugin, AGPL-3.0) aus dessen offiziellem GitHub-Release und
installiert es fuer den aktuellen Windows-Benutzer.

Das Plugin wird nicht mit ausgeliefert, sondern bei der Installation unveraendert vom Release geladen und gegen die
dort veroeffentlichte checksums.txt geprueft. Ziel ist %ProgramData%\\obs-studio\\plugins\\obs-vdoninja, dort laedt
OBS unter Windows Plugins ausserhalb des Programmordners, und Benutzer duerfen den Ordner ohne Admin-Rechte anlegen.
Der Ordner %APPDATA%\\obs-studio\\plugins, den das Skript des Plugins nimmt, wird von OBS 32.1 nicht gelesen. Welcher Build passt, haengt von
der OBS-Version ab: 32.0 bis 32.1 brauchen den Legacy-Build (FFmpeg 7), 32.2 und 33.0 den normalen (FFmpeg 8).
Ist das Plugin schon systemweit im OBS-Ordner installiert, bleibt es dabei, damit OBS es nicht doppelt laedt.
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

REPO = "steveseguin/ninja-obs-plugin"
LATEST_API = f"https://api.github.com/repos/{REPO}/releases/latest"
DOWNLOAD_PREFIX = f"https://github.com/{REPO}/releases/download/"
PAGE = f"https://github.com/{REPO}/releases/latest"
DLL = "obs-vdoninja.dll"
USER_DIR = os.path.join(os.environ.get("ProgramData", r"C:\ProgramData"), "obs-studio", "plugins", "obs-vdoninja")
OLD_USER_DIR = os.path.join(obs.OBS_DIR, "plugins", "obs-vdoninja")
MARKER_NAME = "gvl_module.json"
MARKER = os.path.join(USER_DIR, MARKER_NAME)
ASSET_CURRENT = "obs-vdoninja-windows-x64.zip"
ASSET_LEGACY = "obs-vdoninja-windows-x64-obs32.0-32.1.zip"
ZIP_BIN = "obs-plugins/64bit/"
ZIP_DATA = "data/obs-plugins/obs-vdoninja/"
TIMEOUT = 60
CHUNK = 256 * 1024


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


def system_install():
    root = obs_root()
    return bool(root) and os.path.isfile(os.path.join(root, "obs-plugins", "64bit", DLL))


def marker():
    try:
        with open(MARKER, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def status():
    """Liefert (zustand, text). Zustaende: ok, system, missing, wrong, unsupported, no-obs."""
    version = obs_version()
    if not version:
        return "no-obs", "OBS wurde auf diesem PC nicht gefunden."
    if system_install():
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
    return urllib.request.Request(url, headers={"User-Agent": "GVL-Regie", "Accept": "application/vnd.github+json"})


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


def extract(archive, target):
    """Kopiert nur den Plugin-Teil der ZIP: bin\\64bit und data, keine Skripte."""
    with zipfile.ZipFile(archive) as z:
        for info in z.infolist():
            name = info.filename.replace("\\", "/")
            if info.is_dir() or ".." in name.split("/"):
                continue
            for prefix, folder in ((ZIP_BIN, os.path.join("bin", "64bit")), (ZIP_DATA, "data")):
                if name.startswith(prefix):
                    path = os.path.join(target, folder, *name[len(prefix):].split("/"))
                    os.makedirs(os.path.dirname(path), exist_ok=True)
                    with z.open(info) as source, open(path, "wb") as out:
                        shutil.copyfileobj(source, out)
    if not os.path.isfile(os.path.join(target, "bin", "64bit", DLL)):
        raise ModuleError(f"{DLL} fehlt in der heruntergeladenen Datei.")


def remove_old_copy():
    if os.path.isfile(os.path.join(OLD_USER_DIR, MARKER_NAME)):
        shutil.rmtree(OLD_USER_DIR, ignore_errors=True)


def install(log=print):
    """Installiert oder ersetzt das Modul. OBS muss geschlossen sein."""
    remove_old_copy()
    state, text = status()
    if state in ("ok", "system"):
        log(text)
        return state
    if state in ("no-obs", "unsupported"):
        raise ModuleError(text)
    if obs.obs_running():
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
        shutil.rmtree(USER_DIR, ignore_errors=True)
        shutil.copytree(staged, USER_DIR)
    with open(MARKER, "w", encoding="utf-8") as f:
        json.dump({"version": tag, "asset": asset}, f)
    log(f"Konferenz-Modul {tag} installiert.")
    return "installed"


def uninstall():
    """Entfernt nur ein Modul, das wir selbst installiert haben."""
    remove_old_copy()
    if marker():
        shutil.rmtree(USER_DIR, ignore_errors=True)
        return True
    return False
