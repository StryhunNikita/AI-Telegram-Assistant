import os
import asyncio
import dotenv
import aiogram
from aiogram import types
from aiogram.filters import CommandStart, Command

from Bot.llm_client import ask_openai
from Bot.memory import (
    add_user_message,
    add_assistant_message,
    get_messages_for_model,
    reset_history,
)
from Bot.db import Database

dotenv.load_dotenv()
token = os.getenv("TELEGRAM_BOT_TOKEN")

dp = aiogram.Dispatcher()
db = Database()


@dp.message(CommandStart())
async def start_handler(message: types.Message):
    await message.answer(
        "Привет! Я ИИ-ассистент. На любой запрос — отвечу по смыслу.  "
        "Команда: /reset — очистить контекст."
    )


@dp.message(Command("reset"))
async def reset_handler(message: types.Message):
    uid = message.from_user.id
    await reset_history(db, uid)
    await message.answer("Контекст очищен.")


@dp.message(Command("search"))
async def search_handler(message: types.Message):
    telegram_id = message.from_user.id
    username = message.from_user.username or ""
    uid = await db.save_user(telegram_id, username)

    query = message.text.replace("/search", "", 1).strip()
    if not query:
        await message.answer("Напиши, что искать. Пример: /search работа")
        return

    try:
        rows = await db.search_messages(uid, query, limit=5)
    except Exception as e:
        await message.answer(f"Ошибка при поиске: {e}")
        return

    if not rows:
        await message.answer(f"Ничего не найдено по запросу: «{query}».")
        return

    results = "\n\n".join(row["content"] for row in rows)
    await message.answer(results)


@dp.message()
async def handle_user_query(message: types.Message):
    if not message.text or message.text.startswith("/"):
        return

    telegram_id = message.from_user.id
    username = message.from_user.username or ""
    uid = await db.save_user(telegram_id, username)

    user_text = message.text

    await add_user_message(db, uid, user_text)
    messages_for_model = await get_messages_for_model(db, uid, limit=10)
    reply = await ask_openai(messages_for_model, db, uid)
    await message.answer(reply)
    await add_assistant_message(db, uid, reply)


async def main():
    if not token:
        print("Ошибка: не найден TELEGRAM_BOT_TOKEN в .env")
        return

    bot = aiogram.Bot(token=token)
    await db.connect()
    print("Бот запущен... Нажми Ctrl+C, чтобы остановить.")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
