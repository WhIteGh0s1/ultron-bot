"""Каталог стикеров для Альтрона: эмодзи у стикеров в паках не совпадают со смыслом,
поэтому каждый стикер «смотрит» модель с картинками и подписывает: настроение + что на нём.
Запуск: .venv\\Scripts\\python -X utf8 tools\\build_stickers.py ПАК1 ПАК2 ...  → assets/stickers.json"""
import asyncio
import base64
import io
import json
import re
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import bot as B  # noqa: E402

OUT = ROOT / "assets" / "stickers.json"
COLS, ROWS, CELL = 6, 4, 200
MOODS = B.STICKER_MOODS
VISION = sys.argv[sys.argv.index("--model") + 1] if "--model" in sys.argv else "gpt-6.2-sol"


def sheet(images: list[Image.Image], start: int) -> bytes:
    canvas = Image.new("RGB", (COLS * CELL, ROWS * CELL), "white")
    d = ImageDraw.Draw(canvas)
    f = ImageFont.truetype("arialbd.ttf", 28)
    for i, im in enumerate(images):
        x, y = (i % COLS) * CELL, (i // COLS) * CELL
        im = im.convert("RGBA")
        im.thumbnail((CELL - 30, CELL - 40))
        bg = Image.new("RGBA", im.size, (255, 255, 255, 255))
        bg.alpha_composite(im)
        canvas.paste(bg.convert("RGB"), (x + (CELL - im.width) // 2, y + 34))
        d.rectangle((x, y, x + CELL - 1, y + CELL - 1), outline=(200, 200, 200))
        d.text((x + 8, y + 4), str(start + i), fill=(220, 0, 40), font=f)
    buf = io.BytesIO()
    canvas.save(buf, "JPEG", quality=88)
    return buf.getvalue()


async def describe(jpg: bytes, nums: list[int]) -> dict:
    prompt = (f"Это сетка стикеров из Telegram, у каждого красный номер ({nums[0]}–{nums[-1]}). Для КАЖДОГО номера определи, "
              f"в какой ситуации в чате его кидают. Ответ — только JSON вида "
              '{"12": {"mood": "...", "desc": "..."}}. mood — РОВНО одно слово из списка: ' + ", ".join(MOODS) +
              ". desc — 3–9 слов по-русски: кто/что на стикере и надпись на нём, если есть.")
    for attempt in range(4):
        try:
            r = await B.llm.chat.completions.create(model=VISION, max_tokens=3000, messages=[{"role": "user", "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(jpg).decode()}}]}])
            raw = r.choices[0].message.content or ""
            return json.loads(re.search(r"\{.*\}", raw, re.S).group(0))
        except Exception as e:
            print("  повтор:", str(e)[:100])
            await asyncio.sleep(10 * (attempt + 1))
    return {}


async def main(packs: list[str]):
    catalog = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else []
    known = {c["uid"] for c in catalog}
    for name in packs:
        pack = await B.bot.get_sticker_set(name)
        todo = [s for s in pack.stickers if s.file_unique_id not in known]
        print(f"{name}: {len(pack.stickers)} стикеров, новых {len(todo)}")
        per = COLS * ROWS
        for k in range(0, len(todo), per):
            part = todo[k:k + per]
            imgs = []
            for s in part:
                src = s.thumbnail.file_id if (s.is_video or s.is_animated) and s.thumbnail else s.file_id
                imgs.append(Image.open(await B.bot.download(src)))
            nums = list(range(1, len(part) + 1))
            got = await describe(sheet(imgs, 1), nums)
            for n, s in zip(nums, part):
                info = got.get(str(n)) or {}
                mood = info.get("mood", "").strip().lower()
                catalog.append({"uid": s.file_unique_id, "file_id": s.file_id, "set": name, "emoji": s.emoji or "",
                                "mood": mood if mood in MOODS else "", "desc": info.get("desc", "").strip()})
            print(f"  {k + len(part)}/{len(todo)}: " + ", ".join(f"{c['mood']}" for c in catalog[-len(part):])[:200])
            OUT.write_text(json.dumps(catalog, ensure_ascii=False, indent=0), encoding="utf-8")
    await B.bot.session.close()
    print("готово:", len(catalog), "стикеров →", OUT)


if __name__ == "__main__":
    asyncio.run(main([a for a in sys.argv[1:] if not a.startswith("--") and a != VISION]))
