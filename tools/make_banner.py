"""Баннер меню в стиле Ghostlink: чёрный фон, мягкий серый свет слева снизу, Benzin + NauryzRedKeds."""
import os, sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter, ImageFont

FONTS = Path(os.environ["LOCALAPPDATA"]) / "Microsoft/Windows/Fonts"
OUT = Path(__file__).resolve().parent.parent / "assets" / "banner.png"
W, H = 1280, 720

img = Image.new("RGB", (W, H), (6, 6, 7))
glow = Image.new("L", (W, H), 0)
g = ImageDraw.Draw(glow)
g.ellipse((-520, 260, 520, 1180), fill=150)          # свет слева снизу
g.ellipse((900, -380, 1600, 260), fill=28)           # еле заметный блик справа сверху
glow = glow.filter(ImageFilter.GaussianBlur(190))
img = Image.composite(Image.new("RGB", (W, H), (150, 150, 155)), img, glow)
noise = Image.effect_noise((W, H), 10).convert("RGB")  # зерно против полос градиента
img = Image.blend(img, noise, 0.035)

d = ImageDraw.Draw(img)
benzin = lambda s: ImageFont.truetype(str(FONTS / "benzin-bold(1).otf"), s)
quirk = ImageFont.truetype(str(FONTS / "NauryzRedKeds.ttf"), 36)

def center(text, font, y, fill="white"):
    w = d.textbbox((0, 0), text, font=font)[2]
    d.text(((W - w) / 2, y), text, font=font, fill=fill)

center("Альтрон", benzin(30), 62)
center("Альтрон", benzin(150), 230)
center("ПРАВАЯ РУКА СТАРОСТЫ", quirk, 425)
OUT.parent.mkdir(exist_ok=True)
img.save(OUT)
print(OUT)
