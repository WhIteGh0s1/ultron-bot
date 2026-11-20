"""Меню старосты в стиле Ghostlink: баннер + подпись + сетка цветных кнопок.
Открывается /menu в личке бота (или в группе — тогда меню придёт в личку)."""
import asyncio
import html
import json
import logging
import re
from datetime import datetime
from pathlib import Path

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import (CallbackQuery, FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto,
                           Message)

log = logging.getLogger("ultron.menu")
router = Router()
C = None  # модуль бота, задаётся в register()
PENDING: dict[int, tuple[str, int]] = {}  # user_id -> (что ждём, id)
BANNER = Path(__file__).resolve().parent / "assets" / "banner.png"

# премиум-эмодзи для текста (у владельца Premium — рисуются анимированными)
E = {
    "shield": ("5902016123972358349", "🛡"), "device": ("5895652322469482989", "📱"),
    "check": ("5895514131896733546", "✅"), "cross": ("5893163582194978381", "❌"),
    "clock": ("5902050947567194830", "⏰"), "rocket": ("6041705726206808304", "🚀"),
    "stats": ("5895444149699612825", "📊"), "info": ("5893290369629556374", "💡"),
    "sparkle": ("5893321843149902412", "✨"), "star": ("5893494861612455015", "⭐️"),
    "warning": ("5904692292324692386", "⚠️"), "profile": ("5902335789798265487", "👤"),
    "link": ("5902449142575141204", "🔗"),
}
# иконки кнопок — тот же набор, что в Ghostlink (custom_patches/inline.py)
ICON = {
    "back": "5893368370530621889", "shield": "5902016123972358349", "device": "5895652322469482989",
    "check": "5895514131896733546", "cross": "5893163582194978381", "clock": "5902050947567194830",
    "rocket": "6041705726206808304", "stats": "5895444149699612825", "info": "5893290369629556374",
    "trophy": "5893376775781617954", "sparkle": "5893321843149902412", "star": "5893494861612455015",
    "plus": "5902453596456227896", "warning": "5904692292324692386", "stop": "5904238507555033712",
    "trash": "5904542823167824187", "gear": "5902432207519093015", "profile": "5902335789798265487",
    "link": "5902449142575141204", "search": "5893382531037794941",
}
ICONS_OK = {"v": True}  # Telegram отверг иконки — дальше без них
esc = html.escape


def em(name: str) -> str:
    i, fb = E[name]
    return f'<tg-emoji emoji-id="{i}">{fb}</tg-emoji>'


def b(text: str, data: str, style: str | None = None, icon: str | None = None) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=data, style=style,
                                icon_custom_emoji_id=ICON[icon] if icon and ICONS_OK["v"] else None)


def no_icons(k: InlineKeyboardMarkup) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=x.text, callback_data=x.callback_data, style=x.style)
                                                  for x in row] for row in k.inline_keyboard])


def kb(*rows) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[list(r) for r in rows if r])


BACK = lambda data="m:home": b("Назад", data, "primary", "back")


# ---------- отправка ----------
async def banner():
    fid = C.setting(0, "banner_fid")
    return fid or FSInputFile(BANNER)


async def show(chat_id: int, caption: str, k: InlineKeyboardMarkup, message_id: int | None = None):
    caption = caption[:1024]
    if message_id:
        try:
            await C.bot.edit_message_caption(chat_id=chat_id, message_id=message_id, caption=caption,
                                             reply_markup=k, parse_mode="HTML")
            return
        except TelegramBadRequest as e:
            if "not modified" in str(e).lower():
                return
            try:  # старое сообщение без фото — пересоздаём
                await C.bot.delete_message(chat_id, message_id)
            except TelegramBadRequest:
                pass
    try:
        sent = await C.bot.send_photo(chat_id, await banner(), caption=caption, reply_markup=k, parse_mode="HTML")
    except TelegramBadRequest as e:
        if "emoji" not in str(e).lower() and "icon" not in str(e).lower():
            raise
        log.warning("иконки кнопок не приняты, дальше без них: %s", e)
        ICONS_OK["v"] = False
        sent = await C.bot.send_photo(chat_id, await banner(), caption=caption, reply_markup=no_icons(k), parse_mode="HTML")
    if not C.setting(0, "banner_fid") and sent.photo:
        C.set_setting(0, "banner_fid", sent.photo[-1].file_id)


# ---------- данные ----------
def chats() -> list[tuple[int, str]]:
    return C.db.execute("SELECT chat_id,title FROM chats ORDER BY title").fetchall()


def cur_chat() -> int | None:
    """Чат, который сейчас настраивается в меню."""
    ids = [c for c, _ in chats()]
    cid = C.setting(0, "menu_chat")
    if cid in ids:
        return cid
    return ids[0] if ids else None


def title(cid: int) -> str:
    row = C.db.execute("SELECT title FROM chats WHERE chat_id=?", (cid,)).fetchone()
    return row[0] if row else str(cid)


def when(ts) -> str:
    return datetime.fromtimestamp(ts).strftime("%d.%m %H:%M") if ts else "ещё не было"


# ---------- экраны ----------
def scr_home():
    cid = cur_chat()
    db = C.db
    n_msg = db.execute("SELECT count(*) FROM messages").fetchone()[0]
    n_people = db.execute("SELECT count(*) FROM people WHERE user_id!=?", (C.ME["id"],)).fetchone()[0]
    if cid:
        active = C.setting(cid, "active", True)
        copy = C.setting(cid, "mode", {}).get("mode") == "copy"
        chat_line = (f"{em('device')} <b>{esc(title(cid))}</b>\n"
                     f"{em('check') if active else em('cross')} Сам влезает · {str(round(C.chance(cid) * 100)) + '%' if active else 'выкл'}"
                     f"   {em('sparkle')} Режим · {'копирование' if copy else 'обычный'}")
    else:
        chat_line = f"{em('info')} Добавь меня в группу и напиши там что-нибудь"
    cap = (f"{em('shield')} <b>АЛЬТРОН</b> · правая рука старосты\n\n{chat_line}\n\n"
           f"{em('stats')} Сообщений <b>{n_msg}</b> · людей <b>{n_people}</b>\n"
           f"{em('link')} GitHub · {when(C.setting(0, 'last_sync'))}")
    k = kb([b("Настройки чата", "m:chat", None, "gear"), b("Характер", "m:persona", "primary", "sparkle")],
           [b("Правила", "m:rules", None, "warning"), b("Заметки", "m:notes", None, "info")],
           [b("Напоминания", "m:rem", None, "clock"), b("Люди", "m:people", None, "profile")],
           [b(f"Чат: {title(cid)[:24]}", "m:pick", "primary", "device")] if len(chats()) > 1 else None,
           [b("Статистика", "m:stats", None, "stats")],
           [b("Сохранить в GitHub", "m:sync", "success", "link")])
    return cap, k


def scr_pick():
    cur = cur_chat()
    return (f"{em('device')} <b>Какой чат настраиваем?</b>",
            kb(*[[b((t or str(c))[:30], f"m:setchat:{c}", "success" if c == cur else None, "check" if c == cur else "device")]
                 for c, t in chats()], [BACK()]))


def scr_chat(cid: int):
    active = C.setting(cid, "active", True)
    mode = C.setting(cid, "mode", {"mode": "normal"})
    copy = mode.get("mode") == "copy"
    ch = C.chance(cid)
    who = ""
    if copy:
        row = C.db.execute("SELECT name FROM people WHERE user_id=?", (mode.get("user_id", 0),)).fetchone()
        who = f" ({esc(row[0])})" if row else ""
    cap = (f"{em('device')} <b>{esc(title(cid))}</b>\n\n"
           f"{em('check') if active else em('cross')} <b>Сам влезает в разговор</b> · {'да, ' + str(round(ch * 100)) + '%' if active else 'нет'}\n"
           f"{em('sparkle')} <b>Режим</b> · {'копирование' + who if copy else 'обычный'}\n\n"
           f"<blockquote expandable>Шанс — как часто бот сам вставляет реплику, реакцию или стикер, когда к нему не обращались. "
           f"Режим копирования — бот пишет твоей манерой, с твоими словечками и опечатками.</blockquote>")
    k = kb([b("Сам влезает: ВКЛ" if active else "Сам влезает: ВЫКЛ", "m:act", "success" if active else "danger",
             "check" if active else "stop")],
           [b(("• " if abs(ch - v) < 0.001 else "") + f"{round(v * 100)}%", f"m:ch:{v}") for v in (0.05, 0.1, 0.2, 0.35, 0.5)],
           [b("Режим: копирование" if copy else "Режим: обычный", "m:mode", "primary", "sparkle")],
           [BACK()])
    return cap, k


def scr_list(cid: int, what: str):
    if what == "rules":
        items, head, hint = C.rules(cid), f"{em('warning')} <b>Правила</b>", \
            "Бот выполняет их всегда. Можно давать и в чате: «альтрон новое правило: …»"
    else:
        items, head, hint = C.notes(cid), f"{em('info')} <b>Заметки</b>", "Факты о группе: пары, дедлайны, кто за что отвечает"
    body = "\n".join(f"<b>{n}.</b> {esc(t)}" for n, (_, t) in enumerate(items, 1)) or "пока пусто"
    cap = f"{head} · {esc(title(cid))}\n\n{body}\n\n<i>{hint}</i>"
    if len(cap) > 1000:
        cap = cap[:990] + "…"
    dels = [b(str(n), f"m:del{what}:{i}", "danger", "trash") for n, (i, _) in enumerate(items, 1)]
    return cap, kb(*[dels[i:i + 4] for i in range(0, len(dels), 4)],
                   [b("Добавить", f"m:add{what}", "success", "plus")], [BACK()])


def scr_rem(cid: int):
    rows = C.db.execute("SELECT id,at,text FROM reminders WHERE chat_id=? AND done=0 ORDER BY at", (cid,)).fetchall()
    body = "\n".join(f"<b>{n}.</b> <code>{when(at)}</code> {esc(t)}" for n, (_, at, t) in enumerate(rows, 1)) or "нет запланированных"
    cap = (f"{em('clock')} <b>Напоминания</b> · {esc(title(cid))}\n\n{body}\n\n"
           f"<i>Новые ставятся в чате: «альтрон напомни завтра в 8:30 …»</i>")[:1024]
    dels = [b(str(n), f"m:delrem:{i}", "danger", "trash") for n, (i, _, _) in enumerate(rows, 1)]
    return cap, kb(*[dels[i:i + 4] for i in range(0, len(dels), 4)], [BACK()])


def scr_persona():
    p = C.persona()
    cap = (f"{em('sparkle')} <b>Характер</b>\n\n"
           f"<blockquote>{esc(p) if p else 'ничего не задано — работает базовый: дерзкий, чёрный юмор, мат, спорит'}</blockquote>\n"
           f"<i>Свои указания поверх базового, для всех чатов. Например: «больше чёрного юмора», «называй меня шеф»</i>")
    return cap[:1024], kb([b("Изменить", "m:setpersona", "success", "plus"), b("Сбросить", "m:resetpersona", "danger", "trash")], [BACK()])


def scr_people(page: int = 0):
    rows = C.db.execute("SELECT user_id,name,facts,msg_count FROM people WHERE user_id!=? ORDER BY msg_count DESC",
                        (C.ME["id"],)).fetchall()
    per = 10
    part = rows[page * per:(page + 1) * per]
    body = "\n".join(f"<b>{esc(n)}</b> · {c} сообщ. · {len(json.loads(f or '[]'))} фактов" for _, n, f, c in part) or "пока никого"
    cap = f"{em('profile')} <b>Люди</b> · {len(rows)}\n\n{body}"
    btns = [b(n[:20], f"m:person:{i}", None, "profile") for i, n, *_ in part]
    nav = []
    if page > 0:
        nav.append(b("Назад", f"m:people:{page - 1}", None, "back"))
    if (page + 1) * per < len(rows):
        nav.append(b("Дальше", f"m:people:{page + 1}", None, "rocket"))
    return cap[:1024], kb(*[btns[i:i + 2] for i in range(0, len(btns), 2)], nav or None, [BACK()])


def scr_person(uid: int):
    row = C.db.execute("SELECT name,username,facts,msg_count,first_seen,last_seen FROM people WHERE user_id=?", (uid,)).fetchone()
    if not row:
        return scr_people()
    n, u, f, c, fs, ls = row
    facts = json.loads(f or "[]")
    body = "\n".join(f"<b>{k}.</b> {esc(x)}" for k, x in enumerate(facts, 1)) or "ничего"
    cap = (f"{em('profile')} <b>{esc(n)}</b>{' · @' + esc(u) if u else ''}\n"
           f"<code>{uid}</code> · {c} сообщ. · последний раз {when(ls)}\n\n"
           f"{em('info')} <b>Что бот о нём знает</b>\n{body}")[:1024]
    dels = [b(str(k), f"m:delfact:{uid}:{k - 1}", "danger", "trash") for k in range(1, len(facts) + 1)]
    return cap, kb(*[dels[i:i + 4] for i in range(0, len(dels), 4)],
                   [b("Добавить факт", f"m:addfact:{uid}", "success", "plus")], [BACK("m:people")])


def scr_stats():
    db = C.db
    cid = cur_chat()
    day = int(datetime.now().timestamp()) - 86400
    top = db.execute("SELECT name,count(*) FROM messages WHERE chat_id=? AND user_id!=? GROUP BY user_id "
                     "ORDER BY 2 DESC LIMIT 5", (cid or 0, C.ME["id"])).fetchall()
    today = db.execute("SELECT count(*) FROM messages WHERE chat_id=? AND date>=?", (cid or 0, day)).fetchone()[0]
    mine = db.execute("SELECT count(*) FROM messages WHERE user_id=?", (C.ME["id"],)).fetchone()[0]
    medals = ["🥇", "🥈", "🥉", "4.", "5."]
    cap = (f"{em('stats')} <b>Статистика</b>{' · ' + esc(title(cid)) if cid else ''}\n\n"
           f"За сутки сообщений · <b>{today}</b>\n"
           f"Бот написал всего · <b>{mine}</b>\n"
           f"Стикеров знает · <b>{db.execute('SELECT count(*) FROM stickers').fetchone()[0]}</b>\n\n"
           f"<b>Самые болтливые</b>\n" + ("\n".join(f"{medals[i]} {esc(n)} · {c}" for i, (n, c) in enumerate(top)) or "пока никого"))
    return cap[:1024], kb([BACK()])


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
    need_chat = act in ("chat", "act", "ch", "mode", "rules", "notes", "delrules", "delnotes", "addrules", "addnotes", "rem", "delrem")
    if need_chat and not cid:
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
        scr, toast = scr_chat(cid), f"шанс {round(float(args[0]) * 100)}%"
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
        await show(cb.message.chat.id, *scr_home(), message_id=cb.message.message_id)
        return
    else:
        scr = scr_home()
    await cb.answer(toast)
    await show(cb.message.chat.id, *scr, message_id=cb.message.message_id)


def register(dp, core):
    global C
    C = core
    dp.include_router(router)
