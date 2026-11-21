"""Мемные штуки Альтрона: звуки (MyInstants → голосовое), мемы по шаблонам (Imgflip + подписи),
кубики Telegram, гифки (Giphy, если задан GIPHY_KEY). Ключи не нужны, кроме гифок."""
import asyncio
import io
import logging
import os
import random
import re
import shutil
import subprocess
import tempfile
import textwrap
from pathlib import Path

import aiohttp
from PIL import Image, ImageDraw, ImageFont

log = logging.getLogger("ultron.fun")
UA = {"User-Agent": "Mozilla/5.0 (AltronBot; +https://github.com/WhIteGh0s1/ultron-bot)"}
GIPHY_KEY = os.environ.get("GIPHY_KEY", "")
DICE = {"🎲", "🎯", "🏀", "⚽", "🎳", "🎰"}
_templates: list[dict] = []

# хорошие шаблоны: имя → как раскладывать подписи (по умолчанию верх/низ)
LAYOUT = {
    "Drake Hotline Bling": [(0.5, 0.0, 1.0, 0.5), (0.5, 0.5, 1.0, 1.0)],
    "Two Buttons": [(0.05, 0.08, 0.45, 0.25), (0.45, 0.02, 0.85, 0.2), (0.0, 0.75, 1.0, 1.0)],
    "Distracted Boyfriend": [(0.05, 0.55, 0.45, 0.8), (0.45, 0.35, 0.7, 0.6), (0.68, 0.45, 1.0, 0.7)],
    "Gru's Plan": [(0.25, 0.05, 0.5, 0.45), (0.75, 0.05, 1.0, 0.45), (0.25, 0.55, 0.5, 0.95), (0.75, 0.55, 1.0, 0.95)],
    "Left Exit 12 Off Ramp": [(0.2, 0.0, 0.5, 0.3), (0.5, 0.0, 0.85, 0.3), (0.3, 0.7, 0.8, 1.0)],
}


async def _get(url: str, **kw):
    async with aiohttp.ClientSession(headers=UA, timeout=aiohttp.ClientTimeout(total=20)) as http:
        async with http.get(url, **kw) as r:
            r.raise_for_status()
            if "json" in r.headers.get("Content-Type", ""):
                return await r.json()
            return await r.read()


# ---------- звуки ----------
async def find_sound(query: str) -> tuple[str, str] | None:
    """(название, mp3-ссылка) самого подходящего звука с MyInstants."""
    data = await _get("https://www.myinstants.com/api/v1/instants/", params={"format": "json", "name": query})
    res = (data or {}).get("results", [])[:8]
    if not res:
        return None
    q = query.lower()
    res.sort(key=lambda x: (q not in x["name"].lower(), len(x["name"])))
    return res[0]["name"], res[0]["sound"]


def to_voice(mp3: bytes) -> bytes:
    """mp3 → ogg/opus для голосового (до 15 секунд)."""
    ff = shutil.which("ffmpeg")
    if not ff:
        raise RuntimeError("нет ffmpeg")
    with tempfile.TemporaryDirectory() as d:
        src, dst = Path(d) / "in.mp3", Path(d) / "out.ogg"
        src.write_bytes(mp3)
        subprocess.run([ff, "-y", "-loglevel", "error", "-i", str(src), "-t", "15", "-ac", "1", "-c:a", "libopus",
                        "-b:a", "48k", str(dst)], check=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return dst.read_bytes()


async def sound(query: str) -> tuple[str, bytes] | None:
    hit = await find_sound(query)
    if not hit:
        return None
    mp3 = await _get(hit[1])
    if len(mp3) > 3_000_000:
        return None
    return hit[0], await asyncio.to_thread(to_voice, mp3)


# ---------- мемы по шаблонам ----------
async def templates() -> list[dict]:
    global _templates
    if not _templates:
        data = await _get("https://api.imgflip.com/get_memes")
        _templates = data["data"]["memes"]
    return _templates


def template_names(n: int = 40) -> str:
    return ", ".join(t["name"] for t in _templates[:n]) if _templates else ", ".join(LAYOUT)


def _font(size: int) -> ImageFont.FreeTypeFont:
    for f in ("impact.ttf", "Impact.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "arialbd.ttf",
              "DejaVuSans-Bold.ttf"):
        try:
            return ImageFont.truetype(f, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _draw_box(img: Image.Image, text: str, box: tuple[float, float, float, float], top: bool):
    W, H = img.size
    x0, y0, x1, y1 = box[0] * W, box[1] * H, box[2] * W, box[3] * H
    bw, bh = x1 - x0, y1 - y0
    d = ImageDraw.Draw(img)
    text = text.upper().strip()
    size = int(min(bh * 0.45, W / 9))
    while size > 12:
        f = _font(size)
        chars = max(6, int(bw / (size * 0.55)))
        lines = textwrap.wrap(text, chars) or [""]
        lh = size * 1.1
        if len(lines) * lh <= bh * 0.95 and max(d.textlength(line, font=f) for line in lines) <= bw * 0.96:
            break
        size -= 2
    total = len(lines) * lh
    y = y0 + (bh * 0.04 if top else bh - total - bh * 0.04) if len(LAYOUT) and box in ((0, 0, 1, .3), (0, .7, 1, 1)) \
        else y0 + (bh - total) / 2
    for line in lines:
        w = d.textlength(line, font=f)
        d.text((x0 + (bw - w) / 2, y), line, font=f, fill="white", stroke_width=max(2, size // 14), stroke_fill="black")
        y += lh


async def meme(template: str, texts: list[str]) -> tuple[str, bytes] | None:
    tl = await templates()
    q = template.lower()
    pick = next((t for t in tl if t["name"].lower() == q), None) or \
        next((t for t in tl if q in t["name"].lower() or t["name"].lower() in q), None)
    if not pick:
        words = set(re.findall(r"\w+", q))
        pick = max(tl, key=lambda t: len(words & set(re.findall(r"\w+", t["name"].lower()))), default=None)
    if not pick:
        return None
    img = Image.open(io.BytesIO(await _get(pick["url"]))).convert("RGB")
    if max(img.size) > 1000:
        img.thumbnail((1000, 1000))
    texts = [t for t in texts if t and t.strip()]
    boxes = LAYOUT.get(pick["name"]) or [(0, 0, 1, 0.3), (0, 0.7, 1, 1)]
    if len(texts) == 1 and pick["name"] not in LAYOUT:
        boxes = [(0, 0.7, 1, 1)]
    for i, (t, box) in enumerate(zip(texts, boxes)):
        _draw_box(img, t, box, top=(i == 0))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=90)
    return pick["name"], buf.getvalue()


# ---------- гифки ----------
async def gif(query: str) -> str | None:
    if not GIPHY_KEY:
        return None
    data = await _get("https://api.giphy.com/v1/gifs/search", params={"api_key": GIPHY_KEY, "q": query, "limit": "10",
                                                                       "rating": "r", "lang": "ru"})
    items = (data or {}).get("data", [])
    return random.choice(items)["images"]["original"]["mp4"] if items else None
