import asyncio
import html
import logging
import sys
from datetime import datetime

from aiogram import Bot, Dispatcher, types
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.client.default import DefaultBotProperties

import os
import aiohttp
from aiohttp import web
import httpx

import config
import database
import scrapers

# Настройка логирования и кодировки для Windows
sys.stdout.reconfigure(encoding="utf-8")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("social_monitor")

bot = Bot(
    token=config.BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
dp = Dispatcher()

# Веб-сервер для прохождения проверок Render (Free Web Service)
async def web_health_check(request):
    return web.json_response({
        "status": "ok",
        "bot": "social_monitor_running",
        "instagram": config.INSTAGRAM_TARGET,
        "tiktok": config.TIKTOK_TARGET
    })

async def self_ping_task():
    """Самопинг каждые 10 минут, чтобы Render Free Tier не засыпал."""
    external_url = os.getenv("RENDER_EXTERNAL_URL")
    if not external_url:
        return
    logger.info(f"Включен самопинг для предотвращения сна Render: {external_url}")
    await asyncio.sleep(60)
    async with httpx.AsyncClient(timeout=10.0) as client:
        while True:
            try:
                r = await client.get(external_url)
                logger.info(f"Самопинг Render: статус {r.status_code}")
            except Exception as e:
                logger.warning(f"Ошибка самопинга: {e}")
            await asyncio.sleep(600)  # каждые 10 минут

async def format_status_message(ig_data: dict, tt_data: dict) -> str:
    """Форматирует сводку по текущему состоянию аккаунтов."""
    msg = "📊 <b>Текущее состояние аккаунтов:</b>\n\n"

    # Instagram
    if ig_data and ig_data.get("followers") is not None:
        last_ig = f"<a href='{ig_data['last_item_url']}'>Открыть пост</a>" if ig_data.get("last_item_url") else "нет данных"
        ig_story = f"{ig_data['stories_count']} активных ✨" if ig_data.get("stories_count", 0) > 0 else "Нет активных историй"
        msg += (
            f"📸 <b>Instagram:</b> <a href='https://www.instagram.com/{config.INSTAGRAM_TARGET}/'>@{config.INSTAGRAM_TARGET}</a>\n"
            f"• Подписчики: <b>{ig_data['followers']:,}</b>\n"
            f"• Подписки: <b>{ig_data['following']:,}</b>\n"
            f"• Публикации: <b>{ig_data['posts_or_videos']:,}</b>\n"
            f"• Истории: <b>{ig_story}</b>\n"
            f"• Последний пост: {last_ig}\n\n"
        )
    else:
        msg += f"📸 <b>Instagram:</b> @{config.INSTAGRAM_TARGET} (ожидание обновления)\n\n"

    # TikTok
    if tt_data and tt_data.get("followers") is not None:
        last_tt = f"<a href='{tt_data['last_item_url']}'>Открыть видео</a>" if tt_data.get("last_item_url") else "нет данных"
        likes_tab = "🔓 Открыт для всех" if tt_data.get("open_favorite") else "🔒 Скрыт пользователем"
        msg += (
            f"🎥 <b>TikTok:</b> <a href='https://www.tiktok.com/@{config.TIKTOK_TARGET}'>@{config.TIKTOK_TARGET}</a>\n"
            f"• Подписчики: <b>{tt_data['followers']:,}</b>\n"
            f"• Подписки: <b>{tt_data['following']:,}</b>\n"
            f"• Всего видео: <b>{tt_data['posts_or_videos']:,}</b>\n"
            f"• Лайков всего: <b>{likes_str}</b>\n"
            f"• Истории: <b>{story_status}</b>\n"
            f"• Лайкнутые видео: <b>{likes_tab}</b>\n"
            f"• Последнее видео: {last_tt}\n"
        )
    else:
        msg += f"🎥 <b>TikTok:</b> @{config.TIKTOK_TARGET} (ожидание обновления)\n"

    return msg

async def notify_all(text: str):
    """Отправка уведомления всем зарегистрированным подписчикам бота."""
    subscribers = await database.get_all_subscribers()
    for chat_id in subscribers:
        try:
            await bot.send_message(chat_id, text, disable_web_page_preview=False)
        except Exception as e:
            logger.error(f"Не удалось отправить уведомление пользователю {chat_id}: {e}")

async def check_platform_changes(platform: str, username: str, new_data: dict):
    """Сравнивает новые данные платформы со старыми и рассылает уведомления при изменениях."""
    if not new_data or new_data.get("followers") is None:
        return

    old_state = await database.get_profile_state(platform)
    now_str = datetime.now().strftime("%H:%M:%S")

    # Если в базе еще нет записи по этой платформе — сохраняем базовый снимок
    if not old_state:
        await database.save_profile_state(
            platform=platform,
            username=username,
            followers=new_data["followers"],
            following=new_data["following"] or 0,
            posts_or_videos=new_data["posts_or_videos"] or 0,
            last_item_id=new_data.get("last_item_id") or "",
            extra_data={"likes": new_data.get("likes"), "stories_count": new_data.get("stories_count", 0)}
        )
        logger.info(f"[{platform}] Инициализировано начальное состояние: {new_data['followers']} подписчиков.")
        return

    notifications = []
    old_followers = old_state.get("followers")
    old_following = old_state.get("following")
    old_items = old_state.get("posts_or_videos")
    old_last_id = old_state.get("last_item_id")

    # 1. Проверка изменения подписчиков
    if new_data["followers"] is not None and old_followers is not None:
        diff = new_data["followers"] - old_followers
        if diff != 0:
            emoji = "📈" if diff > 0 else "📉"
            sign = f"+{diff}" if diff > 0 else f"{diff}"
            name_p = "Instagram" if platform == "instagram" else "TikTok"
            notifications.append(
                f"{emoji} <b>{name_p} (@{username})</b> [{now_str}]\n"
                f"Подписчики: <b>{sign}</b> (было {old_followers:,} ➔ стало <b>{new_data['followers']:,}</b>)"
            )

    # 2. Проверка изменения подписок
    if new_data["following"] is not None and old_following is not None:
        f_diff = new_data["following"] - old_following
        if f_diff != 0:
            name_p = "Instagram" if platform == "instagram" else "TikTok"
            f_sign = f"+{f_diff}" if f_diff > 0 else f"{f_diff}"
            notifications.append(
                f"👥 <b>{name_p} (@{username})</b> [{now_str}]\n"
                f"Подписки (following): <b>{f_sign}</b> (было {old_following:,} ➔ стало <b>{new_data['following']:,}</b>)"
            )

    # 3. Проверка новой публикации / нового видео
    is_new_media = False
    if new_data.get("last_item_id") and old_last_id and new_data["last_item_id"] != old_last_id:
        is_new_media = True
    elif new_data.get("posts_or_videos") and old_items and new_data["posts_or_videos"] > old_items:
        is_new_media = True

    if is_new_media:
        if platform == "instagram":
            url = new_data.get("last_item_url") or f"https://www.instagram.com/{username}/"
            notifications.append(
                f"📸 <b>Instagram (@{username}): Новая публикация!</b>\n"
                f"🔗 <a href='{url}'>Смотреть публикацию</a>"
            )
        elif platform == "tiktok":
            url = new_data.get("last_item_url") or f"https://www.tiktok.com/@{username}"
            title = new_data.get("last_item_title") or "Новое видео"
            notifications.append(
                f"🎥 <b>TikTok (@{username}): Новое видео!</b>\n"
                f"«{html.escape(title)}»\n"
                f"🔗 <a href='{url}'>Смотреть видео в TikTok</a>"
            )

    # 4. Проверка историй (Instagram)
    if platform == "instagram" and new_data.get("stories_count", 0) > 0:
        extra = {}
        if old_state.get("extra_json"):
            try:
                import json
                extra = json.loads(old_state["extra_json"])
            except Exception:
                pass
        old_stories = extra.get("stories_count", 0)
        if new_data["stories_count"] > old_stories:
            notifications.append(
                f"✨ <b>Instagram (@{username}): Новая история!</b>\n"
                f"🔗 <a href='https://www.instagram.com/{username}/'>Перейти в профиль</a>"
            )

    # 5. Проверка историй (TikTok)
    if platform == "tiktok":
        extra = {}
        if old_state.get("extra_json"):
            try:
                import json
                extra = json.loads(old_state["extra_json"])
            except Exception:
                pass
        old_has_story = extra.get("has_story", False)
        # Если ранее не было истории, а сейчас появилась
        if new_data.get("has_story") and not old_has_story:
            notifications.append(
                f"✨ <b>TikTok (@{username}): Появилась новая история!</b>\n"
                f"🔗 <a href='https://www.tiktok.com/@{username}'>Смотреть профиль TikTok</a>"
            )

        # 6. Проверка открытости лайкнутых видео
        old_open_fav = extra.get("open_favorite", False)
        new_open_fav = bool(new_data.get("open_favorite", False))
        if new_open_fav and not old_open_fav:
            notifications.append(
                f"🔓 <b>TikTok (@{username}): Пользователь ОТКРЫЛ список лайкнутых видео!</b>\n"
                f"Теперь список понравившихся видео стал публичным.\n"
                f"🔗 <a href='https://www.tiktok.com/@{username}'>Открыть TikTok профиль</a>"
            )
        elif not new_open_fav and old_open_fav:
            notifications.append(
                f"🔒 <b>TikTok (@{username}): Пользователь снова СКРЫЛ список лайкнутых видео.</b>"
            )

    # Отправка уведомлений подписчикам
    for alert in notifications:
        await notify_all(alert)

    # Обновление данных в БД
    await database.save_profile_state(
        platform=platform,
        username=username,
        followers=new_data["followers"],
        following=new_data["following"] or 0,
        posts_or_videos=new_data["posts_or_videos"] or 0,
        last_item_id=new_data.get("last_item_id") or old_last_id or "",
        extra_data={
            "likes": new_data.get("likes"),
            "stories_count": new_data.get("stories_count", 0),
            "has_story": new_data.get("has_story", False),
            "open_favorite": new_data.get("open_favorite", False),
        }
    )

async def check_all_targets():
    """Запуск разовой проверки обоих профилей."""
    logger.info("Проверка обновлений TikTok и Instagram...")
    # TikTok
    try:
        tt_data = await scrapers.fetch_tiktok_data(config.TIKTOK_TARGET)
        await check_platform_changes("tiktok", config.TIKTOK_TARGET, tt_data)
    except Exception as e:
        logger.error(f"Ошибка проверки TikTok: {e}")

    await asyncio.sleep(3)

    # Instagram
    try:
        ig_data = await scrapers.fetch_instagram_data(config.INSTAGRAM_TARGET, config.INSTAGRAM_SESSION_ID)
        await check_platform_changes("instagram", config.INSTAGRAM_TARGET, ig_data)
    except Exception as e:
        logger.error(f"Ошибка проверки Instagram: {e}")

# ================= ХЕНДЛЕРЫ TELEGRAM =================

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await database.add_subscriber(message.chat.id)
    welcome_text = (
        "👋 <b>Бот мониторинга активирован!</b>\n\n"
        "Вы успешно подписаны на уведомления.\n\n"
        "🎯 <b>Цели мониторинга:</b>\n"
        f"• 📸 Instagram: <a href='https://www.instagram.com/{config.INSTAGRAM_TARGET}/'>@{config.INSTAGRAM_TARGET}</a>\n"
        f"• 🎥 TikTok: <a href='https://www.tiktok.com/@{config.TIKTOK_TARGET}'>@{config.TIKTOK_TARGET}</a>\n\n"
        f"⏱ <b>Интервал проверки:</b> каждые {config.CHECK_INTERVAL_SECONDS // 60} минут.\n\n"
        "<b>Доступные команды:</b>\n"
        "/status — Текущее состояние профилей\n"
        "/check — Запустить проверку прямо сейчас\n"
        "/help — Справка"
    )
    await message.answer(welcome_text, disable_web_page_preview=True)

    # Сразу отправляем актуальный статус
    wait_msg = await message.answer("⏳ Загружаю актуальные данные профилей...")
    ig_data = await scrapers.fetch_instagram_data(config.INSTAGRAM_TARGET, config.INSTAGRAM_SESSION_ID)
    tt_data = await scrapers.fetch_tiktok_data(config.TIKTOK_TARGET)
    status_text = await format_status_message(ig_data, tt_data)
    await wait_msg.edit_text(status_text, disable_web_page_preview=True)

@dp.message(Command("status"))
async def cmd_status(message: types.Message):
    wait_msg = await message.answer("⏳ Получаю свежие данные...")
    ig_data = await scrapers.fetch_instagram_data(config.INSTAGRAM_TARGET, config.INSTAGRAM_SESSION_ID)
    tt_data = await scrapers.fetch_tiktok_data(config.TIKTOK_TARGET)
    status_text = await format_status_message(ig_data, tt_data)
    await wait_msg.edit_text(status_text, disable_web_page_preview=True)

@dp.message(Command("check"))
async def cmd_check(message: types.Message):
    await message.answer("🔎 Запущена внеплановая проверка...")
    await check_all_targets()
    await message.answer("✅ Проверка завершена. Если были изменения, уведомления уже отправлены.")

@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    help_text = (
        "🤖 <b>Справка бота мониторинга</b>\n\n"
        "Бот отслеживает профили в фоновом режиме каждые 30 минут:\n"
        "• Прирост / убыль подписчиков (Followers)\n"
        "• Изменение подписок (Following)\n"
        "• Новые видео в TikTok\n"
        "• Новые посты и Reels в Instagram\n\n"
        "<b>Команды:</b>\n"
        "/status — посмотреть текущие цифры\n"
        "/check — принудительно запустить проверку прямо сейчас"
    )
    await message.answer(help_text)

# ================= ФОНОВЫЙ ЦИКЛ =================

async def background_scheduler():
    """Фоновый цикл проверки каждые CHECK_INTERVAL_SECONDS."""
    logger.info(f"Фоновый планировщик запущен (интервал: {config.CHECK_INTERVAL_SECONDS} сек)...")
    # Небольшая задержка перед первым циклом
    await asyncio.sleep(10)
    while True:
        try:
            await check_all_targets()
        except Exception as e:
            logger.error(f"Непредвиденная ошибка в цикле планировщика: {e}")
        await asyncio.sleep(config.CHECK_INTERVAL_SECONDS)

async def main():
    await database.init_db()
    logger.info("База данных инициализирована.")
    
    # Первичная синхронизация базы при старте
    try:
        tt = await scrapers.fetch_tiktok_data(config.TIKTOK_TARGET)
        if tt and tt.get("followers") is not None:
            await database.save_profile_state(
                "tiktok", config.TIKTOK_TARGET, tt["followers"], tt["following"] or 0,
                tt["posts_or_videos"] or 0, tt.get("last_item_id") or "",
                {"likes": tt.get("likes"), "has_story": tt.get("has_story", False), "open_favorite": tt.get("open_favorite", False)}
            )
        ig = await scrapers.fetch_instagram_data(config.INSTAGRAM_TARGET, config.INSTAGRAM_SESSION_ID)
        if ig and ig.get("followers") is not None:
            await database.save_profile_state(
                "instagram", config.INSTAGRAM_TARGET, ig["followers"], ig["following"] or 0,
                ig["posts_or_videos"] or 0, ig.get("last_item_id") or "",
                {"stories_count": ig.get("stories_count", 0)}
            )
        logger.info("Начальные снимки профилей успешно сохранены в БД.")
    except Exception as e:
        logger.warning(f"Ошибка при сохранении начальных снимков: {e}")

    # Запуск фонового планировщика
    asyncio.create_task(background_scheduler())

    # Запуск веб-сервера для Render (Free Web Service)
    port = int(os.getenv("PORT", 8080))
    app = web.Application()
    app.router.add_get("/", web_health_check)
    app.router.add_get("/health", web_health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info(f"Веб-сервер мониторинга слушает порт {port}")

    # Запуск фонового самопинга для Render
    asyncio.create_task(self_ping_task())

    # Запуск поллинга сообщений бота
    logger.info("Запуск Telegram Polling...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот остановлен.")
