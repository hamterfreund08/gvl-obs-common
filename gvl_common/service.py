"""Bausteine fuer den lokalen aiohttp-Dienst: Schutz der Routen, Live-Kanal zum Dock und JSON-Eingang."""
import asyncio
import json

from aiohttp import web

MAX_CLIENTS = 8
PING_EVERY = 15
QUEUE_SIZE = 64


def make_guard(host, port, secret):
    """Ueber den Tunnel ist nur /in/<geheimnis>/* erreichbar, lokal alles andere. secret ist eine Funktion."""
    local_hosts = (f"{host}:{port}", f"localhost:{port}")
    local_origins = (f"http://{host}:{port}", f"http://localhost:{port}", "null")

    @web.middleware
    async def guard(request, handler):
        tunneled = "Cf-Ray" in request.headers or "Cf-Connecting-Ip" in request.headers
        inbound = request.path.startswith("/in/")
        if tunneled != inbound or (tunneled and request.match_info.get("secret") != secret()):
            raise web.HTTPNotFound()
        if not tunneled:
            origin = request.headers.get("Origin")
            if request.host not in local_hosts or (origin and origin not in local_origins):
                raise web.HTTPForbidden()
        return await handler(request)

    return guard


async def body_of(request):
    try:
        data = await request.json()
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def encode(data):
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


class Hub:
    """Server-Sent Events an Dock und Overlay."""

    def __init__(self, max_clients=MAX_CLIENTS):
        self.clients = set()
        self.max_clients = max_clients

    def send(self, data):
        text = encode(data)
        for queue in list(self.clients):
            try:
                queue.put_nowait(text)
            except asyncio.QueueFull:
                self.clients.discard(queue)

    def close(self):
        for queue in list(self.clients):
            try:
                queue.put_nowait(None)
            except asyncio.QueueFull:
                pass

    async def stream(self, request, first):
        if len(self.clients) >= self.max_clients:
            return web.json_response({"ok": False}, status=429)
        response = web.StreamResponse(headers={"Content-Type": "text/event-stream", "Cache-Control": "no-cache"})
        await response.prepare(request)
        queue = asyncio.Queue(QUEUE_SIZE)
        self.clients.add(queue)
        queue.put_nowait(encode(first))
        try:
            while True:
                try:
                    text = await asyncio.wait_for(queue.get(), PING_EVERY)
                except asyncio.TimeoutError:
                    await response.write(b": ping\n\n")
                    continue
                if text is None:
                    break
                await response.write(f"data: {text}\n\n".encode("utf-8"))
        except (ConnectionResetError, asyncio.CancelledError):
            pass
        finally:
            self.clients.discard(queue)
        return response
