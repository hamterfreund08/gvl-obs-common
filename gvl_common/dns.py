"""Namensaufloesung fuer frische trycloudflare-Adressen.

Eine Quick-Tunnel-Adresse ist in den ersten Sekunden noch nicht im DNS. Fragt Windows in dieser Zeit nach, merkt es
sich "gibt es nicht" fuer mehrere Minuten, auch wenn die Adresse laengst erreichbar ist. Deshalb:

- wait_until_resolvable prueft ueber DNS-over-HTTPS bei Cloudflare, ohne den Windows-Cache zu beruehren.
- FallbackResolver nimmt zuerst die normale Aufloesung und fragt bei einem Fehler Cloudflare per DNS-over-HTTPS.
"""
import asyncio
import json
import socket
import time
import urllib.parse
import urllib.request

from aiohttp.abc import AbstractResolver
from aiohttp.resolver import ThreadedResolver

DOH_URL = "https://1.1.1.1/dns-query?name={}&type=A"
DOH_TIMEOUT = 5
WAIT_STEP = 1.5


def doh_lookup(host):
    request = urllib.request.Request(DOH_URL.format(urllib.parse.quote(host)), headers={"Accept": "application/dns-json"})
    with urllib.request.urlopen(request, timeout=DOH_TIMEOUT) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return [a["data"] for a in data.get("Answer") or [] if a.get("type") == 1 and a.get("data")]


async def wait_until_resolvable(host, timeout):
    end = time.time() + timeout
    while time.time() < end:
        try:
            if await asyncio.to_thread(doh_lookup, host):
                return True
        except (OSError, ValueError):
            pass
        await asyncio.sleep(WAIT_STEP)
    return False


class FallbackResolver(AbstractResolver):
    def __init__(self):
        self.system = ThreadedResolver()

    async def resolve(self, host, port=0, family=socket.AF_INET):
        try:
            return await self.system.resolve(host, port, family)
        except OSError:
            addresses = await asyncio.to_thread(doh_lookup, host)
            if not addresses:
                raise
            return [{"hostname": host, "host": ip, "port": port, "family": socket.AF_INET, "proto": 0,
                     "flags": socket.AI_NUMERICHOST} for ip in addresses]

    async def close(self):
        await self.system.close()
