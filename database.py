import aiosqlite
import json
from datetime import datetime
from config import DB_PATH

async def init_db():
    """Создание необходимых таблиц в базе данных."""
    async with aiosqlite.connect(DB_PATH) as db:
        # Таблица подписчиков бота (кому слать уведомления)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS subscribers (
                chat_id INTEGER PRIMARY KEY,
                created_at TEXT
            )
        """)
        # Таблица снимков состояния профилей
        await db.execute("""
            CREATE TABLE IF NOT EXISTS profile_state (
                platform TEXT PRIMARY KEY,
                username TEXT,
                followers INTEGER,
                following INTEGER,
                posts_or_videos INTEGER,
                last_item_id TEXT,
                extra_json TEXT,
                updated_at TEXT
            )
        """)
        await db.commit()

async def add_subscriber(chat_id: int):
    """Добавить пользователя в рассылку."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO subscribers (chat_id, created_at) VALUES (?, ?)",
            (chat_id, datetime.now().isoformat())
        )
        await db.commit()

async def get_all_subscribers():
    """Получить всех активных подписчиков бота."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT chat_id FROM subscribers") as cursor:
            rows = await cursor.fetchall()
            return [row[0] for row in rows]

async def get_profile_state(platform: str):
    """Получить сохранённое состояние для платформы."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM profile_state WHERE platform = ?", (platform,)) as cursor:
            row = await cursor.fetchone()
            if row:
                return dict(row)
            return None

async def save_profile_state(platform: str, username: str, followers: int, following: int,
                             posts_or_videos: int, last_item_id: str, extra_data: dict = None):
    """Сохранить или обновить состояние профиля."""
    extra_str = json.dumps(extra_data or {}, ensure_ascii=False)
    now_str = datetime.now().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO profile_state (platform, username, followers, following, posts_or_videos, last_item_id, extra_json, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(platform) DO UPDATE SET
                username=excluded.username,
                followers=excluded.followers,
                following=excluded.following,
                posts_or_videos=excluded.posts_or_videos,
                last_item_id=excluded.last_item_id,
                extra_json=excluded.extra_json,
                updated_at=excluded.updated_at
        """, (platform, username, followers, following, posts_or_videos, last_item_id, extra_str, now_str))
        await db.commit()
