import logging
import json
import os
import re
import asyncio
from datetime import datetime, timedelta

try:
    from zoneinfo import ZoneInfo
    TASHKENT = ZoneInfo("Asia/Tashkent")
except Exception:
    import datetime as dt
    TASHKENT = dt.timezone(dt.timedelta(hours=5))

from telegram import (
    Update, KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler,
    MessageHandler, filters, ContextTypes, ConversationHandler
)

from zoom_api import create_zoom_meeting
from config import TELEGRAM_TOKEN, ADMIN_TELEGRAM_ID, DATA_FILE

logging.basicConfig(
    format='%(asctime)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

WAITING_PHONE_TO_ADD    = 1
WAITING_PHONE_TO_REMOVE = 2
WAITING_ZOOM_TIME       = 3

# ─────────────────────────────────────────────
# Ma'lumotlar
# ─────────────────────────────────────────────

def load_data() -> dict:
    try:
        folder = os.path.dirname(DATA_FILE)
        if folder:
            os.makedirs(folder, exist_ok=True)
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if "phones" not in data:
                    data["phones"] = []
                if "users" not in data:
                    data["users"] = {}
                return data
    except Exception as e:
        logger.error(f"load_data xatosi: {e}")
    return {"phones": [], "users": {}}

def save_data(data: dict):
    try:
        folder = os.path.dirname(DATA_FILE)
        if folder:
            os.makedirs(folder, exist_ok=True)
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.error(f"save_data xatosi: {e}")

def normalize(phone: str) -> str:
    try:
        phone = re.sub(r"[\s\-\(\)\+]", "", phone.strip())
        if len(phone) == 9:
            return "+998" + phone
        elif len(phone) == 12 and phone.startswith("998"):
            return "+" + phone
        return phone
    except Exception:
        return phone

def is_admin(user_id: int) -> bool:
    try:
        return int(user_id) == int(ADMIN_TELEGRAM_ID)
    except Exception:
        return False

def is_registered(telegram_id: int) -> bool:
    try:
        data = load_data()
        return str(telegram_id) in data.get("users", {}) or is_admin(telegram_id)
    except Exception:
        return False

def now_tashkent():
    try:
        return datetime.now(TASHKENT)
    except Exception:
        import datetime as dt
        return datetime.now(dt.timezone(dt.timedelta(hours=5)))

# ─────────────────────────────────────────────
# Klaviaturalar
# ─────────────────────────────────────────────

def admin_kb():
    return ReplyKeyboardMarkup([
        ["➕ Qoshish", "🗑 Ochirish"],
        ["📋 Royxat",  "🎥 Zoom"]
    ], resize_keyboard=True)

def user_kb():
    return ReplyKeyboardMarkup([["🎥 Zoom link olish"]], resize_keyboard=True)

def contact_kb():
    return ReplyKeyboardMarkup(
        [[KeyboardButton("📱 Raqamimni yuborish", request_contact=True)]],
        resize_keyboard=True, one_time_keyboard=True
    )

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
    try:
        user = update.effective_user
        context.user_data.clear()
        if is_admin(user.id):
            await update.message.reply_text(
                "👋 Salom, Admin!\nQuyidagi tugmalardan foydalaning:",
                reply_markup=admin_kb()
            )
        elif is_registered(user.id):
            await update.message.reply_text(
                f"👋 Salom, {user.first_name}!\nZoom link olish uchun tugmani bosing:",
                reply_markup=user_kb()
            )
        else:
            await update.message.reply_text(
                f"👋 Salom, {user.first_name}!\n\n"
                "Botdan foydalanish uchun telefon raqamingizni yuboring 👇",
                reply_markup=contact_kb()
            )
    except Exception as e:
        logger.error(f"start xatosi: {e}")
    return ConversationHandler.END

# ─────────────────────────────────────────────
# Kontakt
# ─────────────────────────────────────────────

async def handle_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user  = update.effective_user
        phone = normalize(update.message.contact.phone_number)
        data  = load_data()
        if phone in [normalize(p) for p in data.get("phones", [])]:
            data["users"][str(user.id)] = phone
            save_data(data)
            await update.message.reply_text(
                f"✅ Tasdiqlandi! Xush kelibsiz, {user.first_name}!\n"
                "Zoom link olish uchun tugmani bosing 👇",
                reply_markup=user_kb()
            )
        else:
            await update.message.reply_text(
                "❌ Raqamingiz royxatda yoq.\nIltimos, admin bilan boglanin.",
                reply_markup=ReplyKeyboardRemove()
            )
    except Exception as e:
        logger.error(f"handle_contact xatosi: {e}")

# ─────────────────────────────────────────────
# Zoom
# ─────────────────────────────────────────────

def parse_time(start_str: str, end_str: str):
    try:
        sh, sm = map(int, start_str.strip().split(":"))
        eh, em = map(int, end_str.strip().split(":"))
        now      = now_tashkent()
        start_dt = now.replace(hour=sh, minute=sm, second=0, microsecond=0)
        end_dt   = now.replace(hour=eh, minute=em, second=0, microsecond=0)
        if start_dt < now:
            start_dt += timedelta(days=1)
            end_dt   += timedelta(days=1)
        if end_dt <= start_dt:
            return None
        return start_dt, int((end_dt - start_dt).total_seconds() // 60)
    except Exception as e:
        logger.error(f"parse_time xatosi: {e}")
        return None

async def zoom_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not is_registered(update.effective_user.id):
            await update.message.reply_text("Siz royxatdan otmagansiz. /start bosing.")
            return ConversationHandler.END
        await update.message.reply_text("Qaysi vaqtga meeting kerak?", reply_markup=zoom_time_kb())
        return WAITING_ZOOM_TIME
    except Exception as e:
        logger.error(f"zoom_start xatosi: {e}")
        return ConversationHandler.END

async def zoom_time_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        text = update.message.text.strip()
        user = update.effective_user
        kb   = admin_kb() if is_admin(user.id) else user_kb()

        if text == "🔙 Orqaga":
            await update.message.reply_text("Bosh menyu:", reply_markup=kb)
            return ConversationHandler.END

        start_dt, duration_min, topic = None, 60, "Meeting"

        if text == "⚡ Hozir boshlash":
            start_dt = now_tashkent() + timedelta(minutes=1)
        else:
            match = re.search(r"(\d{1,2}:\d{2})\s*[-–]\s*(\d{1,2}:\d{2})", text)
            if match:
                result = parse_time(match.group(1), match.group(2))
                if result:
                    start_dt, duration_min = result
                    topic = "Rejalashtirilgan meeting"
            else:
                parts = text.split()
                if len(parts) >= 2 and re.match(r"^\d{1,2}:\d{2}$", parts[0]) and re.match(r"^\d{1,2}:\d{2}$", parts[1]):
                    result = parse_time(parts[0], parts[1])
                    if result:
                        start_dt, duration_min = result
                        topic = " ".join(parts[2:]) if len(parts) > 2 else "Meeting"

        if start_dt is None:
            await update.message.reply_text(
                "Tushunmadim. Tugmalardan birini tanlang\n"
                "yoki vaqtni yozing: 14:00 16:00",
                reply_markup=zoom_time_kb()
            )
            return WAITING_ZOOM_TIME

        msg = await update.message.reply_text("⏳ Zoom meeting yaratilmoqda...", reply_markup=kb)
        try:
            meeting  = create_zoom_meeting(topic=topic, start_dt=start_dt, duration=duration_min)
            join_url = meeting.get("join_url", "")
            mid      = meeting.get("id", "")
            password = meeting.get("password", "")
            end_dt   = start_dt + timedelta(minutes=duration_min)

            if not join_url:
                raise ValueError("Zoom API link qaytarmadi")

            out = (
                f"✅ Meeting tayyor!\n\n"
                f"📌 Mavzu: {topic}\n"
                f"🕐 Boshlanish: {start_dt.strftime('%H:%M')}\n"
                f"🕔 Tugash: {end_dt.strftime('%H:%M')}\n"
                f"⏱ Davomiyligi: {duration_min} daqiqa\n\n"
                f"🔗 Link: {join_url}\n"
                f"🆔 ID: {mid}\n"
            )
            if password:
                out += f"🔑 Parol: {password}\n"
            out += "\n☁️ Meeting avtomatik yozib olinadi"
            await msg.edit_text(out)
        except Exception as e:
            logger.error(f"Zoom API xatosi: {e}")
            await msg.edit_text(f"⚠️ Zoom xatosi: {str(e)}")

    except Exception as e:
        logger.error(f"zoom_time_receive xatosi: {e}")
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
    try:
        text = update.message.text.strip()
        if text == "🔙 Orqaga":
            await update.message.reply_text("Admin panel:", reply_markup=admin_kb())
            return ConversationHandler.END

        phone = normalize(text)
        if not re.match(r"^\+998\d{9}$", phone):
            await update.message.reply_text(
                "Notogri format. Masalan: +998901234567 yoki 901234567",
                reply_markup=back_kb()
            )
            return WAITING_PHONE_TO_ADD

        data = load_data()
        if phone in [normalize(p) for p in data.get("phones", [])]:
            await update.message.reply_text(f"Bu raqam ({phone}) allaqachon royxatda!", reply_markup=admin_kb())
            return ConversationHandler.END

        data["phones"].append(phone)
        save_data(data)
        await update.message.reply_text(
            f"✅ {phone} royxatga qoshildi!\n\n"
            "Endi bu foydalanuvchi /start bosib raqamini yuborishi mumkin.",
            reply_markup=admin_kb()
        )
    except Exception as e:
        logger.error(f"add_receive xatosi: {e}")
        await update.message.reply_text("Xato yuz berdi.", reply_markup=admin_kb())
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
    try:
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
        await update.message.reply_text(f"🗑 {phone} royxatdan ochirildi.", reply_markup=admin_kb())
    except Exception as e:
        logger.error(f"remove_receive xatosi: {e}")
        await update.message.reply_text("Xato yuz berdi.", reply_markup=admin_kb())
    return ConversationHandler.END

# ─────────────────────────────────────────────
# Admin — ro'yxat
# ─────────────────────────────────────────────

async def show_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not is_admin(update.effective_user.id):
            return
        data   = load_data()
        phones = data.get("phones", [])
        if not phones:
            await update.message.reply_text("📋 Royxat bosh.", reply_markup=admin_kb())
            return
        id_map = {normalize(p): uid for uid, p in data.get("users", {}).items()}
        lines  = [
            f"{i}. {'✅' if id_map.get(normalize(p)) else '⏳'} {p}"
            for i, p in enumerate(phones, 1)
        ]
        text = f"👥 Royxat ({len(phones)} ta):\n\n" + "\n".join(lines)
        text += "\n\n✅ kirgan   ⏳ hali kirmagan"
        await update.message.reply_text(text, reply_markup=admin_kb())
    except Exception as e:
        logger.error(f"show_list xatosi: {e}")

# ─────────────────────────────────────────────
# Ishga tushirish — asyncio muammosini hal qilish
# ─────────────────────────────────────────────

async def run_bot():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    conv = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            MessageHandler(filters.Regex("^🎥 Zoom link olish$"), zoom_start),
            MessageHandler(filters.Regex("^🎥 Zoom$"),            zoom_start),
            MessageHandler(filters.Regex("^➕ Qoshish$"),         add_start),
            MessageHandler(filters.Regex("^🗑 Ochirish$"),        remove_start),
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

    logger.info("Bot ishga tushdi!")
    print("Bot ishga tushdi!")

    await app.initialize()
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(run_bot())
