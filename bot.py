import logging
import json
import os
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from telegram import (
    Update, KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler,
    MessageHandler, filters, ContextTypes, ConversationHandler
)

from zoom_api import create_zoom_meeting
from config import TELEGRAM_TOKEN, ADMIN_TELEGRAM_ID, DATA_FILE, PROXY_URL

TASHKENT = ZoneInfo("Asia/Tashkent")

logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)

WAITING_PHONE_TO_ADD    = 1
WAITING_PHONE_TO_REMOVE = 2
WAITING_ZOOM_TIME       = 3

# ─────────────────────────────────────────────
# Ma'lumotlar
# ─────────────────────────────────────────────

def load_data() -> dict:
    folder = os.path.dirname(DATA_FILE)
    if folder:
        os.makedirs(folder, exist_ok=True)
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r") as f:
            return json.load(f)
    return {"phones": [], "users": {}}

def save_data(data: dict):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def normalize(phone: str) -> str:
    phone = re.sub(r"[\s\-\(\)]", "", phone.strip())
    if not phone.startswith("+"):
        if phone.startswith("998"):
            phone = "+" + phone
        elif len(phone) == 9:
            phone = "+998" + phone
    return phone

def is_admin(user_id: int) -> bool:
    return user_id == ADMIN_TELEGRAM_ID

def is_registered(telegram_id: int) -> bool:
    data = load_data()
    return str(telegram_id) in data.get("users", {}) or is_admin(telegram_id)

# ─────────────────────────────────────────────
# Klaviaturalar
# ─────────────────────────────────────────────

def admin_kb():
    return ReplyKeyboardMarkup([
        ["➕ Qoshish", "🗑 Ochirish"],
        ["📋 Royxat",  "🎥 Zoom"]
    ], resize_keyboard=True)

def user_kb():
    return ReplyKeyboardMarkup([
        ["🎥 Zoom link olish"]
    ], resize_keyboard=True)

def contact_kb():
    return ReplyKeyboardMarkup([
        [KeyboardButton("📱 Raqamimni yuborish", request_contact=True)]
    ], resize_keyboard=True, one_time_keyboard=True)

def zoom_time_kb():
    return ReplyKeyboardMarkup([
        ["⚡ Hozir boshlash"],
        ["09:00 - 10:00", "10:00 - 11:00"],
        ["11:00 - 12:00", "14:00 - 15:00"],
        ["15:00 - 16:00", "16:00 - 17:00"],
        ["🔙 Orqaga"]
    ], resize_keyboard=True)

def back_kb():
    return ReplyKeyboardMarkup([["🔙 Orqaga"]], resize_keyboard=True)

# ─────────────────────────────────────────────
# /start
# ─────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    context.user_data.clear()

    if is_admin(user.id):
        await update.message.reply_text(
            "👋 Salom, Admin!\nQuyidagi tugmalardan foydalaning:",
            reply_markup=admin_kb()
        )
        return ConversationHandler.END

    if is_registered(user.id):
        await update.message.reply_text(
            f"👋 Salom, {user.first_name}!\nZoom link olish uchun tugmani bosing:",
            reply_markup=user_kb()
        )
        return ConversationHandler.END

    await update.message.reply_text(
        f"👋 Salom, {user.first_name}!\n\n"
        "Botdan foydalanish uchun telefon raqamingizni yuboring 👇",
        reply_markup=contact_kb()
    )
    return ConversationHandler.END

# ─────────────────────────────────────────────
# Kontakt
# ─────────────────────────────────────────────

async def handle_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user  = update.effective_user
    phone = normalize(update.message.contact.phone_number)
    data  = load_data()

    if phone in [normalize(p) for p in data["phones"]]:
        data["users"][str(user.id)] = phone
        save_data(data)
        await update.message.reply_text(
            f"✅ Tasdiqlandi! Xush kelibsiz, {user.first_name}!\n"
            "Zoom link olish uchun tugmani bosing 👇",
            reply_markup=user_kb()
        )
    else:
        await update.message.reply_text(
            "❌ Raqamingiz royxatda yoq.\n"
            "Iltimos, admin bilan boglanin.",
            reply_markup=ReplyKeyboardRemove()
        )

# ─────────────────────────────────────────────
# Zoom
# ─────────────────────────────────────────────

def parse_time(start_str: str, end_str: str):
    try:
        sh, sm = map(int, start_str.split(":"))
        eh, em = map(int, end_str.split(":"))
    except ValueError:
        return None
    now      = datetime.now(TASHKENT)
    start_dt = now.replace(hour=sh, minute=sm, second=0, microsecond=0)
    end_dt   = now.replace(hour=eh, minute=em, second=0, microsecond=0)
    if start_dt < now:
        start_dt += timedelta(days=1)
        end_dt   += timedelta(days=1)
    if end_dt <= start_dt:
        return None
    duration_min = int((end_dt - start_dt).total_seconds() // 60)
    return start_dt, duration_min

async def zoom_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_registered(user.id):
        await update.message.reply_text("Siz royxatdan otmagansiz. /start bosing.")
        return ConversationHandler.END
    await update.message.reply_text(
        "Qaysi vaqtga meeting kerak?",
        reply_markup=zoom_time_kb()
    )
    return WAITING_ZOOM_TIME

async def zoom_time_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    user = update.effective_user

    if text == "🔙 Orqaga":
        kb = admin_kb() if is_admin(user.id) else user_kb()
        await update.message.reply_text("Bosh menyu:", reply_markup=kb)
        return ConversationHandler.END

    # Vaqtni ajratib olish
    start_dt     = None
    duration_min = 60
    topic        = "Meeting"

    if text == "⚡ Hozir boshlash":
        start_dt     = datetime.now(TASHKENT) + timedelta(minutes=1)
        duration_min = 60

    else:
        # "09:00 - 10:00" formatini qabul qilish
        match = re.search(r"(\d{1,2}:\d{2})\s*[-–]\s*(\d{1,2}:\d{2})", text)
        if match:
            result = parse_time(match.group(1), match.group(2))
            if result:
                start_dt, duration_min = result
        else:
            # Qo'lda "14:00 16:00 Mavzu" kiritilgan
            parts   = text.split()
            time_re = re.compile(r"^\d{1,2}:\d{2}$")
            if len(parts) >= 2 and time_re.match(parts[0]) and time_re.match(parts[1]):
                result = parse_time(parts[0], parts[1])
                if result:
                    start_dt, duration_min = result
                    topic = " ".join(parts[2:]) if len(parts) > 2 else "Meeting"

    if start_dt is None:
        await update.message.reply_text(
            "Tushunmadim. Quyidagi tugmalardan birini tanlang\n"
            "yoki vaqtni yozing: 14:00 16:00",
            reply_markup=zoom_time_kb()
        )
        return WAITING_ZOOM_TIME

    kb  = admin_kb() if is_admin(user.id) else user_kb()
    msg = await update.message.reply_text("⏳ Zoom meeting yaratilmoqda...", reply_markup=kb)

    try:
        meeting    = create_zoom_meeting(topic=topic, start_dt=start_dt, duration=duration_min)
        join_url   = meeting["join_url"]
        meeting_id = meeting["id"]
        password   = meeting.get("password", "")
        end_dt     = start_dt + timedelta(minutes=duration_min)

        out = (
            f"✅ *Meeting tayyor!*\n\n"
            f"📌 *Mavzu:* {topic}\n"
            f"🕐 *Boshlanish:* {start_dt.strftime('%H:%M')}\n"
            f"🕔 *Tugash:* {end_dt.strftime('%H:%M')}\n"
            f"⏱ *Davomiyligi:* {duration_min} daqiqa\n\n"
            f"🔗 *Link:* {join_url}\n"
            f"🆔 *ID:* `{meeting_id}`\n"
        )
        if password:
            out += f"🔑 *Parol:* `{password}`\n"
        out += "\n☁️ _Meeting avtomatik yozib olinadi_"

        await msg.edit_text(out, parse_mode="Markdown")
        logging.info(f"Meeting: {user.id} | {topic} | {start_dt.strftime('%H:%M')}–{end_dt.strftime('%H:%M')}")

    except Exception as e:
        logging.error(f"Zoom xatosi [{user.id}]: {e}")
        await msg.edit_text(
            f"⚠️ Zoom API xatosi:\n{str(e)}\n\n"
            "Zoom API kalitlarini tekshirin."
        )

    return ConversationHandler.END

# ─────────────────────────────────────────────
# Admin — qo'shish
# ─────────────────────────────────────────────

async def add_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END
    await update.message.reply_text(
        "Qoshmoqchi bolgan foydalanuvchi raqamini yozing:\n\n"
        "Masalan: +998901234567 yoki 901234567",
        reply_markup=back_kb()
    )
    return WAITING_PHONE_TO_ADD

async def add_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()

    if text == "🔙 Orqaga":
        await update.message.reply_text("Admin panel:", reply_markup=admin_kb())
        return ConversationHandler.END

    phone = normalize(text)

    if not re.match(r"^\+998\d{9}$", phone):
        await update.message.reply_text(
            "Notogri format. Qayta yozing:\n"
            "Masalan: +998901234567 yoki 901234567",
            reply_markup=back_kb()
        )
        return WAITING_PHONE_TO_ADD

    data = load_data()
    if phone in [normalize(p) for p in data["phones"]]:
        await update.message.reply_text(
            f"Bu raqam ({phone}) allaqachon royxatda!",
            reply_markup=admin_kb()
        )
        return ConversationHandler.END

    data["phones"].append(phone)
    save_data(data)
    await update.message.reply_text(
        f"✅ {phone} royxatga qoshildi!\n\n"
        "Endi bu foydalanuvchi botga kirib /start bossa raqamini yuborishi mumkin.",
        reply_markup=admin_kb()
    )
    logging.info(f"Qoshildi: {phone}")
    return ConversationHandler.END

# ─────────────────────────────────────────────
# Admin — o'chirish
# ─────────────────────────────────────────────

async def remove_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END

    data   = load_data()
    phones = data.get("phones", [])

    if not phones:
        await update.message.reply_text("Royxat bosh.", reply_markup=admin_kb())
        return ConversationHandler.END

    buttons = [[p] for p in phones] + [["🔙 Orqaga"]]
    await update.message.reply_text(
        "Ochirmoqchi bolgan raqamni tanlang:",
        reply_markup=ReplyKeyboardMarkup(buttons, resize_keyboard=True)
    )
    return WAITING_PHONE_TO_REMOVE

async def remove_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()

    if text == "🔙 Orqaga":
        await update.message.reply_text("Admin panel:", reply_markup=admin_kb())
        return ConversationHandler.END

    phone = normalize(text)
    data  = load_data()

    if phone not in [normalize(p) for p in data.get("phones", [])]:
        await update.message.reply_text("Bu raqam royxatda yoq.", reply_markup=admin_kb())
        return ConversationHandler.END

    data["phones"] = [p for p in data["phones"] if normalize(p) != phone]
    data["users"]  = {uid: p for uid, p in data.get("users", {}).items() if normalize(p) != phone}
    save_data(data)

    await update.message.reply_text(
        f"🗑 {phone} royxatdan ochirildi.",
        reply_markup=admin_kb()
    )
    logging.info(f"Ochirildi: {phone}")
    return ConversationHandler.END

# ─────────────────────────────────────────────
# Admin — ro'yxat
# ─────────────────────────────────────────────

async def show_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    data   = load_data()
    phones = data.get("phones", [])

    if not phones:
        await update.message.reply_text("📋 Royxat bosh.", reply_markup=admin_kb())
        return

    id_map = {normalize(p): uid for uid, p in data.get("users", {}).items()}
    lines  = []
    for i, phone in enumerate(phones, 1):
        uid    = id_map.get(normalize(phone), "—")
        status = "✅" if uid != "—" else "⏳"
        lines.append(f"{i}. {status} {phone}")

    text = f"👥 Royxat ({len(phones)} ta):\n\n" + "\n".join(lines)
    text += "\n\n✅ kirgan   ⏳ hali kirmagan"

    await update.message.reply_text(text, reply_markup=admin_kb())

# ─────────────────────────────────────────────
# Ishga tushirish
# ─────────────────────────────────────────────

def main():
    builder = ApplicationBuilder().token(TELEGRAM_TOKEN)
    if PROXY_URL:
        builder = builder.proxy(PROXY_URL).get_updates_proxy(PROXY_URL)
    app = builder.build()

    conv = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            MessageHandler(filters.Regex("^🎥 Zoom link olish$"),  zoom_start),
            MessageHandler(filters.Regex("^🎥 Zoom$"),             zoom_start),
            MessageHandler(filters.Regex("^➕ Qoshish$"),          add_start),
            MessageHandler(filters.Regex("^🗑 Ochirish$"),         remove_start),
        ],
        states={
            WAITING_ZOOM_TIME:       [MessageHandler(filters.TEXT & ~filters.COMMAND, zoom_time_receive)],
            WAITING_PHONE_TO_ADD:    [MessageHandler(filters.TEXT & ~filters.COMMAND, add_receive)],
            WAITING_PHONE_TO_REMOVE: [MessageHandler(filters.TEXT & ~filters.COMMAND, remove_receive)],
        },
        fallbacks=[CommandHandler("start", start)],
        allow_reentry=True
    )

    app.add_handler(conv)
    app.add_handler(MessageHandler(filters.Regex("^📋 Royxat$"), show_list))
    app.add_handler(MessageHandler(filters.CONTACT, handle_contact))

    print("Bot ishga tushdi!")
    app.run_polling()

if __name__ == "__main__":
    main()
