"""Баннеры меню (как разделы у Ghostlink, но в красной гамме Альтрона):
чёрный угол слева сверху → глубокий красный → розовое свечение справа снизу, зерно, Benzin + NauryzRedKeds.
Запуск: .venv\\Scripts\\python -X utf8 tools\\make_banner.py  → assets/banners/*.png"""
import os
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont, ImageOps

FONTS = Path(os.environ["LOCALAPPDATA"]) / "Microsoft/Windows/Fonts"
OUT = Path(__file__).resolve().parent.parent / "assets" / "banners"
W, H = 1280, 720

BANNERS = {
    "home": ("Альтрон", "ПРАВАЯ РУКА СТАРОСТЫ"),
    "chat": ("Настройки", "КАК ОН ВЕДЁТ СЕБЯ В ЧАТЕ"),
    "persona": ("Характер", "КТО ОН ТАКОЙ"),
    "rules": ("Правила", "ЧТО ВЫПОЛНЯТЬ ВСЕГДА"),
    "notes": ("Заметки", "ЧТО ПОМНИТЬ О ГРУППЕ"),
    "rem": ("Напоминания", "ЧТОБЫ НИКТО НЕ ПРОСПАЛ"),
    "people": ("Люди", "КОГО ОН ЗНАЕТ"),
    "stats": ("Статистика", "КТО ТУТ САМЫЙ БОЛТЛИВЫЙ"),
}


def background() -> Image.Image:
    # диагональный градиент: чёрный левый верх → глубокий красный → правый низ
    gy = Image.linear_gradient("L").resize((W, H))
    gx = Image.linear_gradient("L").rotate(90).resize((W, H))
    grad = Image.blend(gx, gy, 0.38).point(lambda v: int(255 * (v / 255) ** 1.7))
    img = ImageOps.colorize(grad, black=(5, 1, 2), mid=(120, 12, 16), white=(206, 30, 38), midpoint=95)
    # розово-красное свечение справа снизу, как на референсе
    glow = Image.new("L", (W, H), 0)
    ImageDraw.Draw(glow).ellipse((W - 420, H - 300, W + 420, H + 420), fill=255)
    glow = glow.filter(ImageFilter.GaussianBlur(170))
    img = Image.composite(Image.new("RGB", (W, H), (236, 92, 112)), img, glow.point(lambda v: int(v * 0.75)))
    # тонкий световой след (как от реактивного ранца на референсе)
    beam = Image.new("L", (W, H), 0)
    ImageDraw.Draw(beam).line((W * 0.05, H * 0.08, W * 0.62, H * 0.52), fill=70, width=26)
    beam = beam.filter(ImageFilter.GaussianBlur(28))
    img = ImageChops.add(img, Image.merge("RGB", (beam, beam.point(lambda v: v // 3), beam.point(lambda v: v // 3))))
    # зерно
    noise = Image.effect_noise((W, H), 22).convert("RGB")
    return Image.blend(img, noise, 0.045)


def fit(text: str, path: Path, size: int, max_w: int) -> ImageFont.FreeTypeFont:
    while size > 20:
        f = ImageFont.truetype(str(path), size)
        if f.getbbox(text)[2] <= max_w:
            return f
        size -= 4
    return ImageFont.truetype(str(path), size)


def make(title: str, tagline: str) -> Image.Image:
    img = background()
    d = ImageDraw.Draw(img)
    benzin = FONTS / "benzin-bold(1).otf"
    quirk = FONTS / "NauryzRedKeds.ttf"

    def center(text, font, y):
        w = d.textbbox((0, 0), text, font=font)[2]
        d.text(((W - w) / 2, y), text, font=font, fill="white")

    center("Альтрон", ImageFont.truetype(str(benzin), 30), 62)
    big = fit(title, benzin, 150, 1120)
    top, bottom = big.getbbox(title)[1], big.getbbox(title)[3]
    y = 300 - (top + bottom) / 2
    center(title, big, y)
    center(tagline, fit(tagline, quirk, 36, 1000), y + bottom + 40)
    return img


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    for key, (title, tag) in BANNERS.items():
        make(title, tag).save(OUT / f"{key}.png", optimize=True)
        print(OUT / f"{key}.png")
