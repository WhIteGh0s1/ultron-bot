"""Меню старосты в стиле Ghostlink: у каждого раздела свой баннер, эмодзи прямо в тексте кнопок
(премиум-иконки на кнопках работают только у ботов с юзернеймом с Fragment), на главной — без подписи.
Открывается /menu в личке бота (или в группе — тогда меню придёт в личку)."""
import asyncio
import html
import json
import logging
from datetime import datetime
from pathlib import Path

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import CallbackQuery, FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto, Message

log = logging.getLogger("ultron.menu")
router = Router()
C = None  # модуль бота, задаётся в register()
PENDING: dict[int, tuple[str, int]] = {}  # user_id -> (что ждём, id)
BANNERS = Path(__file__).resolve().parent / "assets" / "banners"
esc = html.escape


def b(text: str, data: str, style: str | None = None) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=data, style=style)


def kb(*rows) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[list(r) for r in rows if r])


BACK = lambda data="m:home": b("◀️ Назад", data)


# ---------- отправка: баннер раздела + подпись + кнопки ----------
def photo(key: str):
    return C.setting(0, f"banner:{key}") or FSInputFile(BANNERS / f"{key}.png")


def remember_photo(key: str, sent) -> None:
    if isinstance(sent, Message) and sent.photo and not C.setting(0, f"banner:{key}"):
        C.set_setting(0, f"banner:{key}", sent.photo[-1].file_id)


async def show(chat_id: int, key: str, caption: str, k: InlineKeyboardMarkup, message_id: int | None = None):
    caption = caption[:1024] or None
    if message_id:
        try:
            sent = await C.bot.edit_message_media(
                chat_id=chat_id, message_id=message_id, reply_markup=k,
                media=InputMediaPhoto(media=photo(key), caption=caption, parse_mode="HTML"))
            remember_photo(key, sent)
            return
        except TelegramBadRequest as e:
            if "not modified" in str(e).lower():
                return
            log.info("не отредактировал меню (%s) — шлю заново", e)
            try:
                await C.bot.delete_message(chat_id, message_id)
            except TelegramBadRequest:
                pass
    sent = await C.bot.send_photo(chat_id, photo(key), caption=caption, reply_markup=k, parse_mode="HTML")
    remember_photo(key, sent)


# ---------- данные ----------
def chats() -> list[tuple[int, str]]:
    return C.db.execute("SELECT chat_id,title FROM chats ORDER BY title").fetchall()


def cur_chat() -> int | None:
    """Чат, который сейчас настраивается в меню."""
    ids = [c for c, _ in chats()]
    cid = C.setting(0, "menu_chat")
    return cid if cid in ids else (ids[0] if ids else None)


def title(cid: int) -> str:
    row = C.db.execute("SELECT title FROM chats WHERE chat_id=?", (cid,)).fetchone()
    return row[0] if row else str(cid)


def when(ts) -> str:
    return datetime.fromtimestamp(ts).strftime("%d.%m %H:%M") if ts else "ещё не было"


def pct(v: float) -> str:
    return f"{round(v * 100)}%"


# ---------- экраны: (баннер, подпись, кнопки) ----------
def scr_home():
    k = kb([b("⚙️ Настройки", "m:chat"), b("😈 Характер", "m:persona", "primary")],
           [b("⚡ Правила", "m:rules"), b("📌 Заметки", "m:notes")],
           [b("⏰ Напоминания", "m:rem"), b("👥 Люди", "m:people")],
           [b(f"💬 Чат: {title(cur_chat())[:24]}", "m:pick")] if len(chats()) > 1 else None,
           [b("📊 Статистика", "m:stats")],
           [b("☁️ Сохранить в GitHub", "m:sync", "success")])
    return "home", "", k


def scr_pick():
    cur = cur_chat()
    return "chat", "<b>Какой чат настраиваем?</b>", kb(
        *[[b(("✅ " if c == cur else "💬 ") + (t or str(c))[:30], f"m:setchat:{c}", "success" if c == cur else None)]
          for c, t in chats()], [BACK()])


def scr_chat(cid: int):
    active = C.setting(cid, "active", True)
    mode = C.setting(cid, "mode", {"mode": "normal"})
    copy = mode.get("mode") == "copy"
    ch = C.chance(cid)
    who = ""
    if copy:
        row = C.db.execute("SELECT name FROM people WHERE user_id=?", (mode.get("user_id", 0),)).fetchone()
        who = f" · {esc(row[0])}" if row else ""
    cap = (f"💬 <b>{esc(title(cid))}</b>\n\n"
           f"Сам влезает в разговор — <b>{'да, ' + pct(ch) if active else 'нет'}</b>\n"
           f"Режим — <b>{'копирование' + who if copy else 'обычный'}</b>\n\n"
           f"<blockquote expandable>Шанс — как часто бот сам вставляет реплику, реакцию или стикер, когда к нему не обращались. "
           f"Копирование — бот пишет твоей манерой, с твоими словечками и опечатками.</blockquote>")
    k = kb([b("✅ Сам влезает: вкл" if active else "⛔ Сам влезает: выкл", "m:act", "success" if active else "danger")],
           [b(("• " if abs(ch - v) < 0.001 else "") + pct(v), f"m:ch:{v}") for v in (0.05, 0.1, 0.2, 0.35, 0.5)],
           [b("🪞 Режим: копирование" if copy else "🗣 Режим: обычный", "m:mode", "primary")],
           [BACK()])
    return "chat", cap, k


def scr_list(cid: int, what: str):
    items = C.rules(cid) if what == "rules" else C.notes(cid)
    hint = ("Выполняются всегда. Можно давать прямо в чате: «альтрон новое правило: …»" if what == "rules"
            else "Факты о группе: пары, дедлайны, кто за что отвечает")
    body = "\n".join(f"<b>{n}.</b> {esc(t)}" for n, (_, t) in enumerate(items, 1)) or "пока пусто"
    cap = f"💬 <b>{esc(title(cid))}</b>\n\n{body}\n\n<i>{hint}</i>"
    if len(cap) > 1000:
        cap = cap[:990] + "…"
    dels = [b(f"🗑 {n}", f"m:del{what}:{i}", "danger") for n, (i, _) in enumerate(items, 1)]
    return what, cap, kb(*[dels[i:i + 4] for i in range(0, len(dels), 4)],
                         [b("➕ Добавить", f"m:add{what}", "success")], [BACK()])


def scr_rem(cid: int):
    rows = C.db.execute("SELECT id,at,text FROM reminders WHERE chat_id=? AND done=0 ORDER BY at", (cid,)).fetchall()
    body = "\n".join(f"<b>{n}.</b> <code>{when(at)}</code> {esc(t)}" for n, (_, at, t) in enumerate(rows, 1)) or "нет запланированных"
    cap = (f"💬 <b>{esc(title(cid))}</b>\n\n{body}\n\n<i>Новые ставятся в чате: «альтрон напомни завтра в 8:30 …»</i>")[:1024]
    dels = [b(f"🗑 {n}", f"m:delrem:{i}", "danger") for n, (i, _, _) in enumerate(rows, 1)]
    return "rem", cap, kb(*[dels[i:i + 4] for i in range(0, len(dels), 4)], [BACK()])


def scr_persona():
    p = C.persona()
    cap = (f"<blockquote>{esc(p) if p else 'ничего не задано — работает базовый: дерзкий, чёрный юмор, мат, держит позицию'}</blockquote>\n"
           f"<i>Свои указания поверх базового, для всех чатов. Например: «больше чёрного юмора», «называй меня шеф»</i>")
    return "persona", cap[:1024], kb([b("✏️ Изменить", "m:setpersona", "success"), b("🗑 Сбросить", "m:resetpersona", "danger")],
                                     [BACK()])


def scr_people(page: int = 0):
    rows = C.db.execute("SELECT user_id,name,facts,msg_count FROM people WHERE user_id!=? ORDER BY msg_count DESC",
                        (C.ME["id"],)).fetchall()
    per = 10
    part = rows[page * per:(page + 1) * per]
    body = "\n".join(f"<b>{esc(n)}</b> · {c} сообщ. · {len(json.loads(f or '[]'))} фактов" for _, n, f, c in part) or "пока никого"
    cap = f"Всего <b>{len(rows)}</b>\n\n{body}"
    btns = [b(f"👤 {n[:18]}", f"m:person:{i}") for i, n, *_ in part]
    nav = ([b("◀️", f"m:people:{page - 1}")] if page > 0 else []) + \
          ([b("▶️", f"m:people:{page + 1}")] if (page + 1) * per < len(rows) else [])
    return "people", cap[:1024], kb(*[btns[i:i + 2] for i in range(0, len(btns), 2)], nav or None, [BACK()])


def scr_person(uid: int):
    row = C.db.execute("SELECT name,username,facts,msg_count,last_seen FROM people WHERE user_id=?", (uid,)).fetchone()
    if not row:
        return scr_people()
    n, u, f, c, ls = row
    facts = json.loads(f or "[]")
    body = "\n".join(f"<b>{k}.</b> {esc(x)}" for k, x in enumerate(facts, 1)) or "ничего"
    cap = (f"👤 <b>{esc(n)}</b>{' · @' + esc(u) if u else ''}\n"
           f"<code>{uid}</code> · {c} сообщ. · был {when(ls)}\n\n<b>Что бот о нём знает</b>\n{body}")[:1024]
    dels = [b(f"🗑 {k}", f"m:delfact:{uid}:{k - 1}", "danger") for k in range(1, len(facts) + 1)]
    return "people", cap, kb(*[dels[i:i + 4] for i in range(0, len(dels), 4)],
                             [b("➕ Добавить факт", f"m:addfact:{uid}", "success")], [BACK("m:people")])


def scr_stats():
    db = C.db
    cid = cur_chat() or 0
    day = int(datetime.now().timestamp()) - 86400
    top = db.execute("SELECT name,count(*) FROM messages WHERE chat_id=? AND user_id!=? GROUP BY user_id "
                     "ORDER BY 2 DESC LIMIT 5", (cid, C.ME["id"])).fetchall()
    medals = ["🥇", "🥈", "🥉", "4.", "5."]
    cap = (f"{'💬 <b>' + esc(title(cid)) + '</b>' if cid else 'Пока ни одного чата'}\n\n"
           f"Сообщений за сутки — <b>{db.execute('SELECT count(*) FROM messages WHERE chat_id=? AND date>=?', (cid, day)).fetchone()[0]}</b>\n"
           f"Всего сообщений — <b>{db.execute('SELECT count(*) FROM messages').fetchone()[0]}</b>\n"
           f"Бот написал — <b>{db.execute('SELECT count(*) FROM messages WHERE user_id=?', (C.ME['id'],)).fetchone()[0]}</b>\n"
           f"Стикеров знает — <b>{db.execute('SELECT count(*) FROM stickers').fetchone()[0]}</b>\n"
           f"GitHub — <b>{when(C.setting(0, 'last_sync'))}</b>\n\n"
           f"<b>Самые болтливые</b>\n" + ("\n".join(f"{medals[i]} {esc(n)} · {c}" for i, (n, c) in enumerate(top)) or "пока никого"))
    return "stats", cap[:1024], kb([BACK()])


PROMPTS = {
    "rules": "Напиши правило одним сообщением. Например: «если много пишут — пиши: пишите суть чуть тише»",
    "notes": "Напиши заметку одним сообщением. Например: «лаба 3 по базам до пятницы»",
    "persona": "Напиши, каким должен быть характер (дополнение к базовому)",
    "fact": "Напиши факт об этом человеке",
}


# ---------- обработчики ----------
def is_owner(uid: int | None) -> bool:
    return bool(uid) and uid in C.OWNER_IDS


async def open_menu(m: Message) -> None:
    if not is_owner(m.from_user and m.from_user.id):
        return
    if m.chat.type == "private":
        await show(m.chat.id, *scr_home())
        return
    C.set_setting(0, "menu_chat", m.chat.id)
    try:
        await show(m.from_user.id, *scr_home())
        await m.reply("меню скинул в личку")
    except (TelegramForbiddenError, TelegramBadRequest):
        await m.reply("нажми Start у меня в личке, потом /menu")


async def on_private(m: Message) -> bool:
    """Ввод текста для меню. True — сообщение обработано."""
    uid = m.from_user.id if m.from_user else 0
    if not is_owner(uid) or uid not in PENDING or not m.text:
        return False
    what, target = PENDING.pop(uid)
    text = m.text.strip()[:800]
    if text.lower() in ("отмена", "/cancel"):
        await m.answer("ок, отменил")
        return True
    db, now = C.db, int(datetime.now().timestamp())
    if what in ("rules", "notes"):
        db.execute(f"INSERT INTO {what}(chat_id,text,date) VALUES(?,?,?)", (target, text, now))
        scr = scr_list(target, what)
    elif what == "persona":
        C.set_setting(0, "persona", text)
        scr = scr_persona()
    else:
        row = db.execute("SELECT facts FROM people WHERE user_id=?", (target,)).fetchone()
        if row:
            facts = json.loads(row[0] or "[]") + [text]
            db.execute("UPDATE people SET facts=? WHERE user_id=?", (json.dumps(facts[-30:], ensure_ascii=False), target))
        scr = scr_person(target)
    db.commit()
    C.dirty["v"] = True
    await show(m.chat.id, *scr)
    return True


@router.callback_query(F.data.startswith("m:"))
async def on_cb(cb: CallbackQuery):
    if not is_owner(cb.from_user.id):
        await cb.answer("это меню старосты")
        return
    parts = cb.data.split(":")
    act, args = parts[1], parts[2:]
    db = C.db
    cid = cur_chat()
    toast = None
    if act in ("chat", "act", "ch", "mode", "rules", "notes", "delrules", "delnotes", "addrules", "addnotes", "rem", "delrem") \
            and not cid:
        await cb.answer("сначала добавь меня в группу и напиши там что-нибудь", show_alert=True)
        return
    if act == "pick":
        scr = scr_pick()
    elif act == "setchat":
        C.set_setting(0, "menu_chat", int(args[0]))
        scr = scr_home()
    elif act == "chat":
        scr = scr_chat(cid)
    elif act == "act":
        C.set_setting(cid, "active", not C.setting(cid, "active", True))
        scr = scr_chat(cid)
    elif act == "ch":
        C.set_setting(cid, "chance", float(args[0]))
        scr, toast = scr_chat(cid), f"шанс {pct(float(args[0]))}"
    elif act == "mode":
        copy = C.setting(cid, "mode", {}).get("mode") == "copy"
        C.set_setting(cid, "mode", {"mode": "normal"} if copy else {"mode": "copy", "user_id": cb.from_user.id})
        scr = scr_chat(cid)
    elif act in ("rules", "notes"):
        scr = scr_list(cid, act)
    elif act in ("delrules", "delnotes"):
        table = act[3:]
        db.execute(f"DELETE FROM {table} WHERE chat_id=? AND id=?", (cid, int(args[0])))
        db.commit()
        C.dirty["v"] = True
        scr, toast = scr_list(cid, table), "удалил"
    elif act in ("addrules", "addnotes", "setpersona", "addfact"):
        what = {"addrules": "rules", "addnotes": "notes", "setpersona": "persona", "addfact": "fact"}[act]
        PENDING[cb.from_user.id] = (what, int(args[0]) if act == "addfact" else cid or 0)
        await cb.answer()
        await cb.message.answer(PROMPTS[what] + "\n\n(или «отмена»)")
        return
    elif act == "rem":
        scr = scr_rem(cid)
    elif act == "delrem":
        db.execute("DELETE FROM reminders WHERE chat_id=? AND id=?", (cid, int(args[0])))
        db.commit()
        scr, toast = scr_rem(cid), "удалил"
    elif act == "persona":
        scr = scr_persona()
    elif act == "resetpersona":
        C.set_setting(0, "persona", "")
        scr, toast = scr_persona(), "сбросил"
    elif act == "people":
        scr = scr_people(int(args[0]) if args else 0)
    elif act == "person":
        scr = scr_person(int(args[0]))
    elif act == "delfact":
        uid, idx = int(args[0]), int(args[1])
        row = db.execute("SELECT facts FROM people WHERE user_id=?", (uid,)).fetchone()
        if row:
            facts = json.loads(row[0] or "[]")
            if 0 <= idx < len(facts):
                facts.pop(idx)
            db.execute("UPDATE people SET facts=? WHERE user_id=?", (json.dumps(facts, ensure_ascii=False), uid))
            db.commit()
            C.dirty["v"] = True
        scr, toast = scr_person(uid), "удалил"
    elif act == "stats":
        scr = scr_stats()
    elif act == "sync":
        await cb.answer("сохраняю…")
        await asyncio.to_thread(C.export_memory)
        await cb.message.answer("☁️ сохранил в GitHub")
        return
    else:
        scr = scr_home()
    await cb.answer(toast)
    await show(cb.message.chat.id, *scr, message_id=cb.message.message_id)


def register(dp, core):
    global C
    C = core
    dp.include_router(router)
