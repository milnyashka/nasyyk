import os
from pathlib import Path

# Базовая директория проекта
BASE_DIR = Path(__file__).resolve().parent

# Токен Telegram-бота
BOT_TOKEN = os.getenv("BOT_TOKEN", "8324581466:AAEJ87WR-a7_82pNpX5VxWgBt64N2vV3msU")

# Интервал проверки (в секундах) — 30 минут = 1800 секунд
CHECK_INTERVAL_SECONDS = int(os.getenv("CHECK_INTERVAL_SECONDS", "1800"))

# Целевые аккаунты
INSTAGRAM_TARGET = os.getenv("INSTAGRAM_TARGET", "nasyy.k")
TIKTOK_TARGET = os.getenv("TIKTOK_TARGET", "naasyyk")

# Сессионная кука Instagram (для отслеживания историй)
INSTAGRAM_SESSION_ID = os.getenv("INSTAGRAM_SESSION_ID", "77589621865%3A4j0m93Nh3uxSCD%3A28%3AAYkrApYfsWnYWSS8OCeuPyE3E3RdJK6XScxvsT4fOw")

# Путь к SQLite базе данных
DB_PATH = BASE_DIR / "monitor.db"
