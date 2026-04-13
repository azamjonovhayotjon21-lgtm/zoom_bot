import os
from dotenv import load_dotenv

load_dotenv()

# Telegram bot token (BotFather dan)
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")

# Sizning Telegram ID ingiz — /myid bilan bilib oling
# Faqat shu ID admin hisoblanadi
ADMIN_TELEGRAM_ID = int(os.getenv("ADMIN_TELEGRAM_ID", "123456789"))

# Zoom API (marketplace.zoom.us dan)
ZOOM_ACCOUNT_ID    = os.getenv("ZOOM_ACCOUNT_ID", "")
ZOOM_CLIENT_ID     = os.getenv("ZOOM_CLIENT_ID", "")
ZOOM_CLIENT_SECRET = os.getenv("ZOOM_CLIENT_SECRET", "")

# Ma'lumotlar fayli
# Render serverida /data — restart bo'lsa ham saqlanadi
DATA_FILE = os.getenv("DATA_FILE", "/data/data.json")

# Proxy (O'zbekistonda Telegram bloklangan bo'lsa)
PROXY_URL = os.getenv("PROXY_URL", "")
