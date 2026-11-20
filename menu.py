"""Rich-меню старосты: rich-сообщение (Bot API 10.2+) — баннер раздела картинкой сверху, ниже rich-блоки
(премиум-эмодзи, таблицы, details, footer), под сообщением цветные кнопки с эмодзи в тексте, как у Ghostlink.
Если клиент/сервер не умеет rich — то же самое фото + подпись. Открывается /menu в личке бота."""
import asyncio
import html
import json
import logging
import re
from datetime import datetime
from pathlib import Path

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.methods import EditMessageText
from aiogram.types import (CallbackQuery, FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto,
                           InputRichMessage, InputRichMessageMedia, Message)

log = logging.getLogger("ultron.menu")
router = Router()
C = None  # модуль бота, задаётся в register()
PENDING: dict[int, tuple[str, int]] = {}  # user_id -> (что ждём, id)
BANNERS = Path(__file__).resolve().parent / "assets" / "banners"
RICH = {"ok": True}  # сервер не знает rich — дальше фото+подпись
esc = html.escape

# премиум-эмодзи ProtectStatus (как в Ghostlink) — в тексте rich-сообщения рендерятся
E = {
    "shield": ("5902016123972358349", "🛡"), "device": ("5895652322469482989", "📱"),
    "check": ("5895514131896733546", "✅"), "cross": ("5893163582194978381", "❌"),
    "clock": ("5902050947567194830", "⏰"), "rocket": ("6041705726206808304", "🚀"),
    "stats": ("5895444149699612825", "📊"), "info": ("5893290369629556374", "💡"),
    "sparkle": ("5893321843149902412", "✨"), "star": ("5893494861612455015", "⭐️"),
    "warning": ("5904692292324692386", "⚠️"), "profile": ("5902335789798265487", "👤"),
    "link": ("5902449142575141204", "🔗"), "trophy": ("5893376775781617954", "🏆"),
}


def em(name: str) -> str:
    i, fb = E[name]
    return f'<tg-emoji emoji-id="{i}">{fb}</tg-emoji>'


def b(text: str, data: str, style: str | None = None) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=data, style=style)


def kb(*rows) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[list(r) for r in rows if r])


BACK = lambda data="m:home": b("◀️ Назад", data)


# ---------- отправка ----------
_HASH: dict[str, str] = {}


def bkey(key: str) -> str:
    """Ключ кеша file_id: меняется, когда баннер перерисован."""
    if key not in _HASH:
        import hashlib
        _HASH[key] = hashlib.md5((BANNERS / f"{key}.png").read_bytes()).hexdigest()[:10]
    return f"banner:{key}:{_HASH[key]}"


def photo(key: str):
    return C.setting(0, bkey(key)) or FSInputFile(BANNERS / f"{key}.png")


def cache_photo(key: str, sent) -> None:
    """Запомнить file_id баннера из ответа Telegram, чтобы не грузить файл каждый раз."""
    if C.setting(0, bkey(key)) or not isinstance(sent, Message):
        return
    ids = re.findall(r"'file_id': '([^']+)'", str(sent.model_dump(exclude_none=True)))
    if ids:
        C.set_setting(0, bkey(key), ids[-1])


def classic(h: str) -> str:
    """Rich-HTML → подпись к фото (если rich недоступен)."""
    h = re.sub(r"<h\d>(.*?)</h\d>", r"<b>\1</b>\n", h)
    h = re.sub(r"</tr>", "\n", h)
    h = re.sub(r"</t[dh]>", " · ", h)
    h = re.sub(r"<br\s*/?>|</p>|<hr\s*/?>|</summary>|</footer>|</blockquote>", "\n", h)
    h = re.sub(r"<(?!/?(b|i|u|s|code|a|tg-emoji)\b)[^>]+>", "", h)
    return re.sub(r"\n{3,}", "\n\n", h).strip()[:1024]


async def show(chat_id: int, key: str, body: str, k: InlineKeyboardMarkup, message_id: int | None = None):
    if RICH["ok"]:
        rich = InputRichMessage(html=f'<img src="tg://photo?id={key}"/>' + body, skip_entity_detection=True,
                                media=[InputRichMessageMedia(id=key, media=InputMediaPhoto(media=photo(key)))])
        try:
            if message_id:
                try:
                    sent = await C.bot(EditMessageText(chat_id=chat_id, message_id=message_id, rich_message=rich,
                                                       reply_markup=k, parse_mode=None))
                    cache_photo(key, sent)
                    return
                except TelegramBadRequest as e:
                    if "not modified" in str(e).lower():
                        return
                    log.info("rich-меню не отредактировал (%s) — шлю заново", e)
                    try:
                        await C.bot.delete_message(chat_id, message_id)
                    except TelegramBadRequest:
                        pass
            sent = await C.bot.send_rich_message(chat_id=chat_id, rich_message=rich, reply_markup=k)
            cache_photo(key, sent)
            return
        except TelegramBadRequest as e:
            text = str(e).lower()
            if "unknown method" in text or "method not found" in text or "rich" in text:
                log.warning("rich не поддерживается — меню фото+подписью: %s", e)
                RICH["ok"] = False
            else:
                raise
    # запасной вариант: фото + подпись
    cap = classic(body) or None
    if message_id:
        try:
            await C.bot.edit_message_media(chat_id=chat_id, message_id=message_id, reply_markup=k,
                                           media=InputMediaPhoto(media=photo(key), caption=cap, parse_mode="HTML"))
            return
        except TelegramBadRequest:
            pass
    sent = await C.bot.send_photo(chat_id, photo(key), caption=cap, reply_markup=k, parse_mode="HTML")
    cache_photo(key, sent)


# ---------- данные ----------
def chats() -> list[tuple[int, str]]:
    return C.db.execute("SELECT chat_id,title FROM chats ORDER BY title").fetchall()


def cur_chat() -> int | None:
    ids = [c for c, _ in chats()]
    cid = C.setting(0, "menu_chat")
    return cid if cid in ids else (ids[0] if ids else None)


def title(cid: int | None) -> str:
    row = C.db.execute("SELECT title FROM chats WHERE chat_id=?", (cid,)).fetchone() if cid else None
    return row[0] if row else str(cid or "—")


def when(ts) -> str:
    return datetime.fromtimestamp(ts).strftime("%d.%m %H:%M") if ts else "ещё не было"


def pct(v: float) -> str:
    return f"{round(v * 100)}%"


def count(sql: str, *args) -> int:
    return C.db.execute(sql, args).fetchone()[0]


def chat_head(cid: int) -> str:
    active = C.setting(cid, "active", True)
    copy = C.setting(cid, "mode", {}).get("mode") == "copy"
    return (f"<p>{em('device')} <b>{esc(title(cid))}</b><br>"
            f"{em('check') if active else em('cross')} Сам влезает · <b>{pct(C.chance(cid)) if active else 'выкл'}</b><br>"
            f"{em('sparkle')} Режим · <b>{'копирование' if copy else 'обычный'}</b></p>")


# ---------- экраны: (баннер, rich-HTML, кнопки) ----------
def scr_home():
    cid = cur_chat()
    if cid:
        body = chat_head(cid) + (
            "<table bordered striped><tr><th>Сообщений</th><th>Людей</th><th>Правил</th><th>Напоминаний</th></tr>"
            f"<tr><td>{count('SELECT count(*) FROM messages WHERE chat_id=?', cid)}</td>"
            f"<td>{count('SELECT count(*) FROM people WHERE user_id!=?', C.ME['id'])}</td>"
            f"<td>{len(C.rules(cid))}</td>"
            f"<td>{count('SELECT count(*) FROM reminders WHERE chat_id=? AND done=0', cid)}</td></tr></table>")
    else:
        body = f"<p>{em('info')} Добавь меня в группу и напиши там что-нибудь — тут появится чат.</p>"
    body += f"<footer>{em('star')} Выбери раздел</footer>"
    k = kb([b("⚙️ Настройки", "m:chat"), b("😈 Характер", "m:persona", "primary")],
           [b("⚡ Правила", "m:rules"), b("📌 Заметки", "m:notes")],
           [b("⏰ Напоминания", "m:rem"), b("👥 Люди", "m:people")],
           [b(f"💬 Чат: {title(cid)[:24]}", "m:pick")] if len(chats()) > 1 else None,
           [b("📊 Статистика", "m:stats")],
           [b("☁️ Сохранить в GitHub", "m:sync", "success")])
    return "home", body, k


def scr_pick():
    cur = cur_chat()
    return "chat", f"<p>{em('device')} <b>Какой чат настраиваем?</b></p>", kb(
        *[[b(("✅ " if c == cur else "💬 ") + (t or str(c))[:30], f"m:setchat:{c}", "success" if c == cur else None)]
          for c, t in chats()], [BACK()])


def scr_chat(cid: int):
    active = C.setting(cid, "active", True)
    copy = C.setting(cid, "mode", {}).get("mode") == "copy"
    ch = C.chance(cid)
    body = chat_head(cid) + (
        f"<details><summary>{em('info')} <b>Что это значит</b></summary>"
        "<p>Шанс — как часто бот сам вставляет реплику, реакцию или стикер, когда к нему не обращались.<br>"
        "Копирование — бот пишет манерой старосты: его словечки, опечатки, без запятых.</p></details>")
    k = kb([b("✅ Сам влезает: вкл" if active else "⛔ Сам влезает: выкл", "m:act", "success" if active else "danger")],
           [b(("• " if abs(ch - v) < 0.001 else "") + pct(v), f"m:ch:{v}") for v in (0.05, 0.1, 0.2, 0.35, 0.5)],
           [b("🪞 Режим: копирование" if copy else "🗣 Режим: обычный", "m:mode", "primary")],
           [BACK()])
    return "chat", body, k


def scr_list(cid: int, what: str):
    items = C.rules(cid) if what == "rules" else C.notes(cid)
    hint = ("Выполняются всегда. Можно давать прямо в чате: «альтрон новое правило: …»" if what == "rules"
            else "Факты о группе: пары, дедлайны, кто за что отвечает")
    rows = "".join(f"<tr><td>{n}</td><td>{esc(t)}</td></tr>" for n, (_, t) in enumerate(items, 1))
    body = (f"<p>{em('device')} <b>{esc(title(cid))}</b></p>"
            + (f"<table bordered striped>{rows}</table>" if rows else f"<p>{em('info')} Пока пусто</p>")
            + f"<footer>{em('warning' if what == 'rules' else 'info')} {esc(hint)}</footer>")
    dels = [b(f"🗑 {n}", f"m:del{what}:{i}", "danger") for n, (i, _) in enumerate(items, 1)]
    return what, body, kb(*[dels[i:i + 4] for i in range(0, len(dels), 4)],
                          [b("➕ Добавить", f"m:add{what}", "success")], [BACK()])


def scr_rem(cid: int):
    rows = C.db.execute("SELECT id,at,text FROM reminders WHERE chat_id=? AND done=0 ORDER BY at", (cid,)).fetchall()
    table = "".join(f"<tr><td>{n}</td><td>{when(at)}</td><td>{esc(t)}</td></tr>" for n, (_, at, t) in enumerate(rows, 1))
    body = (f"<p>{em('device')} <b>{esc(title(cid))}</b></p>"
            + (f"<table bordered striped><tr><th>#</th><th>Когда</th><th>Что</th></tr>{table}</table>" if table
               else f"<p>{em('clock')} Нет запланированных</p>")
            + f"<footer>{em('info')} Новые ставятся в чате: «альтрон напомни завтра в 8:30 …»</footer>")
    dels = [b(f"🗑 {n}", f"m:delrem:{i}", "danger") for n, (i, _, _) in enumerate(rows, 1)]
    return "rem", body, kb(*[dels[i:i + 4] for i in range(0, len(dels), 4)], [BACK()])


def scr_persona():
    p = C.persona()
    body = (f"<p>{em('sparkle')} <b>Базовый характер</b> — дерзкий, чёрный юмор, мат к месту, держит позицию в споре, "
            "за старосту горой.</p>"
            f"<blockquote>{esc(p) if p else 'Своих указаний пока нет'}</blockquote>"
            f"<footer>{em('info')} Свои указания поверх базового, для всех чатов: «больше чёрного юмора», «называй меня шеф»</footer>")
    return "persona", body, kb([b("✏️ Изменить", "m:setpersona", "success"), b("🗑 Сбросить", "m:resetpersona", "danger")],
                               [BACK()])


def scr_people(page: int = 0):
    rows = C.db.execute("SELECT user_id,name,facts,msg_count FROM people WHERE user_id!=? ORDER BY msg_count DESC",
                        (C.ME["id"],)).fetchall()
    per = 10
    part = rows[page * per:(page + 1) * per]
    table = "".join(f"<tr><td>{esc(n)}</td><td>{c}</td><td>{len(json.loads(f or '[]'))}</td></tr>" for _, n, f, c in part)
    body = (f"<p>{em('profile')} Всего <b>{len(rows)}</b></p>"
            + (f"<table bordered striped><tr><th>Кто</th><th>Сообщений</th><th>Фактов</th></tr>{table}</table>" if table
               else f"<p>{em('info')} Пока никого</p>"))
    btns = [b(f"👤 {n[:18]}", f"m:person:{i}") for i, n, *_ in part]
    nav = ([b("◀️", f"m:people:{page - 1}")] if page > 0 else []) + \
          ([b("▶️", f"m:people:{page + 1}")] if (page + 1) * per < len(rows) else [])
    return "people", body, kb(*[btns[i:i + 2] for i in range(0, len(btns), 2)], nav or None, [BACK()])


def scr_person(uid: int):
    row = C.db.execute("SELECT name,username,facts,msg_count,last_seen FROM people WHERE user_id=?", (uid,)).fetchone()
    if not row:
        return scr_people()
    n, u, f, c, ls = row
    facts = json.loads(f or "[]")
    body = (f"<h4>{em('profile')} {esc(n)}</h4>"
            f"<p>{'@' + esc(u) + '<br>' if u else ''}<code>{uid}</code> · {c} сообщ. · был {when(ls)}</p>"
            f"<details open><summary>{em('info')} <b>Что бот о нём знает</b></summary>"
            + ("".join(f"<p>{k}. {esc(x)}</p>" for k, x in enumerate(facts, 1)) or "<p>ничего</p>") + "</details>")
    dels = [b(f"🗑 {k}", f"m:delfact:{uid}:{k - 1}", "danger") for k in range(1, len(facts) + 1)]
    return "people", body, kb(*[dels[i:i + 4] for i in range(0, len(dels), 4)],
                              [b("➕ Добавить факт", f"m:addfact:{uid}", "success")], [BACK("m:people")])


def scr_stats():
    cid = cur_chat() or 0
    day = int(datetime.now().timestamp()) - 86400
    top = C.db.execute("SELECT name,count(*) FROM messages WHERE chat_id=? AND user_id!=? GROUP BY user_id "
                       "ORDER BY 2 DESC LIMIT 5", (cid, C.ME["id"])).fetchall()
    medals = ["🥇", "🥈", "🥉", "4", "5"]
    body = (f"<p>{em('device')} <b>{esc(title(cid))}</b></p>"
            "<table bordered striped>"
            f"<tr><td>Сообщений за сутки</td><td>{count('SELECT count(*) FROM messages WHERE chat_id=? AND date>=?', cid, day)}</td></tr>"
            f"<tr><td>Всего сообщений</td><td>{count('SELECT count(*) FROM messages')}</td></tr>"
            f"<tr><td>Бот написал</td><td>{count('SELECT count(*) FROM messages WHERE user_id=?', C.ME['id'])}</td></tr>"
            f"<tr><td>Стикеров знает</td><td>{count('SELECT count(*) FROM stickers')}</td></tr>"
            f"<tr><td>GitHub</td><td>{when(C.setting(0, 'last_sync'))}</td></tr></table>"
            f"<h4>{em('trophy')} Самые болтливые</h4>"
            + ("<table bordered striped>" + "".join(f"<tr><td>{medals[i]}</td><td>{esc(n)}</td><td>{c}</td></tr>"
                                                     for i, (n, c) in enumerate(top)) + "</table>" if top
               else "<p>пока никого</p>"))
    return "stats", body, kb([BACK()])


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
