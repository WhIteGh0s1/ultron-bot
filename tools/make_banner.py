"""Баннеры меню Альтрона в стиле постера: тёмный фон, светящийся стеклянный цветок (свечение, блики, тычинки),
заголовок капсом шрифтом с завитушками (Kudry Weird Headline), мелкие подписи, тонкая линия.
Запуск: .venv\\Scripts\\python -X utf8 tools\\make_banner.py  → assets/banners/*.png"""
import math
import random
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent.parent
FONTS = ROOT / "assets" / "fonts"
OUT = ROOT / "assets" / "banners"
W, H = 1280, 720
SS = 2  # суперсэмплинг для гладких линий

BANNERS = {  # ключ: (заголовок, номер, подпись под линией, подпись внизу)
    "home": ("АЛЬТРОН", "01 / 08", ["правая рука", "старосты"], ["помнит всё, шутит чёрно,", "пишет отчёты за тебя"]),
    "chat": ("НАСТРОЙКИ", "02 / 08", ["как он ведёт", "себя в чате"], ["шанс влезть в разговор,", "режим копирования"]),
    "persona": ("ХАРАКТЕР", "03 / 08", ["кто он", "такой"], ["дерзкий, чёрный юмор,", "держит позицию"]),
    "rules": ("ПРАВИЛА", "04 / 08", ["что выполнять", "всегда"], ["«если много пишут —", "пиши: тише»"]),
    "notes": ("ЗАМЕТКИ", "05 / 08", ["что помнить", "о группе"], ["пары, дедлайны,", "кто за что отвечает"]),
    "rem": ("НАПОМИНАНИЯ", "06 / 08", ["чтобы никто", "не проспал"], ["«альтрон напомни", "завтра в 8:30»"]),
    "people": ("ЛЮДИ", "07 / 08", ["кого он", "знает"], ["факты, привычки,", "кто кому должен"]),
    "stats": ("СТАТИСТИКА", "08 / 08", ["кто тут самый", "болтливый"], ["сообщения, топ,", "активность за сутки"]),
}

INK = (246, 232, 238)       # почти белый с розовым
ACCENT = (255, 70, 90)     # акцентный красно-розовый
SOFT = (255, 150, 160)      # мелкий текст


def font(name: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONTS / name), size)


# ---------- фон ----------
def background() -> np.ndarray:
    y, x = np.mgrid[0:H, 0:W].astype(np.float32)
    base = np.zeros((H, W, 3), np.float32)
    base[:] = (7, 2, 4)
    for cx, cy, r, col in ((W * 0.28, H * 0.42, 620, (70, 8, 20)), (W * 0.82, H * 0.86, 760, (120, 10, 32))):
        d = np.sqrt((x - cx) ** 2 + (y - cy) ** 2) / r
        base += np.clip(1 - d, 0, 1)[..., None] ** 2 * np.array(col, np.float32)
    return base


# ---------- стеклянный цветок ----------
def petal_poly(cx, cy, ang, length, width, bend, n=60):
    left, right = [], []
    for i in range(n + 1):
        t = i / n
        w = width * math.sin(math.pi * t) ** 0.85 * (1 - 0.25 * t)
        px, py = length * t, bend * math.sin(math.pi * t) * length * 0.18
        for sign, pts in ((1, left), (-1, right)):
            qx, qy = px, py + sign * w
            pts.append(((cx + qx * math.cos(ang) - qy * math.sin(ang)) * SS,
                        (cy + qx * math.sin(ang) + qy * math.cos(ang)) * SS))
    return left + right[::-1]


def layer():
    im = Image.new("L", (W * SS, H * SS), 0)
    return im, ImageDraw.Draw(im)


def to_arr(im: Image.Image, blur: float = 0) -> np.ndarray:
    im = im.resize((W, H), Image.LANCZOS)
    if blur:
        im = im.filter(ImageFilter.GaussianBlur(blur))
    return np.asarray(im, np.float32) / 255


def flower(rng: random.Random) -> np.ndarray:
    cx, cy = W * 0.80, H * 0.80
    fill_im, fill_d = layer()
    edge_im, edge_d = layer()
    core_im, core_d = layer()
    for a in (-2.55, -1.95, -1.25, -0.55, 0.25, 2.75, 3.6):
        a += rng.uniform(-0.12, 0.12)
        length, width = rng.uniform(430, 560), rng.uniform(85, 125)
        poly = petal_poly(cx, cy, a, length, width, rng.uniform(-0.6, 0.6))
        fill_d.polygon(poly, fill=95)
        edge_d.line(poly + [poly[0]], fill=255, width=3 * SS, joint="curve")
        mid = [((cx + length * t * math.cos(a)) * SS, (cy + length * t * math.sin(a)) * SS) for t in (0.08, 0.5, 0.85)]
        edge_d.line(mid, fill=150, width=2 * SS)
    for _ in range(11):  # тычинки
        a, ln = rng.uniform(-2.9, -0.2), rng.uniform(150, 290)
        ex, ey = cx + ln * math.cos(a), cy + ln * math.sin(a)
        core_d.line([(cx * SS, cy * SS), (ex * SS, ey * SS)], fill=230, width=3 * SS)
        r = rng.uniform(7, 12)
        core_d.ellipse(((ex - r * 1.6) * SS, (ey - r) * SS, (ex + r * 1.6) * SS, (ey + r) * SS), fill=255)
    core_d.ellipse(((cx - 34) * SS, (cy - 34) * SS, (cx + 34) * SS, (cy + 34) * SS), fill=200)

    fill, edge, core = to_arr(fill_im, 2), to_arr(edge_im), to_arr(core_im)
    y, x = np.mgrid[0:H, 0:W].astype(np.float32)
    dist = np.clip(np.sqrt((x - cx) ** 2 + (y - cy) ** 2) / 560, 0, 1)[..., None]
    glass = (1 - dist) * np.array((255, 70, 96), np.float32) + dist * np.array((175, 10, 26), np.float32)
    out = fill[..., None] * glass * (1.2 - dist * 0.6)
    out += edge[..., None] * np.array((255, 178, 186), np.float32) * 0.9
    out += to_arr(edge_im, 6)[..., None] * np.array((255, 40, 70), np.float32) * 1.4
    out += core[..., None] * np.array((255, 110, 130), np.float32) * 0.8
    bright = Image.fromarray(np.clip(out, 0, 255).astype(np.uint8))
    for r, k in ((18, 0.45), (60, 0.4), (140, 0.35)):  # свечение
        out += np.asarray(bright.filter(ImageFilter.GaussianBlur(r)), np.float32) * k
    return out


# ---------- текст ----------
def asterisk(d: ImageDraw.ImageDraw, x: float, y: float, r: float):
    for i in range(6):
        a = math.pi / 3 * i + math.pi / 2
        d.line((x * SS, y * SS, (x + r * math.cos(a)) * SS, (y + r * math.sin(a)) * SS), fill=INK, width=7 * SS)
    d.ellipse(((x - 5) * SS, (y - 5) * SS, (x + 5) * SS, (y + 5) * SS), fill=INK)


def text_layer(title: str, num: str, top: list[str], foot: list[str]) -> Image.Image:
    im = Image.new("RGBA", (W * SS, H * SS), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    small = font("Inter-Bold.otf", 30 * SS)
    d.text((56 * SS, 44 * SS), "альтрон", font=small, fill=INK)
    w = d.textbbox((0, 0), "староста", font=small)[2]
    d.text(((W - 56) * SS - w, 44 * SS), "староста", font=small, fill=INK)
    asterisk(d, W / 2, 62, 24)
    size = 230
    while True:
        f = font("kudry_weird-headline.otf", size * SS)
        bb = d.textbbox((0, 0), title, font=f)
        if bb[2] - bb[0] <= (W - 112) * SS or size <= 60:
            break
        size -= 6
    d.text((56 * SS - bb[0], 128 * SS - bb[1]), title, font=f, fill=INK)
    title_bottom = 128 + (bb[3] - bb[1]) / SS
    nf = font("benzin-bold.otf", 34 * SS)
    nw = d.textbbox((0, 0), num, font=nf)[2]
    d.text(((W - 56) * SS - nw, 100 * SS), num, font=nf, fill=ACCENT)
    ly = title_bottom + 34
    d.line((56 * SS, ly * SS, 520 * SS, ly * SS), fill=INK, width=3 * SS)
    qf = font("NauryzRedKeds.ttf", 28 * SS)
    for i, line in enumerate(top):
        d.text((56 * SS, (ly + 26 + i * 36) * SS), line, font=qf, fill=SOFT)
    for i, line in enumerate(foot):
        d.text((56 * SS, (H - 60 - (len(foot) - i) * 36) * SS), line, font=qf, fill=SOFT)
    return im.resize((W, H), Image.LANCZOS)


def make(key: str, seed: int) -> Image.Image:
    title, num, top, foot = BANNERS[key]
    arr = background() + flower(random.Random(seed))
    arr += np.random.default_rng(seed).normal(0, 7, (H, W, 1)).astype(np.float32)  # зерно
    img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8)).convert("RGBA")
    img.alpha_composite(text_layer(title, num, top, foot))
    return img.convert("RGB")


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    for i, key in enumerate(BANNERS):
        make(key, 7 + i * 13).save(OUT / f"{key}.png", optimize=True)
        print(OUT / f"{key}.png")
