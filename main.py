import asyncio
import logging
import os
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

from os import getenv
from aiogram import Bot, Dispatcher, html, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from aiogram.types import Message
from aiogram.fsm.storage.memory import MemoryStorage
from openai import AsyncOpenAI
from dotenv import load_dotenv

# ────────────────────────────────────────────────
# Фейковый HTTP-сервер для Render (Web Service)
# ────────────────────────────────────────────────
class DummyHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

def run_dummy_server():
    port = int(os.environ.get('PORT', 10000))  # Render требует именно 10000
    server = HTTPServer(('0.0.0.0', port), DummyHandler)
    server.serve_forever()

# Запускаем сервер в отдельном потоке (до инициализации бота)
threading.Thread(target=run_dummy_server, daemon=True).start()

# ────────────────────────────────────────────────
# Настройки и окружение
# ────────────────────────────────────────────────
load_dotenv()

TELEGRAM_TOKEN = getenv("TELEGRAM_TOKEN")
OPENAI_API_KEY = getenv("OPENAI_API_KEY")

# Белый список (замени на реальные ID!)
ALLOWED_USERS = {986853662, 640886937}

SYSTEM_PROMPT = """
Ты - AI-аналитик для менеджеров. Твоя задача - анализировать предоставленный текст и давать структурированный ответ.
Структура ответа:
1. Ключевые моменты: Перечисли основные идеи.
2. Рекомендации: Предложи действия на основе анализа.
3. Риски: Укажи потенциальные проблемы.

Анализируй текст объективно и конструктивно.
"""

# ────────────────────────────────────────────────
# Инициализация
# ────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

bot = Bot(
    token=TELEGRAM_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)

dp = Dispatcher(storage=MemoryStorage())

openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)

# ────────────────────────────────────────────────
# Вспомогательная функция — отправка длинных сообщений
# ────────────────────────────────────────────────
async def send_split_text(chat_id: int, text: str, max_len: int = 3800):
    while text:
        chunk = text[:max_len]
        text = text[max_len:]
        await bot.send_message(chat_id, chunk)

# ────────────────────────────────────────────────
# Хендлеры
# ────────────────────────────────────────────────
@dp.message(CommandStart())
async def cmd_start(message: Message):
    user_id = message.from_user.id
    if user_id not in ALLOWED_USERS:
        logging.warning(f"Отказ в доступе → user_id={user_id}")
        await message.answer("Доступ запрещён. Вы не в белом списке.")
        return

    await message.answer(
        f"Привет, {html.bold(message.from_user.full_name)}!\n"
        "Отправь мне текст для анализа."
    )


@dp.message(F.text)  # Только текстовые сообщения (без стикеров, фото и т.д.)
async def analyze_text(message: Message):
    user_id = message.from_user.id
    if user_id not in ALLOWED_USERS:
        logging.warning(f"Отказ в доступе → user_id={user_id}")
        await message.answer("Доступ запрещён. Вы не в белом списке.")
        return

    user_text = message.text.strip()
    if not user_text:
        await message.answer("Пустое сообщение. Отправь текст для анализа.")
        return

    try:
        response = await openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_text},
            ],
            temperature=0.3,
            max_tokens=1500,
        )

        ai_text = response.choices[0].message.content
        await send_split_text(message.chat.id, ai_text)  # безопасная отправка длинных текстов

    except Exception as e:
        logging.exception("Ошибка при обращении к OpenAI")
        error_msg = f"Произошла ошибка: {html.code(str(e))}"
        await message.answer(error_msg[:4000])  # Telegram лимит на сообщение


# ────────────────────────────────────────────────
# Запуск
# ────────────────────────────────────────────────
async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    logging.info("Бот запущен. Polling стартовал.")
    await dp.start_polling(
        bot,
        allowed_updates=["message"],
    )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("Бот остановлен")
