import os
import re
import sys
import shutil
import tempfile
import asyncio
import logging
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart
from aiogram.types import FSInputFile
from downloader import download_video

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s"
)
logger = logging.getLogger("tg_video_bot")

# Load Bot Token
API_KEY_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "apikey.txt")

def get_bot_token() -> str:
    if os.path.exists(API_KEY_PATH):
        with open(API_KEY_PATH, "r", encoding="utf-8") as f:
            token = f.read().strip()
            if token:
                return token
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        logger.error("API token not found in apikey.txt or BOT_TOKEN env variable!")
        sys.exit(1)
    return token

TOKEN = get_bot_token()
bot = Bot(token=TOKEN)
dp = Dispatcher()

# Regex pattern for matching URLs
URL_REGEX = re.compile(r'https?://[^\s]+')


@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    welcome_text = (
        "👋 <b>Привет!</b>\n\n"
        "Я бот для скачивания видео.\n\n"
        "Просто отправь мне ссылку на видео из <b>YouTube, TikTok, Instagram, VK</b> или других поддерживаемых сайтов, "
        "и я сразу пришлю тебе видеозапись!\n\n"
        "⚡ Без рекламы\n"
        "⚡ Без обязательных подписок\n"
        "⚡ Прямая загрузка в чат"
    )
    await message.answer(welcome_text, parse_mode="HTML")


@dp.message(F.text)
async def handle_url(message: types.Message):
    text = message.text or ""
    urls = URL_REGEX.findall(text)

    if not urls:
        await message.answer("Пожалуйста, отправьте корректную ссылку на видео (например, с YouTube, TikTok, Instagram, VK).")
        return

    url = urls[0]  # Process the first URL found
    status_msg = await message.answer("📥 Скачиваю видео...")

    tmp_dir = tempfile.mkdtemp(prefix="tg_bot_vid_")

    try:
        res = await download_video(url, tmp_dir)

        if res.is_compressed:
            await status_msg.edit_text("⚡ Сжимаю видео для отправки в Telegram...")

        await status_msg.edit_text("📤 Отправляю видео...")

        video_file = FSInputFile(res.video_path)
        thumb_file = FSInputFile(res.thumb_path) if (res.thumb_path and os.path.exists(res.thumb_path)) else None

        caption = f"🎬 <b>{res.title}</b>"
        if len(caption) > 1024:
            caption = caption[:1020] + "..."

        await bot.send_video(
            chat_id=message.chat.id,
            video=video_file,
            caption=caption,
            parse_mode="HTML",
            duration=res.duration if res.duration > 0 else None,
            width=res.width if res.width > 0 else None,
            height=res.height if res.height > 0 else None,
            thumbnail=thumb_file,
            supports_streaming=True,
            reply_to_message_id=message.message_id
        )

        try:
            await status_msg.delete()
        except Exception:
            pass

    except Exception as e:
        logger.error(f"Error handling video download for {url}: {e}", exc_info=True)
        await status_msg.edit_text("❌ Не удалось скачать видео. Проверьте правильность ссылки или доступность видео.")

    finally:
        # Cleanup temporary files
        shutil.rmtree(tmp_dir, ignore_errors=True)


async def main():
    logger.info("Starting Telegram Video Downloader Bot...")
    # Delete webhook if any exists and start polling
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
