import html
import json
import logging
import re
import urllib.parse
from curl_cffi import requests
import yt_dlp

logger = logging.getLogger(__name__)

IPHONE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4_1 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4.1 Mobile/15E148 Safari/604.1"
)

DESKTOP_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

def clean_number(s: str) -> int:
    """Очищает строку с числом от пробелов, запятых и суффиксов K/M."""
    if not s:
        return 0
    s = s.strip().replace(" ", "").replace("\xa0", "").replace(",", "")
    if s.endswith("K") or s.endswith("k"):
        return int(float(s[:-1]) * 1000)
    if s.endswith("M") or s.endswith("m"):
        return int(float(s[:-1]) * 1000000)
    return int(float(s))

def parse_instagram_description(text: str):
    """Извлекает подписчиков, подписки и посты из описания Instagram."""
    text = html.unescape(text)
    followers = None
    following = None
    posts = None

    # Поиск подписчиков (рус / eng)
    m_fol = re.search(r'Подписчики:\s*([\d\s.,KkMm]+)', text, re.IGNORECASE)
    if not m_fol:
        m_fol = re.search(r'([\d\s.,KkMm]+)\s*Followers', text, re.IGNORECASE)
    if m_fol:
        followers = clean_number(m_fol.group(1))

    # Поиск подписок
    m_fng = re.search(r'Подписки:\s*([\d\s.,KkMm]+)', text, re.IGNORECASE)
    if not m_fng:
        m_fng = re.search(r'([\d\s.,KkMm]+)\s*Following', text, re.IGNORECASE)
    if m_fng:
        following = clean_number(m_fng.group(1))

    # Поиск публикаций
    m_pst = re.search(r'Публикации:\s*([\d\s.,KkMm]+)', text, re.IGNORECASE)
    if not m_pst:
        m_pst = re.search(r'([\d\s.,KkMm]+)\s*Posts', text, re.IGNORECASE)
    if m_pst:
        posts = clean_number(m_pst.group(1))

    return {
        "followers": followers,
        "following": following,
        "posts": posts,
    }

async def fetch_tiktok_data(username: str) -> dict:
    """Получает данные профиля TikTok и информацию о последнем видео."""
    result = {
        "platform": "tiktok",
        "username": username,
        "followers": None,
        "following": None,
        "posts_or_videos": None,
        "likes": None,
        "last_item_id": None,
        "last_item_url": None,
        "last_item_title": None,
    }

    # 1. Получение статистики профиля через веб-страницу с обходом WAF
    url = f"https://www.tiktok.com/@{username}?lang=en"
    try:
        r = requests.get(
            url,
            impersonate="chrome124",
            headers={
                "User-Agent": IPHONE_UA,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
                "Referer": "https://www.google.com/",
            },
            timeout=15
        )
        if r.status_code == 200:
            match = re.search(r'<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__"[^>]*>(.*?)</script>', r.text, re.DOTALL)
            if match:
                data = json.loads(match.group(1))
                scope = data.get("__DEFAULT_SCOPE__", {})
                user_detail = scope.get("webapp.user-detail", {})
                user_info = user_detail.get("userInfo", {})
                stats = user_info.get("stats", {})
                user = user_info.get("user", {})
                result["followers"] = stats.get("followerCount")
                result["following"] = stats.get("followingCount")
                result["posts_or_videos"] = stats.get("videoCount")
                result["likes"] = stats.get("heartCount") or stats.get("heart")
                result["has_story"] = (user.get("UserStoryStatus") == 1)
                result["open_favorite"] = bool(user.get("openFavorite", False))
                result["digg_count"] = stats.get("diggCount", 0)
    except Exception as e:
        logger.error(f"Ошибка при получении профиля TikTok: {e}")

    # 2. Получение последнего видео через yt-dlp
    try:
        ydl_opts = {
            "extract_flat": True,
            "playlist_end": 1,
            "quiet": True,
            "no_warnings": True,
            "http_headers": {
                "User-Agent": IPHONE_UA,
            },
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(f"https://www.tiktok.com/@{username}", download=False)
            if info and "entries" in info and len(info["entries"]) > 0:
                first_video = info["entries"][0]
                result["last_item_id"] = str(first_video.get("id"))
                result["last_item_url"] = first_video.get("url") or f"https://www.tiktok.com/@{username}/video/{result['last_item_id']}"
                result["last_item_title"] = first_video.get("title")
    except Exception as e:
        logger.warning(f"yt-dlp не смог получить последнее видео TikTok: {e}")

    return result

async def fetch_instagram_data(username: str, session_id: str = "") -> dict:
    """Получает данные профиля Instagram и ID последней публикации."""
    result = {
        "platform": "instagram",
        "username": username,
        "followers": None,
        "following": None,
        "posts_or_videos": None,
        "last_item_id": None,
        "last_item_url": None,
        "stories_count": 0,
    }

    url = f"https://www.instagram.com/{username}/"
    cookies = {"sessionid": session_id} if session_id else {}
    try:
        r = requests.get(
            url,
            impersonate="chrome124",
            headers={
                "User-Agent": DESKTOP_UA,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
            },
            cookies=cookies,
            timeout=15
        )
        if r.status_code == 200:
            # 1. Парсинг количества подписчиков/подписок/постов из meta
            meta_desc = re.search(r'<meta property="og:description" content="([^"]+)"', r.text)
            if not meta_desc:
                meta_desc = re.search(r'<meta name="description" content="([^"]+)"', r.text)
            
            if meta_desc:
                parsed = parse_instagram_description(meta_desc.group(1))
                result["followers"] = parsed["followers"]
                result["following"] = parsed["following"]
                result["posts_or_videos"] = parsed["posts"]

            # 2. Поиск последнего shortcode поста
            posts = re.findall(r'/(?:p|reel)/([A-Za-z0-9_-]{10,12})/', r.text)
            if posts:
                seen = set()
                unique_posts = [p for p in posts if not (p in seen or seen.add(p))]
                if unique_posts:
                    result["last_item_id"] = unique_posts[0]
                    result["last_item_url"] = f"https://www.instagram.com/p/{unique_posts[0]}/"

    except Exception as e:
        logger.error(f"Ошибка при получении профиля Instagram: {e}")

    # 3. Проверка историй (если предоставлен sessionid)
    if session_id:
        try:
            story_cookies = {
                "sessionid": urllib.parse.unquote(session_id),
                "ds_user_id": session_id.split("%3A")[0].split(":")[0],
            }
            story_headers = {
                "User-Agent": DESKTOP_UA,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            }
            story_url = f"https://www.instagram.com/stories/{username}/"
            s_resp = requests.get(story_url, impersonate="chrome124", headers=story_headers, cookies=story_cookies, timeout=15)
            if s_resp.status_code == 200:
                scripts = re.findall(r'<script type="application/json"[^>]*>(.*?)</script>', s_resp.text, re.DOTALL)
                for s in scripts:
                    if "xdt_api__v1__feed__reels_media" in s:
                        try:
                            data = json.loads(s)
                            def count_reels(obj):
                                count = 0
                                if isinstance(obj, dict):
                                    if "reels_media" in obj and isinstance(obj["reels_media"], list):
                                        for rm in obj["reels_media"]:
                                            count += len(rm.get("items", []))
                                    for v in obj.values():
                                        count += count_reels(v)
                                elif isinstance(obj, list):
                                    for it in obj:
                                        count += count_reels(it)
                                return count
                            result["stories_count"] = count_reels(data)
                            if result["stories_count"] > 0:
                                break
                        except Exception:
                            pass
        except Exception as e:
            logger.warning(f"Не удалось проверить истории Instagram: {e}")

    return result
