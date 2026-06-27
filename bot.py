import asyncio
import logging
from pyrogram import Client, filters
from pyrogram.handlers import MessageHandler
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

# ===== НАЛАШТУВАННЯ =====

# ========================

logging.basicConfig(level=logging.INFO)

# --- Стани FSM ---
class Setup(StatesGroup):
    channel  = State()
    keywords = State()
    comment  = State()

# --- Дані користувачів ---
# { user_id: { "channel": ..., "keywords": [...], "comment": ... } }
user_configs = {}

# --- Активні моніторинги ---
# { user_id: handler_ref }
active_monitors = {}

# --- Pyrogram userbot ---
userbot = Client("userbot_session", api_id=API_ID, api_hash=API_HASH)

# --- aiogram бот ---
bot = Bot(token=BOT_TOKEN)
dp  = Dispatcher(storage=MemoryStorage())


# ===== AIOGRAM ХЕНДЛЕРИ =====

@dp.message(F.text == "/start")
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "👋 Привіт! Я допоможу налаштувати моніторинг Telegram-каналу.\n\n"
        "Надішли команду /setup щоб почати."
    )

@dp.message(F.text == "/setup")
async def cmd_setup(message: Message, state: FSMContext):
    await state.set_state(Setup.channel)
    await message.answer("📢 Введи username каналу без @ (наприклад: my_channel):")

@dp.message(Setup.channel)
async def got_channel(message: Message, state: FSMContext):
    await state.update_data(channel=message.text.strip())
    await state.set_state(Setup.keywords)
    await message.answer(
        "🔍 Введи ключові слова через кому.\n"
        "Бот буде реагувати на пости, що містять хоча б одне з них.\n\n"
        "Наприклад: продаж, знижка, акція"
    )

@dp.message(Setup.keywords)
async def got_keywords(message: Message, state: FSMContext):
    keywords = [kw.strip().lower() for kw in message.text.split(",") if kw.strip()]
    if not keywords:
        await message.answer("❌ Введи хоча б одне ключове слово.")
        return
    await state.update_data(keywords=keywords)
    await state.set_state(Setup.comment)
    await message.answer("💬 Що писати в коментарі до посту?")

@dp.message(Setup.comment)
async def got_comment(message: Message, state: FSMContext):
    data = await state.get_data()
    config = {
        "channel":  data["channel"],
        "keywords": data["keywords"],
        "comment":  message.text.strip(),
    }
    user_configs[message.from_user.id] = config
    await state.clear()

    await message.answer(
        f"✅ Налаштування збережено:\n\n"
        f"📢 Канал: @{config['channel']}\n"
        f"🔍 Слова: {', '.join(config['keywords'])}\n"
        f"💬 Коментар: {config['comment']}\n\n"
        f"Надішли /start_monitor щоб запустити моніторинг."
    )

@dp.message(F.text == "/start_monitor")
async def cmd_start_monitor(message: Message):
    user_id = message.from_user.id
    config  = user_configs.get(user_id)

    if not config:
        await message.answer("⚠️ Спочатку налаштуй бота через /setup")
        return

    # Видаляємо старий хендлер якщо є
    if user_id in active_monitors:
        userbot.remove_handler(*active_monitors[user_id])
        del active_monitors[user_id]

    channel  = config["channel"]
    keywords = config["keywords"]
    comment  = config["comment"]

    async def post_handler(client, msg):
        if not msg.text:
            return
        text = msg.text.lower()
        if any(kw in text for kw in keywords):
            try:
                await msg.reply(comment)
                await bot.send_message(user_id, f"✅ Відповів на пост у @{channel}")
            except Exception as e:
                await bot.send_message(user_id, f"❌ Помилка при відповіді: {e}")

    handler = MessageHandler(post_handler, filters.chat(channel))
    userbot.add_handler(handler)
    active_monitors[user_id] = (handler, filters.chat(channel))

    await message.answer(
        f"🟢 Моніторинг запущено!\n"
        f"Слідкую за @{channel} на слова: {', '.join(keywords)}"
    )

@dp.message(F.text == "/stop_monitor")
async def cmd_stop_monitor(message: Message):
    user_id = message.from_user.id
    if user_id in active_monitors:
        userbot.remove_handler(*active_monitors[user_id])
        del active_monitors[user_id]
        await message.answer("🔴 Моніторинг зупинено.")
    else:
        await message.answer("⚠️ Моніторинг не був запущений.")

@dp.message(F.text == "/status")
async def cmd_status(message: Message):
    user_id = message.from_user.id
    config  = user_configs.get(user_id)
    active  = user_id in active_monitors

    if not config:
        await message.answer("Налаштування відсутні. Запусти /setup")
        return

    await message.answer(
        f"📊 Статус:\n\n"
        f"📢 Канал: @{config['channel']}\n"
        f"🔍 Слова: {', '.join(config['keywords'])}\n"
        f"💬 Коментар: {config['comment']}\n"
        f"🔄 Моніторинг: {'🟢 активний' if active else '🔴 зупинений'}"
    )

@dp.message(F.text == "/help")
async def cmd_help(message: Message):
    await message.answer(
        "📋 Команди:\n\n"
        "/setup — налаштувати канал, слова, коментар\n"
        "/start_monitor — запустити моніторинг\n"
        "/stop_monitor — зупинити моніторинг\n"
        "/status — поточні налаштування\n"
        "/help — ця довідка"
    )


# ===== ЗАПУСК =====

async def main():
    await userbot.start()
    print("✅ Userbot запущено")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())