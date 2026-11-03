"""Sucht auf GitHub nach einer neuen Version und spielt sie ein.

Die ZIP aus dem neuesten Release landet im Unterordner _update des Programmordners. Von dort startet die neue
EXE mit --apply-update, wartet, bis die alte beendet ist, kopiert sich ueber den Programmordner und startet
danach wieder den Dienst oder die App. Das Lua-Skript liest OBS nur beim Start. Aendert es sich, zeigen Dock
und App den Hinweis, OBS einmal neu zu starten.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import zipfile

from . import files

STAGE = "_update"
RESULT_NAME = "update_result.json"
CHECK_TIMEOUT = 15
DOWNLOAD_TIMEOUT = 60
CHUNK = 256 * 1024
COPY_ATTEMPTS = 8
COPY_DELAY = 1.5
DETACHED = 0x00000008 | 0x00000200


def numbers(version):
    return tuple(int(n) for n in re.findall(r"\d+", str(version or ""))[:3])


def is_newer(remote, current):
    return bool(numbers(remote)) and numbers(remote) > numbers(current)


def launch(exe, *args):
    env = dict(os.environ, PYINSTALLER_RESET_ENVIRONMENT="1")
    subprocess.Popen([exe, *args], cwd=os.path.dirname(exe), env=env, creationflags=DETACHED, close_fds=True,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def clean(folder):
    files.remove_tree(folder)


def read_bytes(path):
    try:
        with open(path, "rb") as f:
            return f.read()
    except OSError:
        return None


class Updater:
    """repo/asset: GitHub-Repo und Name der ZIP im Release. Gibt es das Repo noch nicht, findet latest() nichts."""

    def __init__(self, repo, asset, agent, required_files, obs_files, settings_dir, stop_service):
        self.repo = repo
        self.asset = asset
        self.agent = agent
        self.required_files = required_files
        self.obs_files = obs_files
        self.settings_dir = settings_dir
        self.stop_service = stop_service
        self.latest_api = f"https://api.github.com/repos/{repo}/releases/latest"
        self.release_page = f"https://github.com/{repo}/releases/latest"
        self.download_prefix = f"https://github.com/{repo}/releases/download/"

    def request(self, url):
        return urllib.request.Request(url, headers={"User-Agent": self.agent, "Accept": "application/vnd.github+json"})

    def missing_files(self, folder):
        return [name for name in self.required_files if not os.path.isfile(os.path.join(folder, name))]

    def latest(self):
        try:
            with urllib.request.urlopen(self.request(self.latest_api), timeout=CHECK_TIMEOUT) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            raise
        url = next((a.get("browser_download_url") or "" for a in data.get("assets") or [] if a.get("name") == self.asset), "")
        return {"version": str(data.get("tag_name") or "").lstrip("vV"), "url": url if url.startswith(self.download_prefix) else "",
                "page": data.get("html_url") or self.release_page}

    def download(self, url, folder, progress):
        clean(folder)
        os.makedirs(folder, exist_ok=True)
        archive = os.path.join(folder, self.asset)
        with urllib.request.urlopen(self.request(url), timeout=DOWNLOAD_TIMEOUT) as resp, open(archive, "wb") as f:
            size = int(resp.headers.get("Content-Length") or 0)
            done = 0
            while chunk := resp.read(CHUNK):
                f.write(chunk)
                done += len(chunk)
                if size:
                    progress(done * 100 // size)
        with zipfile.ZipFile(archive) as z:
            z.extractall(folder)
        os.remove(archive)
        missing = self.missing_files(folder)
        if missing:
            raise OSError(f"Dateien fehlen nach dem Entpacken: {', '.join(missing)}. Der Virenschutz hat sie eventuell entfernt.")

    def start(self, folder, target, then):
        launch(os.path.join(folder, self.required_files[0]), "--apply-update", target, then)

    def apply(self, target, then):
        stage = os.path.dirname(os.path.abspath(sys.executable))
        self.stop_service()
        restart_obs = then == "service" and any(read_bytes(os.path.join(stage, n)) != read_bytes(os.path.join(target, n)) for n in self.obs_files)
        error = ""
        for _ in range(COPY_ATTEMPTS):
            try:
                shutil.copytree(stage, target, copy_function=files.copy_file, dirs_exist_ok=True)
                missing = self.missing_files(target)
                if missing:
                    raise OSError(f"Dateien fehlen: {', '.join(missing)}")
                error = ""
                break
            except OSError as e:
                error = str(e)
                time.sleep(COPY_DELAY)
        if not error and not os.path.isdir(os.path.join(stage, "_internal")):
            files.remove_tree(os.path.join(target, "_internal"))
        print(f"Update nach {target}: {error or 'fertig'}", flush=True)
        os.makedirs(self.settings_dir, exist_ok=True)
        with open(os.path.join(self.settings_dir, RESULT_NAME), "w", encoding="utf-8") as f:
            json.dump({"error": error, "restartObs": restart_obs}, f)
        args = ("--service", "--updated") if then == "service" else ("--app", "--updated")
        launch(os.path.join(target, self.required_files[0]), *args)

    def take_result(self):
        path = os.path.join(self.settings_dir, RESULT_NAME)
        try:
            with open(path, encoding="utf-8") as f:
                result = json.load(f)
        except (OSError, ValueError):
            result = None
        try:
            os.remove(path)
        except OSError:
            pass
        return result if isinstance(result, dict) and "--updated" in sys.argv else None
