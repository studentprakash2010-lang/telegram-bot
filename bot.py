# -*- coding: utf-8 -*-
"""
Telegram Shop Bot  (python-telegram-bot v20+)  +  Online-Admin UPI QR
Install :  pip install -U "python-telegram-bot>=21.5" aiohttp qrcode pillow
Run     :  BOT_TOKEN=xxxx python3 shop_bot.py

Setup:
 1. BOT_TOKEN (env), ADMIN_IDS, CHANNEL, CHANNEL_URL set karo.
 2. Bot ko apne channel me ADMIN banao (warna join check nahi chalega).
 3. /admin -> "My UPI ID" se apna UPI ID set karo, phir "Online" dabao.
    Jo admin Online hoga, user ko usi ke UPI ID ka fixed-amount QR dikhega.
    Koi admin online nahi hoga to Item QR / Global QR use hoga.
"""
import asyncio
import html
import io
import json
import logging
import math
import os
import re
import time
from urllib.parse import quote

import qrcode
from aiohttp import web
from telegram import InlineKeyboardButton as B, InlineKeyboardMarkup as M, Update
from telegram.constants import ChatMemberStatus, ParseMode
from telegram.error import TelegramError
from telegram.ext import (Application, CallbackQueryHandler, CommandHandler,
                          ContextTypes, Defaults, MessageHandler, filters)

# ===================== CONFIG =====================
BOT_TOKEN = os.getenv("BOT_TOKEN", "8886347612:AAFEhesMmEWAgdGOKNsjqvmoT_CjRtkuR5Y")
ADMIN_IDS = [7689771634]                        # OWNER id(s)
CHANNEL = "@all_for_one_121"                    # ya -100xxxxxxxxxx
CHANNEL_URL = "https://t.me/all_for_one_121"    # join button ka link
DB_FILE = "shop_db.json"
BRAND = "PREMIUM SERVICES"
MIN_QTY, MAX_QTY = 100, 100000
AUTO_VERIFY = False                             # True = bank SMS se auto payment check
WEBHOOK_PORT = 8080
EFFECTS = True                                  # message effects (🔥🎉) - sirf private chat me chalte hain
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "change-me-long-random-text")
# ==================================================

logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s", level=logging.INFO)
log = logging.getLogger("shopbot")

UPI_RE = re.compile(r"^[\w.\-]{2,}@[A-Za-z]{2,}$")

# ---------- look & feel ----------
LINE = "🔹━━━━━━━━━━━━━━🔹"
FX = {"fire": "5104841245755180586", "like": "5107584321108051014",
      "heart": "5044134455711629726", "party": "5046509860389126442"}


def head(title):
    return f"<b>{title}</b>\n{LINE}\n"


JOIN_TEXT = (head(f"✨ {BRAND} ✨") + "🎉 <b>Welcome!</b> 🎊\n\n🔒 "
             "Bot use karne ke liye pehle hamara official channel join karein.\n\n"
             "1️⃣ <b>Join Channel</b> dabayein\n2️⃣ Join karke <b>I have joined</b> dabayein")
DEFAULT_MAIN_TEXT = head(f"✨ {BRAND} ✨") + "🏠 <b>Main Menu</b>\n🛍 Apni zaroorat ke hisaab se service choose karein 👇"
MAINT_TEXT = head("🛠 Under Maintenance") + "Ye service abhi update ho rahi hai.\nThodi der baad dobara try karein."
ADMIN_TEXT = head("🛠 Admin Panel") + "Manage karne ke liye option choose karein 👇"

# ---------- catalogue ----------
PACKS = {"c100": 100, "c500": 500, "c1000": 1000, "h1000": 1000}
FOLLOWER_KEYS = set(PACKS) | {"fwa", "ftg"}
TITLES = {
    "u10": "Unsafe Panel #1", "u30": "Unsafe Panel #2", "sp": "Safe Panel (Permanent)",
    "sf2": "Safe Panel Option 2", "login": "WhatsApp/Telegram Login",
    "otp": "OTP Verification Service", "qr": "Generate QR",
    "unsub": "Unsubscribe Issue", "fwa": "WhatsApp Followers", "ftg": "Telegram Followers",
}
LABELS = {
    "c100": "Cheap 100", "c500": "Cheap 500", "c1000": "Cheap 1000", "h1000": "High 1000",
    "rate_c": "Cheap rate/follower", "rate_h": "High rate/follower",
    "u10": "Unsafe #1", "u30": "Unsafe #2", "sp": "Safe Permanent", "sf2": "Safe Option 2",
    "login": "WA/TG Login", "otp": "OTP Service", "qr": "Generate QR",
    "unsub": "Unsub Issue", "fwa": "WhatsApp Followers", "ftg": "Telegram Followers",
}
DELIV_KEYS = ["u10", "u30", "sp", "sf2", "login", "otp", "qr", "unsub"]
MAINT_KEYS = ["fwa", "ftg", "sf2", "login", "otp", "qr", "unsub"]
QR_EXTRA = {"custom_c": "Custom Cheap Qty", "custom_h": "Custom High Qty"}
# custom option kahan dikhega
PARENTS = {
    "main": "🏠 Main Menu",
    "f": "👥 Followers (platform list)",
    "f:ig": "📸 Instagram (Cheap/High page)",
    "f:c": "💸 Instagram Cheap Plans",
    "f:h": "💎 Instagram Premium Plans",
    "p": "🧩 Panel (Unsafe/Safe page)",
    "p:u": "⚠️ Unsafe Panel",
    "p:s": "🛡 Safe Panel",
}

DEFAULT_DB = {
    "qr": None,
    "qrs": {},
    "users": [],
    "used_utr": [],
    "orders": {},
    "seq": 0,
    "maint": {k: True for k in MAINT_KEYS},
    "prices": {
        "c100": 10, "c500": 40, "c1000": 70, "h1000": 400,
        "rate_c": 0.07, "rate_h": 0.4,
        "u10": 10, "u30": 30, "sp": 150,
        "sf2": 0, "login": 0, "otp": 0, "qr": 0, "unsub": 0, "fwa": 0, "ftg": 0,
    },
    "delivery": {},
    "payments": {},
    "admins": [],
    "custom": {},
    "cseq": 0,
    "labels": {},
    "texts": {},
    "upis": {},      # admin_id (str) -> UPI ID
    "online": [],    # abhi online admin ids (jo last me online hua wahi active)
}


# ---------- database ----------
def load_db():
    data = {}
    if os.path.exists(DB_FILE):
        with open(DB_FILE, encoding="utf-8") as f:
            data = json.load(f)
    for k, v in DEFAULT_DB.items():
        if k not in data:
            data[k] = json.loads(json.dumps(v))
        elif isinstance(v, dict):
            for kk, vv in v.items():
                data[k].setdefault(kk, vv)
    return data


db = load_db()


def save_db():
    tmp = DB_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=1)
    os.replace(tmp, DB_FILE)


# ---------- helpers ----------
def main_text():
    t = db["texts"].get("main")
    return esc(t) if t else DEFAULT_MAIN_TEXT


def is_admin(uid):
    return uid in ADMIN_IDS or uid in db["admins"]


def all_admins():
    return list(dict.fromkeys(ADMIN_IDS + db["admins"]))


def fmt(n):
    n = round(float(n), 2)
    return str(int(n)) if n == int(n) else f"{n:.2f}"


def esc(s):
    return html.escape(str(s))


def kb(*rows):
    return M([[B(t, callback_data=c) for t, c in row] for row in rows])


def cu_rows(parent):
    return [[("⭐ " + c["name"], f"cu:{cid}")] for cid, c in db["custom"].items()
            if c.get("parent", "main") == parent]


async def send(bot, chat_id, text, effect=None, **kw):
    """send_message + optional message effect (purani library/group me bina effect ke chalta hai)."""
    if effect and EFFECTS:
        try:
            return await bot.send_message(chat_id, text, message_effect_id=FX[effect], **kw)
        except (TelegramError, TypeError):
            pass
    return await bot.send_message(chat_id, text, **kw)


async def reply(msg, text, effect=None, **kw):
    if effect and EFFECTS:
        try:
            return await msg.reply_text(text, message_effect_id=FX[effect], **kw)
        except (TelegramError, TypeError):
            pass
    return await msg.reply_text(text, **kw)


async def animate(msg, frames, delay=0.4):
    """Ek message ko frames se edit karke animation chalata hai. Last message return karta hai."""
    m = await msg.reply_text(frames[0])
    for f in frames[1:]:
        await asyncio.sleep(delay)
        try:
            await m.edit_text(f)
        except TelegramError:
            pass
    return m


def kbx(parent, *rows):
    """Menu keyboard: custom options last 'Back' row se pehle jodta hai."""
    return kb(*rows[:-1], *cu_rows(parent), rows[-1])


MAIN_DEFAULTS = [
    ("f", "🔵 👥 Followers"),
    ("p", "🟣 🧩 Panel"),
    ("feat:login", "🟢 📱 WhatsApp / Telegram Login"),
    ("feat:otp", "🟠 🔐 OTP Verification Service"),
    ("feat:qr", "🟡 🔳 Generate QR"),
    ("feat:unsub", "🔴 🚫 Unsubscribe Issue"),
]


def main_kb():
    b = [(db["labels"].get(c, t), c) for c, t in MAIN_DEFAULTS]
    rows = [[b[0], b[1]], [b[2]], [b[3]], [b[4]], [b[5]]]
    rows += cu_rows("main")
    return kb(*rows)


def join_kb():
    return M([[B("📢 Join Channel", url=CHANNEL_URL)],
              [B("✅ I have joined", callback_data="chk")]])


async def show(q, text, markup=None):
    try:
        await q.edit_message_text(text, reply_markup=markup)
    except TelegramError as e:
        if "not modified" in str(e).lower():
            return
        await q.message.reply_text(text, reply_markup=markup)


async def is_joined(bot, uid):
    if is_admin(uid):
        return True
    try:
        m = await bot.get_chat_member(CHANNEL, uid)
        if m.status in (ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR,
                        ChatMemberStatus.OWNER):
            return True
        return m.status == ChatMemberStatus.RESTRICTED and getattr(m, "is_member", False)
    except TelegramError as e:
        log.warning("join check failed (bot channel me admin hai?): %s", e)
        return False


def pack_title(key):
    tier = "Cheap" if key.startswith("c") else "High Quality"
    return f"Instagram {PACKS[key]} Followers ({tier})"


def custom_of(key):
    return db["custom"].get(key[3:]) if key.startswith("cu_") else None


def title_of(key):
    c = custom_of(key)
    if c:
        return c["name"]
    return pack_title(key) if key in PACKS else TITLES.get(key, key)


def price_of(key):
    c = custom_of(key)
    if c:
        return c["price"]
    return db["prices"].get(key, 0)


def lbl_of(k):
    c = custom_of(k)
    return c["name"] if c else LABELS.get(k, k)


# ---------- item-wise QR ----------
def qr_of(key):
    """Item ka apna QR, nahi to global QR."""
    return db["qrs"].get(key) or db["qr"]


def qr_keys():
    keys = (list(PACKS) + ["custom_c", "custom_h", "u10", "u30", "sp"]
            + MAINT_KEYS + ["cu_" + c for c in db["custom"]])
    return list(dict.fromkeys(keys))


def qr_label(k):
    return QR_EXTRA.get(k) or lbl_of(k)


# ---------- online admin UPI QR ----------
def active_admin():
    """Jo admin abhi online hai (aur UPI set hai) usko return karta hai.
    Ek se zyada online hon to jo sabse last me online hua wahi."""
    for a in reversed(db["online"]):
        if is_admin(a) and db["upis"].get(str(a)):
            return a
    return None


def upi_qr_image(upi, amount):
    """Fixed amount wala UPI QR (PNG, BytesIO)."""
    url = f"upi://pay?pa={quote(upi)}&am={fmt(amount)}&cu=INR"
    buf = io.BytesIO()
    qrcode.make(url).save(buf)
    buf.seek(0)
    return buf


def online_status():
    rows = [f"🟢 <code>{a}</code> • <code>{esc(db['upis'].get(str(a), '-'))}</code>"
            for a in db["online"] if is_admin(a)]
    cur = active_admin()
    txt = "\n".join(rows) if rows else "🔴 Koi admin online nahi (Item/Global QR use hoga)"
    act = f"\n\n✅ Abhi active: <code>{db['upis'][str(cur)]}</code>" if cur else ""
    return head("🟢 Online Admins") + txt + act


async def verify_payment(utr, amount):
    """Bank SMS webhook se db['payments'] me UTR->amount aata hai.
    1 minute tak check karta hai. Na mile to order admin ke paas manual approval me jata hai."""
    for _ in range(6):
        p = db["payments"].get(utr)
        if p is not None and p >= float(amount):
            return True
        await asyncio.sleep(10)
    return False


async def sms_hook(request):
    """Phone ka SMS forwarder yaha SMS bhejta hai:  http://SERVER_IP:PORT/sms?key=SECRET"""
    if request.query.get("key") != WEBHOOK_SECRET:
        return web.Response(status=403, text="forbidden")
    body = (await request.text()) + " " + request.query.get("msg", "")
    low = body.lower()
    if not any(w in low for w in ("credit", "received", "deposit")):
        return web.Response(text="ignored")
    utrs = set(re.findall(r"(?<!\d)\d{12}(?!\d)", body))
    am = re.search(r"(?:\brs\.?|\binr|₹)\s*([\d,]+(?:\.\d+)?)", low)
    if not utrs or not am:
        log.info("SMS parse fail: %s", body[:200])
        return web.Response(text="no utr/amount")
    amt = float(am.group(1).replace(",", ""))
    for u in utrs:
        db["payments"][u] = amt
    save_db()
    tg = request.app["tg"]
    for o in list(db["orders"].values()):
        if o["status"] == "pending" and o["utr"] in utrs and amt >= float(o["amount"]):
            o["status"] = "approved"
            try:
                await deliver(tg.bot, o)
            except TelegramError as e:
                log.warning("deliver fail: %s", e)
            await notify_admins(tg.bot, "🤖 Auto-verified (SMS)\n" + order_text(o))
    return web.Response(text="ok")


async def post_init(app):
    if not AUTO_VERIFY:
        return
    w = web.Application()
    w["tg"] = app
    w.router.add_post("/sms", sms_hook)
    w.router.add_get("/sms", sms_hook)
    runner = web.AppRunner(w)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", WEBHOOK_PORT).start()
    log.info("SMS webhook on port %s", WEBHOOK_PORT)


# ---------- order / delivery ----------
def order_text(o):
    st = {"pending": "⏳ Pending", "approved": "✅ Approved", "done": "✅ Completed",
          "rejected": "❌ Rejected"}.get(o["status"], o["status"])
    rcv = f"\n🏦 Paid to: <code>{esc(o['upi'])}</code>" if o.get("upi") else ""
    return (head(f"🧾 Order #{o['id']}") +
            f"👤 <a href=\"tg://user?id={o['uid']}\">{esc(o['name'])}</a>  (<code>{o['uid']}</code>)\n"
            f"🛍 {esc(o['title'])}\n💰 <b>₹{fmt(o['amount'])}</b>\n"
            f"🔗 {esc(o.get('link') or '-')}\n🧷 UTR: <code>{o['utr']}</code>{rcv}\n"
            f"📌 {st}")


def order_kb(oid):
    return kb([("✅ Approve", f"ap:{oid}"), ("❌ Reject", f"rj:{oid}")])


async def notify_admins(bot, text, markup=None, only=None):
    """only = us admin ko hi bhejo jiske UPI par payment aaya; na chale to sabko."""
    targets = [only] if only and is_admin(only) else all_admins()
    sent = False
    for a in targets:
        try:
            await bot.send_message(a, text, parse_mode=ParseMode.HTML, reply_markup=markup)
            sent = True
        except TelegramError as e:
            log.warning("admin notify failed %s: %s", a, e)
    if not sent and targets != all_admins():
        for a in all_admins():
            try:
                await bot.send_message(a, text, parse_mode=ParseMode.HTML, reply_markup=markup)
            except TelegramError as e:
                log.warning("admin notify failed %s: %s", a, e)


async def deliver(bot, o):
    uid = o["uid"]
    if o["follower"]:
        await send(bot, uid, head("🎉 Payment Verified") + "Aapka order process me hai.\nJaldi complete ho jayega 🚀", effect="party")
        o["status"] = "done"
        save_db()
        return True
    d = db["delivery"].get(o["key"])
    if not d:
        await bot.send_message(uid, head("🎉 Payment Verified") + "Aapka item thodi der me mil jayega ⏳")
        await notify_admins(bot, f"⚠️ Order #{o['id']}: <b>{esc(o['title'])}</b> ki delivery set nahi hai. /admin → Set Delivery.")
        return False
    if d["type"] == "file":
        await bot.send_document(uid, d["value"], caption=d.get("caption") or "✅ Payment verified. Ye lo aapka item.", parse_mode=None)
    elif d["type"] == "photo":
        await bot.send_photo(uid, d["value"], caption=d.get("caption") or "✅ Payment verified.", parse_mode=None)
    else:
        await send(bot, uid, "🎉 Payment Verified! 🎊\n🔹━━━━━━━━━━━━━━🔹\n\n" + d["value"], effect="party", parse_mode=None)
    o["status"] = "done"
    save_db()
    return True


# ---------- user flow ----------
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    if u.id not in db["users"]:
        db["users"].append(u.id)
        save_db()
    ctx.user_data.clear()
    if not await is_joined(ctx.bot, u.id):
        await update.message.reply_text(JOIN_TEXT, reply_markup=join_kb())
        return
    anim = await animate(update.message, ["✨", "🌟 Loading ▰▱▱▱▱", "🚀 Loading ▰▰▰▱▱",
                                          "🔥 Loading ▰▰▰▰▱", "🎉 Ready ▰▰▰▰▰"], delay=0.35)
    try:
        await anim.delete()
    except TelegramError:
        pass
    await reply(update.message, main_text(), effect="fire", reply_markup=main_kb())


async def begin_purchase(q, ctx, key):
    c = custom_of(key)
    cart = {"key": key, "title": title_of(key), "amount": price_of(key),
            "follower": key in FOLLOWER_KEYS, "ask_link": bool(c and c.get("link"))}
    ctx.user_data["cart"] = cart
    if cart["follower"] or cart["ask_link"]:
        ctx.user_data["state"] = "link"
        await show(q, head("📦 Order Details") + f"🛍 <b>Item:</b> {esc(cart['title'])}\n💰 <b>Price:</b> ₹{fmt(cart['amount'])}\n\n"
                      "🔗 Jis account par service chahiye uska <b>username / link</b> bhejein 👇",
                   kb([("❌ Cancel", "home")]))
    else:
        ctx.user_data.pop("state", None)
        await send_payment(q.message, ctx)


async def send_payment(msg, ctx):
    cart = ctx.user_data["cart"]
    link = f"🔗 <b>Account:</b> {esc(cart['link'])}\n" if cart.get("link") else ""
    caption = (head("💳 Payment Details") +
               f"🛍 <b>Item:</b> {esc(cart['title'])}\n💰 <b>Amount:</b> ₹{fmt(cart['amount'])}\n{link}{LINE}\n"
               "1️⃣ QR scan karke <b>exact amount</b> pay karein\n"
               "2️⃣ <b>Confirm Payment</b> dabayein\n3️⃣ Phir apna <b>UTR number</b> bhejein")
    buttons = kb([("✅ Confirm Payment", "payok")], [("❌ Cancel", "paycancel")])

    # 1) Online admin ke UPI ID se fixed-amount QR (default)
    adm = active_admin()
    cart.pop("pay_admin", None)
    cart.pop("pay_upi", None)
    if adm:
        upi = db["upis"][str(adm)]
        try:
            photo = upi_qr_image(upi, cart["amount"])
            cart["pay_admin"] = adm
            cart["pay_upi"] = upi
            await msg.reply_photo(photo, caption=caption, reply_markup=buttons)
            return
        except Exception as e:  # noqa
            log.exception("UPI QR banane me error: %s", e)

    # 2) Koi admin online nahi -> Item QR / Global QR
    qr = qr_of(cart["key"])
    if qr:
        await msg.reply_photo(qr, caption=caption, reply_markup=buttons)
    else:
        await msg.reply_text(caption + "\n\n⚠️ QR abhi set nahi hai, admin se contact karo.",
                             reply_markup=kb([("❌ Cancel", "paycancel")]))


async def on_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    d = q.data
    uid = q.from_user.id

    if d.startswith(("ad:", "ap:", "rj:")):
        if not is_admin(uid):
            await q.answer("Admin only", show_alert=True)
            return
        if d.startswith("ad:"):
            await admin_cb(q, ctx, d[3:])
        else:
            await order_action(q, ctx, d)
        return

    if d == "chk":
        if await is_joined(ctx.bot, uid):
            await q.answer()
            await show(q, main_text(), main_kb())
        else:
            await q.answer("❌ Aapne abhi tak channel join nahi kiya!", show_alert=True)
        return

    if not await is_joined(ctx.bot, uid):
        await q.answer()
        await show(q, JOIN_TEXT, join_kb())
        return
    await q.answer()
    P = db["prices"]

    if d == "home":
        ctx.user_data.clear()
        await show(q, main_text(), main_kb())

    # ----- followers -----
    elif d == "f":
        await show(q, head("👥 Followers") + "Platform select karein 👇", kbx("f",
            [("🟣 📸 Instagram", "f:ig")], [("🟢 💬 WhatsApp", "feat:fwa")],
            [("🔵 ✈️ Telegram", "feat:ftg")], [("⬅️ Back", "home")]))
    elif d == "f:ig":
        await show(q, head("📸 Instagram Followers") + "⚠️ <b>High Drop and No Refill</b>\n\nPlan type select karein 👇", kbx("f:ig",
            [("🟢 💸 Cheap", "f:c")], [("🔵 💎 High Price", "f:h")], [("⬅️ Back", "f")]))
    elif d == "f:c":
        await show(q, head("💸 Cheap Plans") + "⚠️ High Drop • No Refill\n\nPack select karein 👇", kbx("f:c",
            [(f"🟢 100 Followers  •  ₹{fmt(P['c100'])}", "buy:c100")],
            [(f"🟡 500 Followers  •  ₹{fmt(P['c500'])}", "buy:c500")],
            [(f"🟠 1000 Followers  •  ₹{fmt(P['c1000'])}", "buy:c1000")],
            [("✍️ Custom Quantity", "cq:c")], [("⬅️ Back", "f:ig")]))
    elif d == "f:h":
        await show(q, head("💎 Premium Plans") + "✅ Refill: Yes  •  ✅ Non Drop\n\nPack select karein 👇", kbx("f:h",
            [(f"💎 1000 Followers  •  ₹{fmt(P['h1000'])}", "buy:h1000")],
            [("✍️ Custom Quantity", "cq:h")], [("⬅️ Back", "f:ig")]))
    elif d in ("cq:c", "cq:h"):
        tier = d[-1]
        rate = P["rate_" + tier]
        ctx.user_data["state"] = "qty"
        ctx.user_data["tier"] = tier
        await show(q, head("✍️ Custom Quantity") + "Kitne followers chahiye? Sirf <b>number</b> bhejein.\n\n"
                      f"📏 Min: {MIN_QTY}  •  Max: {MAX_QTY}\n💰 Rate: 1000 followers = ₹{fmt(rate * 1000)}",
                   kb([("❌ Cancel", "home")]))

    # ----- panel -----
    elif d == "p":
        await show(q, head("🧩 Panel") + "Type select karein 👇", kbx("p",
            [("🟠 ⚠️ Unsafe", "p:u")], [("🟢 🛡 Safe", "p:s")], [("⬅️ Back", "home")]))
    elif d == "p:u":
        await show(q, head("⚠️ Unsafe Panel") + "Plan select karein 👇", kbx("p:u",
            [(f"🔓 Unsafe  •  ₹{fmt(P['u10'])}", "buy:u10")],
            [(f"🔓 Unsafe  •  ₹{fmt(P['u30'])}", "buy:u30")], [("⬅️ Back", "p")]))
    elif d == "p:s":
        l2 = "🛠 Under Maintenance" if db["maint"]["sf2"] else f"🔐 Safe Option 2 • ₹{fmt(P['sf2'])}"
        await show(q, head("🛡 Safe Panel") + "Plan select karein 👇", kbx("p:s",
            [(f"♾ Permanent • ₹{fmt(P['sp'])}", "buy:sp")], [(l2, "feat:sf2")], [("⬅️ Back", "p")]))

    # ----- buy / feature -----
    elif d.startswith("buy:"):
        key = d[4:]
        if key in PACKS or key in ("u10", "u30", "sp"):
            await begin_purchase(q, ctx, key)
    elif d.startswith("feat:"):
        key = d[5:]
        if db["maint"].get(key, True):
            await show(q, MAINT_TEXT, kb([("⬅️ Back", "home")]))
        elif P.get(key, 0) <= 0:
            await show(q, "ℹ️ Is option ka price abhi set nahi hai, admin se contact karo.", kb([("⬅️ Back", "home")]))
        else:
            await begin_purchase(q, ctx, key)

    elif d.startswith("cu:"):
        cid = d[3:]
        c = db["custom"].get(cid)
        if not c or not c.get("on", True):
            await show(q, MAINT_TEXT, kb([("⬅️ Back", "home")]))
        elif c["price"] <= 0:
            await show(q, "ℹ️ Is option ka price abhi set nahi hai, admin se contact karo.", kb([("⬅️ Back", "home")]))
        else:
            await begin_purchase(q, ctx, "cu_" + cid)

    # ----- payment -----
    elif d == "payok":
        if not ctx.user_data.get("cart"):
            await q.message.reply_text("Session expire ho gaya, /start karo.")
            return
        ctx.user_data["state"] = "utr"
        try:
            await q.message.edit_reply_markup(reply_markup=None)
        except TelegramError:
            pass
        await q.message.reply_text(head("🧾 UTR Verification") + "📩 <b>Pls send UTR No</b> (12 digit) 👇\n\n"
                                   "<i>Payment app ke Transaction Details se UTR / Ref No copy karein.</i>")
    elif d == "paycancel":
        ctx.user_data.clear()
        try:
            await q.message.delete()
        except TelegramError:
            pass
        await ctx.bot.send_message(q.message.chat_id, main_text(), reply_markup=main_kb())


async def on_msg(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    uid = msg.from_user.id
    state = ctx.user_data.get("state", "")

    if state.startswith("adm_") and is_admin(uid):
        await admin_input(update, ctx, state)
        return
    if not await is_joined(ctx.bot, uid):
        await msg.reply_text(JOIN_TEXT, reply_markup=join_kb())
        return
    text = (msg.text or "").strip()

    if state == "qty":
        try:
            qty = int(text.replace(",", ""))
        except ValueError:
            await msg.reply_text("❌ Sirf number bhejo, jaise 1000")
            return
        if not MIN_QTY <= qty <= MAX_QTY:
            await msg.reply_text(f"❌ Quantity {MIN_QTY} se {MAX_QTY} ke beech honi chahiye.")
            return
        tier = ctx.user_data.get("tier", "c")
        rate = db["prices"]["rate_" + tier]
        amt = max(1, math.ceil(round(qty * rate, 4)))
        tname = "Cheap" if tier == "c" else "High Quality"
        ctx.user_data["cart"] = {"key": f"custom_{tier}", "title": f"Instagram {qty} Followers ({tname})",
                                 "amount": amt, "follower": True}
        ctx.user_data["state"] = "link"
        await msg.reply_text(head("🧮 Price Calculated") + f"📦 <b>{qty}</b> followers\n💰 <b>Total: ₹{amt}</b>\n"
                             f"<i>Rate: 1000 followers = ₹{fmt(rate * 1000)}</i>\n\n"
                             "🔗 Ab account ka <b>username / link</b> bhejein 👇")

    elif state == "link":
        if not text:
            await msg.reply_text("Username ya link text me bhejo.")
            return
        ctx.user_data["cart"]["link"] = text[:200]
        ctx.user_data.pop("state", None)
        await send_payment(msg, ctx)

    elif state == "utr":
        utr = re.sub(r"\s", "", text)
        if not re.fullmatch(r"\d{12}", utr):
            await msg.reply_text("❌ <b>Invalid UTR</b>\n12 digit ka UTR number bhejein.")
            return
        if utr in db["used_utr"]:
            await msg.reply_text("⚠️ <b>Ye UTR pehle use ho chuka hai.</b>\nSahi UTR bhejein.")
            return
        cart = ctx.user_data.get("cart")
        if not cart:
            await msg.reply_text("Session expire ho gaya, /start karo.")
            return
        db["seq"] += 1
        oid = str(db["seq"])
        o = {"id": oid, "uid": uid, "name": msg.from_user.full_name, "key": cart["key"],
             "title": cart["title"], "amount": cart["amount"], "follower": cart["follower"],
             "link": cart.get("link", ""), "utr": utr, "status": "pending", "time": int(time.time()),
             "admin": cart.get("pay_admin"), "upi": cart.get("pay_upi", "")}
        db["orders"][oid] = o
        db["used_utr"].append(utr)
        save_db()
        ctx.user_data.clear()

        if AUTO_VERIFY:
            await msg.reply_text(head("⏳ Verifying Payment") + "Aapka payment check ho raha hai.\nKripya <b>1 minute</b> wait karein...")
            try:
                paid = await verify_payment(utr, o["amount"])
            except Exception as e:  # noqa
                log.exception("verify_payment error: %s", e)
                paid = None
            if o["status"] != "pending":   # SMS webhook ne pehle hi handle kar diya
                return
            if paid:
                o["status"] = "approved"
                await reply(msg, "🎉 <b>Payment mil gaya!</b> 🎊", effect="party")
                await deliver(ctx.bot, o)
                await notify_admins(ctx.bot, "🤖 Auto-verified\n" + order_text(o), only=o.get("admin"))
                return
        m = await animate(msg, ["🔍 Checking ▱▱▱▱▱", "🔍 Checking ▰▰▱▱▱", "🔍 Checking ▰▰▰▰▱", "📨 Received ▰▰▰▰▰"], delay=0.4)
        try:
            await m.edit_text(head("⏳ UTR Received") + "Aapka payment verify ho raha hai.\nApprove hote hi aapko item mil jayega ✅")
        except TelegramError:
            pass
        await notify_admins(ctx.bot, order_text(o), order_kb(oid), only=o.get("admin"))
    else:
        await msg.reply_text(main_text(), reply_markup=main_kb())


# ---------- admin ----------
def admin_kb(uid=None):
    on = uid in db["online"]
    return kb(
        [(("🟢 Online" if on else "🔴 Offline") + " (tap = toggle)", "ad:on"), ("🆔 My UPI ID", "ad:upi")],
        [("🟦 🖼 Set QR (Global)", "ad:qr"), ("🟪 🖼 Item QR", "ad:iq")],
        [("🟩 💰 Edit Prices", "ad:pr"), ("🟧 📦 Set Delivery", "ad:dl")],
        [("🟨 🧱 Options (Add/Edit)", "ad:ops"), ("🟥 ✏️ Texts & Buttons", "ad:tx")],
        [("🛠 Maintenance On/Off", "ad:mt")],
        [("📋 Pending Orders", "ad:po"), ("📊 Stats", "ad:st")],
        [("📢 Broadcast", "ad:bc"), ("👮 Admins", "ad:am")],
    )


async def admin_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    ctx.user_data.clear()
    await update.message.reply_text(ADMIN_TEXT, reply_markup=admin_kb(update.effective_user.id))


async def admin_cb(q, ctx, a):
    await q.answer()
    ctx.user_data.pop("state", None)
    back = kb([("⬅️ Admin Panel", "ad:home")])
    me = q.from_user.id

    if a == "home":
        await show(q, ADMIN_TEXT, admin_kb(me))
    elif a == "upi":
        cur = db["upis"].get(str(me))
        ctx.user_data["state"] = "adm_upi"
        await show(q, head("🆔 My UPI ID") + f"Abhi: <code>{esc(cur) if cur else 'set nahi hai'}</code>\n\n"
                      "Apna UPI ID bhejo (jaise <code>name@bank</code>).\n"
                      "Online hone par user ko isi UPI ID ka QR dikhega.", back)
    elif a == "on":
        if me in db["online"]:
            db["online"].remove(me)
        else:
            if not db["upis"].get(str(me)):
                await show(q, "⚠️ Online hone se pehle apna UPI ID set karo.",
                           kb([("🆔 Set My UPI ID", "ad:upi")], [("⬅️ Admin Panel", "ad:home")]))
                return
            db["online"].append(me)
        save_db()
        await show(q, online_status(), kb(
            [(("🔴 Offline jao" if me in db["online"] else "🟢 Online jao"), "ad:on")],
            [("⬅️ Admin Panel", "ad:home")]))
    elif a == "qr":
        ctx.user_data["state"] = "adm_qr"
        await show(q, "🖼 Naya <b>global</b> payment QR (photo) bhejo.\n(Jab koi admin online nahi hoga aur item ka alag QR nahi hoga, tab ye use hoga)", back)
    elif a == "iq":
        rows = [[(("✅ " if k in db["qrs"] else "➖ ") + qr_label(k), f"ad:iqk:{k}")] for k in qr_keys()]
        rows.append([("⬅️ Admin Panel", "ad:home")])
        await show(q, "🖼 Kis item ka QR set karna hai?\n(✅ = apna QR set hai, ➖ = global QR use hoga)\n"
                      "ℹ️ Admin online ho to uska UPI QR in sabse upar chalta hai.", kb(*rows))
    elif a.startswith("iqk:"):
        k = a[4:]
        ctx.user_data["state"] = f"adm_iqr:{k}"
        await show(q, f"🖼 <b>{esc(qr_label(k))}</b> ka QR (photo) bhejo.",
                   kb([("🗑 Is item ka QR hatao", f"ad:iqd:{k}")], [("⬅️ Item QR", "ad:iq")]))
    elif a.startswith("iqd:"):
        db["qrs"].pop(a[4:], None)
        save_db()
        ctx.user_data.pop("state", None)
        await show(q, "✅ QR hata diya, ab global QR use hoga.", kb([("⬅️ Item QR", "ad:iq")]))
    elif a == "pr":
        keys = list(LABELS)
        rows = []
        for i in range(0, len(keys), 2):
            rows.append([(f"{LABELS[k]} = {fmt(db['prices'][k])}", f"ad:pk:{k}") for k in keys[i:i + 2]])
        rows.append([("⬅️ Admin Panel", "ad:home")])
        await show(q, "💰 Kis ka price badalna hai?", kb(*rows))
    elif a.startswith("pk:"):
        k = a[3:]
        ctx.user_data["state"] = f"adm_price:{k}"
        await show(q, f"{esc(lbl_of(k))} ka naya price/rate bhejo (abhi: {fmt(db['prices'].get(k, 0))}).", back)
    elif a == "dl":
        rows = [[(("✅ " if k in db["delivery"] else "➖ ") + LABELS[k], f"ad:dk:{k}")] for k in DELIV_KEYS]
        rows.append([("⬅️ Admin Panel", "ad:home")])
        await show(q, "📦 Kis item ki delivery set karni hai?\n(payment verify hone par user ko ye milega)", kb(*rows))
    elif a.startswith("dk:"):
        k = a[3:]
        ctx.user_data["state"] = f"adm_deliv:{k}"
        await show(q, f"📦 {esc(lbl_of(k))}: APK/file ya text bhejo.\n(file ke saath caption bhi de sakte ho)", back)
    elif a == "mt" or a.startswith("mtt:"):
        if a.startswith("mtt:"):
            k = a[4:]
            if k in db["maint"]:
                db["maint"][k] = not db["maint"][k]
                save_db()
        rows = [[(("🛠 Maintenance" if db["maint"][k] else "🟢 Live") + " • " + LABELS[k], f"ad:mtt:{k}")] for k in MAINT_KEYS]
        rows.append([("⬅️ Admin Panel", "ad:home")])
        await show(q, "🛠 Tap karke On/Off karo.\n(Live karne se pehle us item ka price + delivery set karo)", kb(*rows))
    elif a == "ops":
        rows = [[(f"{'🟢' if c.get('on', True) else '🛠'} {c['name']} • ₹{fmt(c['price'])}", f"ad:ope:{cid}")]
                for cid, c in db["custom"].items()]
        rows.append([("➕ New Option", "ad:opn")])
        rows.append([("⬅️ Admin Panel", "ad:home")])
        await show(q, "🧱 Custom Options\n(ye main menu me alag button ban kar dikhte hain)", kb(*rows))
    elif a == "opn":
        ctx.user_data["state"] = "adm_onew"
        await show(q, "➕ Naye option ka naam bhejo (button par yahi dikhega).", back)
    elif a.startswith("ope:"):
        cid = a[4:]
        c = db["custom"].get(cid)
        if not c:
            await show(q, "❌ Option nahi mila.", back)
            return
        has = "✅" if f"cu_{cid}" in db["delivery"] else "➖"
        hasq = "✅" if f"cu_{cid}" in db["qrs"] else "➖"
        txt = (head("🧱 " + esc(c['name'])) + f"💰 ₹{fmt(c['price'])}\n"
               f"Status: {'🟢 Live' if c.get('on', True) else '🛠 Maintenance'}\n"
               f"Link maangna: {'Haa' if c.get('link') else 'Nahi'}\nDelivery: {has}\nAlag QR: {hasq}\n"
               f"Jagah: {PARENTS.get(c.get('parent', 'main'), '🏠 Main Menu')}")
        await show(q, txt, kb(
            [("✏️ Naam", f"ad:opr:{cid}"), ("💰 Price", f"ad:opp:{cid}")],
            [(f"📦 Delivery {has}", f"ad:dk:cu_{cid}"), (f"🖼 QR {hasq}", f"ad:iqk:cu_{cid}")],
            [("🔁 Live/Maintenance", f"ad:opt:{cid}"), ("🔗 Link maango On/Off", f"ad:opl:{cid}")],
            [("📍 Jagah (kahan dikhe)", f"ad:opwh:{cid}")],
            [("🗑 Delete", f"ad:opd:{cid}")],
            [("⬅️ Options", "ad:ops")]))
    elif a.startswith("opwh:"):
        cid = a[5:]
        rows = [[(lab, f"ad:opsq:{cid}:{par}")] for par, lab in PARENTS.items()]
        rows.append([("⬅️ Option", f"ad:ope:{cid}")])
        await show(q, "📍 Ye option kahan dikhana hai?", kb(*rows))
    elif a.startswith("opsq:"):
        cid, _, par = a[5:].partition(":")
        c = db["custom"].get(cid)
        if c and par in PARENTS:
            c["parent"] = par
            save_db()
        await show(q, "✅ Jagah badal gayi.", kb([("⬅️ Option", f"ad:ope:{cid}")]))
    elif a.startswith("opsp:"):
        cid, _, par = a[5:].partition(":")
        c = db["custom"].get(cid)
        if not c or par not in PARENTS:
            await show(q, "❌ Option nahi mila.", back)
            return
        c["parent"] = par
        save_db()
        ctx.user_data["state"] = f"adm_deliv:cu_{cid}"
        await show(q, f"✅ Option ban gaya! Jagah: {PARENTS[par]}\n\n📦 Ab delivery bhejo (APK/file/photo ya text) jo payment ke baad user ko milega.\n"
                      "🖼 Alag QR baad me option ke andar <b>QR</b> button se set kar sakte ho.",
                   kb([("⏭ Skip (baad me)", f"ad:ope:{cid}")]))
    elif a.startswith("opr:"):
        ctx.user_data["state"] = f"adm_orn:{a[4:]}"
        await show(q, "✏️ Naya naam bhejo.", back)
    elif a.startswith("opp:"):
        ctx.user_data["state"] = f"adm_opp:{a[4:]}"
        await show(q, "💰 Naya price bhejo (₹).", back)
    elif a.startswith(("opt:", "opl:", "opd:")):
        act, cid = a[:3], a[4:]
        c = db["custom"].get(cid)
        if c:
            if act == "opt":
                c["on"] = not c.get("on", True)
            elif act == "opl":
                c["link"] = not c.get("link", False)
            else:
                db["custom"].pop(cid, None)
                db["delivery"].pop(f"cu_{cid}", None)
                db["qrs"].pop(f"cu_{cid}", None)
            save_db()
        nxt = "ad:ops" if act == "opd" else f"ad:ope:{cid}"
        await show(q, "✅ Update ho gaya.", kb([("⬅️ Wapas", nxt)]))
    elif a == "tx":
        await show(q, head("✏️ Texts &amp; Buttons") + "Kya badalna hai?", kb(
            [("📝 Welcome/Main Text", "ad:txm")],
            [("🔤 Rename Main Buttons", "ad:rb")],
            [("⬅️ Admin Panel", "ad:home")]))
    elif a == "txm":
        ctx.user_data["state"] = "adm_text:main"
        await show(q, f"📝 Naya main-menu text bhejo.\n\nAbhi:\n{main_text()}", back)
    elif a == "rb":
        rows = [[(db["labels"].get(c, t), f"ad:rbk:{c}")] for c, t in MAIN_DEFAULTS]
        rows.append([("↩️ Sab Reset", "ad:rbr")])
        rows.append([("⬅️ Admin Panel", "ad:home")])
        await show(q, "🔤 Kis button ka naam badalna hai?", kb(*rows))
    elif a.startswith("rbk:"):
        ctx.user_data["state"] = f"adm_label:{a[4:]}"
        await show(q, "🔤 Us button ka naya naam bhejo (emoji ke saath).", back)
    elif a == "rbr":
        db["labels"].clear()
        save_db()
        await show(q, "✅ Saare button naam default ho gaye.", back)
    elif a == "am":
        if q.from_user.id not in ADMIN_IDS:
            await show(q, "❌ Sirf owner admin add/remove kar sakta hai.", back)
            return
        rows = [[("➕ Add Admin", "ad:aa")]]
        for x in db["admins"]:
            rows.append([(f"🗑 Remove {x}", f"ad:ar:{x}")])
        rows.append([("⬅️ Admin Panel", "ad:home")])
        owners = ", ".join(str(x) for x in ADMIN_IDS)
        await show(q, f"👮 Admins\n\nOwner(s): {owners}\nExtra admins: {len(db['admins'])}", kb(*rows))
    elif a == "aa":
        if q.from_user.id not in ADMIN_IDS:
            return
        ctx.user_data["state"] = "adm_addadmin"
        await show(q, "➕ Naye admin ki Telegram numeric ID bhejo.\n(ID @userinfobot se mil jati hai. Us user ne bot /start kiya hona chahiye.)", back)
    elif a.startswith("ar:"):
        if q.from_user.id not in ADMIN_IDS:
            return
        x = int(a[3:])
        if x in db["admins"]:
            db["admins"].remove(x)
        if x in db["online"]:
            db["online"].remove(x)
        save_db()
        await show(q, f"✅ Admin {x} hata diya.", back)
    elif a == "bc":
        ctx.user_data["state"] = "adm_bc"
        await show(q, "📢 Jo message sabko bhejna hai wo bhejo (text/photo/file).", back)
    elif a == "st":
        orders = db["orders"].values()
        done = [o for o in orders if o["status"] in ("done", "approved")]
        pend = [o for o in orders if o["status"] == "pending"]
        rev = sum(o["amount"] for o in done)
        await show(q, head("📊 Statistics") + f"👥 Users: <b>{len(db['users'])}</b>\n🧾 Orders: <b>{len(db['orders'])}</b>\n"
                      f"⏳ Pending: <b>{len(pend)}</b>\n✅ Done: <b>{len(done)}</b>\n💰 Revenue: <b>₹{fmt(rev)}</b>", back)
    elif a == "po":
        pend = [o for o in db["orders"].values() if o["status"] == "pending"][-10:]
        if not pend:
            await show(q, "✅ Koi pending order nahi.", back)
            return
        await show(q, f"📋 {len(pend)} pending order(s) 👇", back)
        for o in pend:
            await ctx.bot.send_message(q.message.chat_id, order_text(o), parse_mode=ParseMode.HTML,
                                       reply_markup=order_kb(o["id"]))


async def order_action(q, ctx, d):
    act, oid = d.split(":", 1)
    o = db["orders"].get(oid)
    if not o or o["status"] != "pending":
        await q.answer("Ye order already handle ho chuka hai.", show_alert=True)
        return
    await q.answer()
    if act == "ap":
        o["status"] = "approved"
        save_db()
        try:
            await deliver(ctx.bot, o)
        except TelegramError as e:
            await q.message.reply_text(f"⚠️ Delivery error: {esc(e)}")
        verdict = "✅ Approved"
    else:
        o["status"] = "rejected"
        save_db()
        try:
            await ctx.bot.send_message(o["uid"], head("❌ Payment Failed") + "Aapka payment verify nahi ho paya.\nSahi UTR ke saath admin se contact karein.")
        except TelegramError:
            pass
        verdict = "❌ Rejected"
    try:
        await q.edit_message_text(q.message.text_html + f"\n\n{verdict} by {esc(q.from_user.first_name)}",
                                  parse_mode=ParseMode.HTML)
    except TelegramError:
        pass


async def admin_input(update, ctx, state):
    msg = update.message
    kind, _, key = state.partition(":")
    back = kb([("⬅️ Admin Panel", "ad:home")])

    if kind == "adm_upi":
        t = (msg.text or "").strip()
        if not UPI_RE.match(t):
            await msg.reply_text("❌ Sahi UPI ID bhejo, jaise name@bank")
            return
        db["upis"][str(msg.from_user.id)] = t
        save_db()
        ctx.user_data.pop("state", None)
        await msg.reply_text(f"✅ UPI ID set: <code>{esc(t)}</code>\nAb <b>Online</b> dabao taaki users ko ye QR dikhe.",
                             reply_markup=kb([("🟢 Online / Offline", "ad:on")], [("⬅️ Admin Panel", "ad:home")]))

    elif kind == "adm_qr":
        if not msg.photo:
            await msg.reply_text("❌ Photo bhejo.")
            return
        db["qr"] = msg.photo[-1].file_id
        save_db()
        ctx.user_data.pop("state", None)
        await msg.reply_text("✅ Global QR update ho gaya.", reply_markup=back)

    elif kind == "adm_iqr":
        if not msg.photo:
            await msg.reply_text("❌ Photo bhejo.")
            return
        db["qrs"][key] = msg.photo[-1].file_id
        save_db()
        ctx.user_data.pop("state", None)
        await msg.reply_text(f"✅ {esc(qr_label(key))} ka QR set ho gaya.",
                             reply_markup=kb([("⬅️ Item QR", "ad:iq")], [("⬅️ Admin Panel", "ad:home")]))

    elif kind == "adm_price":
        try:
            val = float((msg.text or "").strip())
            assert val >= 0
        except Exception:
            await msg.reply_text("❌ Sahi number bhejo.")
            return
        db["prices"][key] = int(val) if val == int(val) else val
        save_db()
        ctx.user_data.pop("state", None)
        await msg.reply_text(f"✅ {esc(lbl_of(key))} = {fmt(val)}", reply_markup=back)

    elif kind == "adm_deliv":
        if msg.document:
            dd = {"type": "file", "value": msg.document.file_id, "caption": msg.caption or ""}
        elif msg.photo:
            dd = {"type": "photo", "value": msg.photo[-1].file_id, "caption": msg.caption or ""}
        elif msg.text:
            dd = {"type": "text", "value": msg.text}
        else:
            await msg.reply_text("❌ File, photo ya text bhejo.")
            return
        db["delivery"][key] = dd
        save_db()
        ctx.user_data.pop("state", None)
        await msg.reply_text(f"✅ {esc(lbl_of(key))} ki delivery set ho gayi.", reply_markup=back)

    elif kind == "adm_onew":
        t = (msg.text or "").strip()
        if not t:
            await msg.reply_text("❌ Naam text me bhejo.")
            return
        ctx.user_data["newname"] = t[:40]
        ctx.user_data["state"] = "adm_onewp"
        await msg.reply_text(f"💰 '{esc(t[:40])}' ka price bhejo (₹, sirf number).")

    elif kind == "adm_onewp":
        try:
            val = float((msg.text or "").strip())
            assert val >= 0
        except Exception:
            await msg.reply_text("❌ Sahi number bhejo.")
            return
        db["cseq"] += 1
        cid = str(db["cseq"])
        db["custom"][cid] = {"name": ctx.user_data.pop("newname", "Option"),
                             "price": int(val) if val == int(val) else val, "on": True, "link": False}
        save_db()
        ctx.user_data.pop("state", None)
        rows = [[(lab, f"ad:opsp:{cid}:{par}")] for par, lab in PARENTS.items()]
        await msg.reply_text("📍 Ye option kahan dikhana hai?", reply_markup=kb(*rows))

    elif kind in ("adm_orn", "adm_opp"):
        c = db["custom"].get(key)
        ctx.user_data.pop("state", None)
        if not c:
            await msg.reply_text("❌ Option nahi mila.", reply_markup=back)
            return
        t = (msg.text or "").strip()
        if kind == "adm_orn":
            c["name"] = t[:40] or c["name"]
        else:
            try:
                val = float(t)
                assert val >= 0
            except Exception:
                ctx.user_data["state"] = state
                await msg.reply_text("❌ Sahi number bhejo.")
                return
            c["price"] = int(val) if val == int(val) else val
        save_db()
        await msg.reply_text("✅ Update ho gaya.", reply_markup=kb([("⬅️ Option", f"ad:ope:{key}")]))

    elif kind == "adm_text":
        if not msg.text:
            await msg.reply_text("❌ Text bhejo.")
            return
        db["texts"]["main"] = msg.text
        save_db()
        ctx.user_data.pop("state", None)
        await msg.reply_text("✅ Main text update ho gaya.", reply_markup=back)

    elif kind == "adm_label":
        t = (msg.text or "").strip()
        if not t:
            await msg.reply_text("❌ Naam text me bhejo.")
            return
        db["labels"][key] = t[:40]
        save_db()
        ctx.user_data.pop("state", None)
        await msg.reply_text("✅ Button ka naam update ho gaya.", reply_markup=back)

    elif kind == "adm_addadmin":
        if msg.from_user.id not in ADMIN_IDS:
            return
        t = (msg.text or "").strip()
        if not t.isdigit():
            await msg.reply_text("❌ Sirf numeric ID bhejo.")
            return
        nid = int(t)
        if nid in ADMIN_IDS or nid in db["admins"]:
            await msg.reply_text("ℹ️ Ye pehle se admin hai.", reply_markup=back)
        else:
            db["admins"].append(nid)
            save_db()
            ctx.user_data.pop("state", None)
            await msg.reply_text(f"✅ {nid} ab admin hai. Wo /admin use kar sakta hai.", reply_markup=back)
            try:
                await ctx.bot.send_message(nid, "✅ Aapko bot ka admin bana diya gaya hai. /admin kholo.")
            except TelegramError:
                pass

    elif kind == "adm_bc":
        ctx.user_data.pop("state", None)
        users = list(db["users"])
        await msg.reply_text(f"📢 Broadcast start ({len(users)} users)...")

        async def run():
            ok = fail = 0
            for u in users:
                try:
                    await ctx.bot.copy_message(u, msg.chat_id, msg.message_id)
                    ok += 1
                except TelegramError:
                    fail += 1
                await asyncio.sleep(0.05)
            await ctx.bot.send_message(msg.chat_id, f"✅ Broadcast done\nSent: {ok}\nFailed: {fail}")

        ctx.application.create_task(run())


async def on_error(update, ctx):
    log.error("Update error", exc_info=ctx.error)


def main():
    if not BOT_TOKEN:
        raise SystemExit("BOT_TOKEN set nahi hai. Run: BOT_TOKEN=xxxx python3 shop_bot.py")
    app = Application.builder().token(BOT_TOKEN).defaults(Defaults(parse_mode=ParseMode.HTML)).post_init(post_init).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_cmd))
    app.add_handler(CallbackQueryHandler(on_cb))
    app.add_handler(MessageHandler(~filters.COMMAND, on_msg))
    app.add_error_handler(on_error)
    log.info("Bot started")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
