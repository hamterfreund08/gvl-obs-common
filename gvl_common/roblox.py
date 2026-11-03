"""Wappen und Avatare ueber die Roblox-Thumbnail-API, mit Zwischenspeicher."""
import asyncio
import time

import aiohttp

ASSETS = "https://thumbnails.roblox.com/v1/assets?assetIds={}&size=420x420&format=Png&isCircular=false"
AVATARS = "https://thumbnails.roblox.com/v1/users/avatar?userIds={}&size=720x720&format=Png&isCircular=false"
TEMPLATES = {"logo": ASSETS, "avatar": AVATARS}
CACHE_SEC = 6 * 3600
BATCH = 50
ATTEMPTS = 4
PENDING_WAIT = 1.5


def digits(value):
    return "".join(c for c in str(value or "") if c.isdigit())


class Thumbs:
    def __init__(self):
        self.cache = {}

    def get(self, kind, value):
        entry = self.cache.get(f"{kind}:{digits(value)}")
        return entry[1] if entry and time.time() - entry[0] < CACHE_SEC else None

    async def fetch(self, http, kind, ids):
        pending = sorted(i for i in {digits(i) for i in ids} - {"", "0"} if not self.get(kind, i))
        for start in range(0, len(pending), BATCH):
            batch = pending[start:start + BATCH]
            for _ in range(ATTEMPTS):
                async with http.get(TEMPLATES[kind].format(",".join(batch))) as resp:
                    data = (await resp.json(content_type=None)).get("data") or []
                waiting = False
                for row in data:
                    if row.get("state") == "Completed" and row.get("imageUrl"):
                        self.cache[f"{kind}:{row.get('targetId')}"] = (time.time(), row["imageUrl"])
                    elif row.get("state") == "Pending":
                        waiting = True
                if not waiting:
                    break
                await asyncio.sleep(PENDING_WAIT)

    async def fetch_quietly(self, http, kind, ids):
        try:
            await self.fetch(http, kind, ids)
            return True
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as e:
            print(f"Thumbnails nicht geladen: {e}", flush=True)
            return False
