"""Cloudflare-Quick-Tunnel ueber den eigenen cloudflared-Prozess.

Es wird nur der selbst gestartete Prozess beendet, nie ein anderer cloudflared auf dem PC.
"""
import asyncio
import os
import re

NO_WINDOW = 0x08000000
TUNNEL_WAIT = 40
URL_PATTERN = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")


class Tunnel:
    def __init__(self, exe, port, on_change, host="127.0.0.1"):
        self.exe = exe
        self.target = f"http://{host}:{port}"
        self.on_change = on_change
        self.process = None
        self.tasks = []
        self.state = {"state": "off", "url": "", "message": ""}

    def set(self, state, url="", message=""):
        self.state = {"state": state, "url": url, "message": message}
        self.on_change()

    async def start(self):
        if self.state["state"] != "off":
            return
        if not os.path.isfile(self.exe):
            self.set("off", message="cloudflared.exe fehlt. Bitte neu installieren.")
            return
        self.set("starting")
        self.process = await asyncio.create_subprocess_exec(
            self.exe, "tunnel", "--no-autoupdate", "--url", self.target,
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE, creationflags=NO_WINDOW)
        self.tasks = [asyncio.create_task(self.watch(self.process)), asyncio.create_task(self.timeout(self.process))]

    async def watch(self, process):
        found = False
        try:
            while True:
                line = await process.stderr.readline()
                if not line:
                    break
                url = URL_PATTERN.search(line.decode("utf-8", "replace"))
                if url and not found and "api.trycloudflare" not in url.group(0):
                    found = True
                    self.set("ready", url.group(0))
        finally:
            if process is self.process:
                self.process = None
                self.set("off", message="Der Tunnel wurde beendet. Bitte neu starten.")

    async def timeout(self, process):
        await asyncio.sleep(TUNNEL_WAIT)
        if process is self.process and self.state["state"] == "starting":
            await self.stop()
            self.set("off", message="Cloudflare hat nicht geantwortet. Bitte erneut versuchen.")

    async def stop(self):
        process, self.process = self.process, None
        if process and process.returncode is None:
            process.kill()
            await process.wait()
        if self.state["state"] != "off" or self.state["message"]:
            self.set("off")
