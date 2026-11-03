"""OBS-Dateien und Windows-Prozesse: Docks und Skripte eintragen, OBS erkennen, eigene Dienste beenden."""
import ctypes
import json
import os
import time
from ctypes import wintypes

OBS_DIR = os.path.join(os.environ.get("APPDATA", ""), "obs-studio")
SNAPSHOT_PROCESSES = 0x2
PROCESS_TERMINATE = 0x1
STOP_WAIT = 5


class ProcessEntry(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
                ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", wintypes.LONG), ("dwFlags", wintypes.DWORD),
                ("szExeFile", wintypes.WCHAR * 260)]


def process_list():
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessEntry)]
    kernel.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessEntry)]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    snapshot = kernel.CreateToolhelp32Snapshot(SNAPSHOT_PROCESSES, 0)
    entry = ProcessEntry()
    entry.dwSize = ctypes.sizeof(ProcessEntry)
    found = []
    more = kernel.Process32FirstW(snapshot, ctypes.byref(entry))
    while more:
        found.append((entry.th32ProcessID, entry.th32ParentProcessID, entry.szExeFile.lower()))
        more = kernel.Process32NextW(snapshot, ctypes.byref(entry))
    kernel.CloseHandle(snapshot)
    return found


def obs_pids():
    return {pid for pid, _, name in process_list() if name == "obs64.exe"}


def obs_running():
    return bool(obs_pids())


def stop_service(service_exe, tunnel_exe="cloudflared.exe"):
    """Beendet laufende Dienste mit diesem EXE-Namen und nur deren eigene Tunnel-Prozesse."""
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    me = os.getpid()
    processes = process_list()
    services = {pid for pid, _, name in processes if name == service_exe.lower() and pid != me}
    tunnels = {pid for pid, parent, name in processes if name == tunnel_exe and parent in services}
    for pid in services | tunnels:
        handle = kernel.OpenProcess(PROCESS_TERMINATE, False, pid)
        if handle:
            kernel.TerminateProcess(handle, 0)
            kernel.CloseHandle(handle)
    end = time.time() + STOP_WAIT
    while time.time() < end and services & {pid for pid, _, _ in process_list()}:
        time.sleep(0.2)


def read_text(path):
    with open(path, encoding="utf-8-sig") as f:
        return f.read()


def write_text(path, text):
    tmp = path + ".gvl-tmp"
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        f.write(text)
    os.replace(tmp, path)


def config_files():
    return [os.path.join(OBS_DIR, name) for name in ("user.ini", "global.ini")]


def scene_files():
    folder = os.path.join(OBS_DIR, "basic", "scenes")
    if not os.path.isdir(folder):
        return []
    return [os.path.join(folder, name) for name in os.listdir(folder) if name.endswith(".json")]


def set_docks(path, change):
    if not os.path.isfile(path):
        return
    lines = read_text(path).split("\n")
    for i, line in enumerate(lines):
        if line.rstrip("\r").startswith("ExtraBrowserDocks="):
            ending = "\r" if line.endswith("\r") else ""
            value = line.rstrip("\r").split("=", 1)[1]
            lines[i] = "ExtraBrowserDocks=" + json.dumps(change(json.loads(value or "[]")), separators=(",", ":")) + ending
            break
    else:
        for i, line in enumerate(lines):
            if line.rstrip("\r") == "[BasicWindow]":
                lines.insert(i + 1, "ExtraBrowserDocks=" + json.dumps(change([]), separators=(",", ":")))
                break
    write_text(path, "\n".join(lines))


def set_script(path, change):
    data = json.loads(read_text(path))
    modules = data.setdefault("modules", {})
    modules["scripts-tool"] = change(modules.get("scripts-tool") or [])
    write_text(path, json.dumps(data, ensure_ascii=False, indent=4))


def register(title, dock_url, dock_uuid, script_path):
    """Traegt Dock und Lua-Skript in OBS ein. OBS muss geschlossen sein."""
    name = os.path.basename(script_path).lower()
    dock = {"title": title, "url": dock_url, "uuid": dock_uuid}
    script = {"path": script_path.replace("\\", "/"), "settings": {}}
    for path in config_files():
        set_docks(path, lambda docks: [d for d in docks if d.get("title") != title] + [dock])
    for path in scene_files():
        set_script(path, lambda scripts: [s for s in scripts if os.path.basename(str(s.get("path"))).lower() != name] + [script])


def unregister(title, script_name):
    name = script_name.lower()
    for path in config_files():
        set_docks(path, lambda docks: [d for d in docks if d.get("title") != title])
    for path in scene_files():
        set_script(path, lambda scripts: [s for s in scripts if os.path.basename(str(s.get("path"))).lower() != name])
