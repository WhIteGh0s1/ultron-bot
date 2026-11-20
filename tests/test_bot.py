"""Автотесты Альтрона без настоящего Telegram: фейковая сессия Bot API записывает все вызовы,
модель подменена сценариями. Запуск:  .venv\\Scripts\\python -X utf8 tests\\test_bot.py"""
import asyncio
import io
import os
import subprocess
import sys
import tempfile
import time
import traceback
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="altron-test-"))
os.environ.update(BOT_TOKEN="123456:TEST", OWNER_IDS="1000001", ALLOWED_CHATS="", ACTIVE_CHANCE="0", COOLDOWN="0",
                  DATA_DIR=str(TMP), DB_PATH=str(TMP / "test.db"), MEMORY_REPO="", AUTO_UPDATE="0", LLM_API_KEY="test")
sys.path.insert(0, str(ROOT))

from aiogram.client.session.base import BaseSession  # noqa: E402
from aiogram.types import Chat, ChatMemberMember, Message, MessageId, PhotoSize, Update, User  # noqa: E402

import bot as B  # noqa: E402
import menu as M  # noqa: E402

OWNER, GROUP = 1000001, -100500
BOT_USER = User(id=9235003238, is_bot=True, first_name="Альтрон", username="Ultron_bad_robot", can_read_all_group_messages=True)


class FakeSession(BaseSession):
    def __init__(self):
        super().__init__()
        self.calls, self.mid = [], 5000

    async def close(self):
        pass

    async def stream_content(self, *a, **k):
        yield b""

    async def make_request(self, bot, method, timeout=None):
        self.calls.append(method)
        name = type(method).__name__
        if name == "GetMe":
            return BOT_USER
        if name == "GetChatMember":
            return ChatMemberMember(user=User(id=method.user_id, is_bot=False, first_name="x"), status="member")
        if name == "CopyMessage":
            self.mid += 1
            return MessageId(message_id=self.mid)
        if name.startswith("Send") and name != "SendChatAction" or name == "ForwardMessage":
            self.mid += 1
            extra = {}
            if name == "SendPhoto":
                extra["photo"] = [PhotoSize(file_id="BANNER_FID", file_unique_id="b", width=1280, height=720)]
            return Message(message_id=self.mid, date=datetime.now(), from_user=BOT_USER,
                           chat=Chat(id=method.chat_id, type="private" if method.chat_id > 0 else "supergroup", title="ИСП-21"),
                           text=getattr(method, "text", None), caption=getattr(method, "caption", None), **extra)
        return True

    def of(self, name):
        return [c for c in self.calls if type(c).__name__ == name]


S = FakeSession()
B.bot.session = S
B.ME.update(id=BOT_USER.id, username=BOT_USER.username)
SCRIPT: list[list[dict]] = []   # что «модель» ответит на следующие вызовы
PROMPTS: list[str] = []


async def fake_think(prompt):
    PROMPTS.append(prompt)
    return SCRIPT.pop(0) if SCRIPT else [{"type": "ignore"}]

B.think = fake_think


class FakeLLM:  # для зрения
    class chat:
        class completions:
            @staticmethod
            async def create(**kw):
                class R:
                    choices = [type("C", (), {"message": type("M", (), {"content": "расписание: 1. базы данных 2. физра"})})]
                return R()

B.llm = FakeLLM()


def make_docx_bytes() -> bytes:
    from docx import Document
    d = Document()
    d.add_paragraph("Лабораторная работа 3. Базы данных")
    d.add_paragraph("Срок сдачи: 28 ноября")
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


async def fake_download(file_id):
    S.calls.append(type("Download", (), {"file_id": file_id})())
    if file_id.startswith("DOC"):
        return io.BytesIO(make_docx_bytes())
    return io.BytesIO(b"\xff\xd8\xff fake jpeg")

B.bot.download = fake_download

UID = {"v": 1}


def upd(**payload):
    UID["v"] += 1
    return Update.model_validate({"update_id": UID["v"], **payload}, context={"bot": B.bot})


def msg(text=None, user=11, name="Дима", chat=GROUP, reply_to=None, photo=False, mid=None):
    UID["v"] += 1
    m = {"message_id": mid or UID["v"], "date": int(time.time()),
         "chat": {"id": chat, "type": "private" if chat > 0 else "supergroup", "title": None if chat > 0 else "ИСП-21"},
         "from": {"id": user, "is_bot": False, "first_name": name}}
    if text is not None:
        m["caption" if photo else "text"] = text
    if photo:
        m["photo"] = [{"file_id": "PHOTO1", "file_unique_id": "p1", "width": 800, "height": 600}]
    if reply_to:
        m["reply_to_message"] = reply_to
    return m


async def feed(**payload):
    await B.dp.feed_update(B.bot, upd(**payload))


def cb(data, user=OWNER):
    return {"id": str(UID["v"]), "from": {"id": user, "is_bot": False, "first_name": "Староста"}, "chat_instance": "x",
            "data": data, "message": {"message_id": 777, "date": int(time.time()), "chat": {"id": user, "type": "private"},
                                      "photo": [{"file_id": "BANNER_FID", "file_unique_id": "b", "width": 1280, "height": 720}]}}


# ---------------- тесты ----------------
async def t_private_stranger():
    await feed(message=msg("привет", user=1, chat=1))
    assert "только в чате" in S.of("SendMessage")[-1].text


async def t_silent_save():
    n = len(PROMPTS)
    await feed(message=msg("всем привет, кто на парах", user=12, name="Катя"))
    assert len(PROMPTS) == n, "без обращения модель не должна вызываться"
    assert B.db.execute("SELECT count(*) FROM messages WHERE text LIKE '%кто на парах%'").fetchone()[0] == 1


async def t_reply():
    SCRIPT.append([{"type": "reply", "text": "Ну привет."}])
    m = msg("альтрон привет")
    await feed(message=m)
    sent = S.of("SendMessage")[-1]
    assert sent.reply_parameters.message_id == m["message_id"]
    assert sent.text == "Ну привет", sent.text  # без точки в конце


async def t_poll():
    SCRIPT.append([{"type": "poll", "question": "Когда шашлыки?", "options": ["сб", "вс"]}])
    await feed(message=msg("альтрон сделай опрос"))
    p = S.of("SendPoll")[-1]
    assert p.question == "Когда шашлыки?" and [o.text if hasattr(o, "text") else o for o in p.options] == ["сб", "вс"]


async def t_admin_only():
    SCRIPT.append([{"type": "pin", "message_id": 5}])
    await feed(message=msg("альтрон закрепи", user=13, name="Саня"))
    assert "админам" in S.of("SendMessage")[-1].text and not S.of("PinChatMessage")
    SCRIPT.append([{"type": "pin", "message_id": 5}])
    await feed(message=msg("альтрон закрепи", user=OWNER, name="Староста"))
    assert S.of("PinChatMessage"), "владельцу закреп разрешён"


async def t_rule_from_chat():
    SCRIPT.append([{"type": "add_rule", "text": "если много пишут — пиши: пишите суть чуть тише"}, {"type": "reply", "text": "принял"}])
    await feed(message=msg("альтрон новое правило: если много пишут пиши пишите суть чуть тише", user=OWNER, name="Староста"))
    assert B.rules(GROUP), "правило должно сохраниться"


async def t_flood():
    now = int(time.time())
    for i in range(B.FLOOD_N):
        B.db.execute("INSERT INTO messages(chat_id,msg_id,user_id,name,text,date) VALUES(?,?,?,?,?,?)",
                     (GROUP, 90000 + i, 11, "Дима", "ахах", now))
    B.db.commit()
    B.last_flood.clear()
    SCRIPT.append([{"type": "send", "text": "пишите суть чуть тише"}])
    await feed(message=msg("лол", user=12, name="Катя"))
    assert "флуд" in PROMPTS[-1] and "пишите суть чуть тише" in PROMPTS[-1]
    assert S.of("SendMessage")[-1].text == "пишите суть чуть тише"


async def t_photo_ignored_without_ask():
    n = len(S.of("Download"))
    await feed(message=msg("смотрите мем", photo=True, user=12, name="Катя"))
    assert len(S.of("Download")) == n, "без просьбы фото не смотрим"


async def t_photo_on_request():
    photo = msg(None, photo=True, user=12, name="Катя")
    await feed(message=photo)
    SCRIPT.append([{"type": "reply", "text": "первой парой базы"}])
    await feed(message=msg("альтрон глянь что на фото", reply_to=photo))
    assert S.of("Download"), "по просьбе фото смотрим"
    assert "[фото: расписание" in PROMPTS[-1]


DOC_MSG: dict = {}


async def t_doc_ignored_without_ask():
    n = len(S.of("Download"))
    m = msg(None, user=12, name="Катя")
    m["caption"] = "вот методичка"
    m["document"] = {"file_id": "DOC1", "file_unique_id": "d1", "file_name": "лаба3.docx",
                     "mime_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}
    await feed(message=m)
    assert len(S.of("Download")) == n, "без просьбы документ не читаем"
    DOC_MSG.update(m)


async def t_doc_read_on_request():
    SCRIPT.append([{"type": "reply", "text": "сдать до 28 ноября"}])
    await feed(message=msg("альтрон прочитай когда сдавать", reply_to=DOC_MSG))
    assert "ДОКУМЕНТ «лаба3.docx»" in PROMPTS[-1] and "Срок сдачи: 28 ноября" in PROMPTS[-1], PROMPTS[-1][-300:]
    # «что в том файле» без реплая — последний документ в чате, уже из кеша
    n = len(S.of("Download"))
    SCRIPT.append([{"type": "reply", "text": "там лаба"}])
    await feed(message=msg("альтрон что в том файле"))
    assert "Срок сдачи" in PROMPTS[-1] and len(S.of("Download")) == n, "второй раз из кеша"


async def t_document():
    SCRIPT.append([{"type": "document", "filename": "Отчёт куратору", "title": "Отчёт", "text": "Сдали:\n- Катя\nНе сдали:\n- Дима"}])
    await feed(message=msg("альтрон сделай отчёт в ворде", user=OWNER, name="Староста"))
    d = S.of("SendDocument")[-1]
    assert d.document.filename == "Отчёт куратору.docx" and len(d.document.data) > 3000


async def t_reminder():
    SCRIPT.append([{"type": "remind", "in_minutes": 0, "text": "первой парой базы"}])
    await feed(message=msg("альтрон напомни", user=OWNER, name="Староста"))
    try:
        await asyncio.wait_for(B.reminder_loop(), 1)
    except asyncio.TimeoutError:
        pass
    assert any((c.text or "").startswith("⏰ первой парой") for c in S.of("SendMessage"))


async def t_sticker_fallback():
    SCRIPT.append([{"type": "sticker", "emoji": "😂"}])
    await feed(message=msg("альтрон ахах"))
    assert S.of("SendMessage")[-1].text == "😂"  # своих стикеров нет — большой эмодзи


async def t_menu_open():
    await feed(message=msg("/menu", user=OWNER, chat=OWNER, name="Староста"))
    r = S.of("SendRichMessage")[-1]
    texts = [x.text for row in r.reply_markup.inline_keyboard for x in row]
    assert r.chat_id == OWNER and r.rich_message.html.startswith('<img src="tg://photo?id=home"/>'), r.rich_message.html[:80]
    assert r.rich_message.media[0].id == "home" and "<footer>" in r.rich_message.html
    assert texts[0] == "⚙️ Настройки" and texts[-1] == "☁️ Сохранить в GitHub", texts


async def t_menu_navigation():
    for data, key in (("m:chat", "chat"), ("m:act", "chat"), ("m:ch:0.35", "chat"), ("m:mode", "chat"), ("m:rules", "rules"),
                      ("m:notes", "notes"), ("m:rem", "rem"), ("m:persona", "persona"), ("m:people", "people"),
                      ("m:person:11", "people"), ("m:stats", "stats"), ("m:home", "home")):
        n = len(S.of("EditMessageText"))
        await feed(callback_query=cb(data))
        assert len(S.of("EditMessageText")) == n + 1, data
        rich = S.of("EditMessageText")[-1].rich_message
        assert rich.html.startswith(f'<img src="tg://photo?id={key}"/>') and rich.media[0].id == key, (data, rich.html[:60])
        assert len(rich.html) < 32768
    assert B.chance(GROUP) == 0.35 and B.setting(GROUP, "active") is False


async def t_menu_input():
    await feed(callback_query=cb("m:addnotes"))
    await feed(message=msg("лаба 3 по базам до пятницы", user=OWNER, chat=OWNER, name="Староста"))
    assert any("лаба 3" in t for _, t in B.notes(GROUP))
    await feed(callback_query=cb("m:setpersona"))
    await feed(message=msg("называй меня шеф", user=OWNER, chat=OWNER, name="Староста"))
    assert B.persona() == "называй меня шеф"


async def t_menu_stranger():
    await feed(callback_query=cb("m:home", user=13))
    assert S.of("AnswerCallbackQuery")[-1].text == "это меню старосты"


async def t_allowed_chats():
    B.ALLOWED_CHATS.add(-1)
    try:
        await feed(message=msg("альтрон привет", chat=-999))
        assert S.of("LeaveChat")[-1].chat_id == -999
    finally:
        B.ALLOWED_CHATS.clear()


async def t_memory_roundtrip():
    repo = TMP / "memrepo"
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "t"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "t@t"], check=True)
    B.MEM = repo
    B.export_memory()
    files = {p.relative_to(repo).as_posix() for p in repo.rglob("*") if ".git" not in p.parts and p.is_file()}
    assert {"people.json", "people.md", "notes.json", "chats.json"} <= files and any(f.endswith(".jsonl") for f in files), files
    assert subprocess.run(["git", "-C", str(repo), "log", "--oneline"], capture_output=True, text=True).stdout.strip()
    # на «новом сервере» с пустой базой история поднимается из репозитория
    import sqlite3
    old, total = B.db, B.db.execute("SELECT count(*) FROM messages").fetchone()[0]
    fresh = sqlite3.connect(":memory:")
    old.backup(fresh)
    for t in ("messages", *B.STATE_TABLES):
        fresh.execute(f"DELETE FROM {t}")
    B.db = fresh
    try:
        B.import_memory()
        assert fresh.execute("SELECT count(*) FROM messages").fetchone()[0] == total
        for t in ("rules", "notes", "settings", "people", "reminders"):  # и всё состояние тоже
            a = old.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
            assert a and fresh.execute(f"SELECT count(*) FROM {t}").fetchone()[0] == a, t
    finally:
        B.db = old


async def main():
    tests = [v for k, v in globals().items() if k.startswith("t_")]
    failed = 0
    for t in tests:
        try:
            await t()
            print(f"  ok   {t.__name__[2:]}")
        except Exception:
            failed += 1
            print(f"  FAIL {t.__name__[2:]}\n" + traceback.format_exc())
    print(f"\n{len(tests) - failed}/{len(tests)} прошло")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    asyncio.run(main())
