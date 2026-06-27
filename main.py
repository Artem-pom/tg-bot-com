"""
Telegram Channel Monitor Bot
Моніторить канал, шукає ключові слова і залишає коментарі під постами.
API_ID і API_HASH зберігаються у файлі .env
"""

import asyncio
import json
import os
import re
import sys
import subprocess
from datetime import datetime, timedelta

# ─────────────────────────────────────────────
#  Автоматична установка залежностей
# ─────────────────────────────────────────────
def _install(package: str):
    print(f"📦 Встановлення {package}...")
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", package],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"❌ Не вдалося встановити {package}:\n{result.stderr}")
        sys.exit(1)
    print(f"✅ {package} встановлено!")

def _ensure_deps():
    missing = []
    for pkg in ["telethon", "colorama", "dotenv"]:
        try:
            __import__("dotenv" if pkg == "dotenv" else pkg)
        except ImportError:
            # pip name відрізняється від import name
            missing.append("python-dotenv" if pkg == "dotenv" else pkg)

    if missing:
        print(f"⚠️  Відсутні бібліотеки: {', '.join(missing)}")
        print(f"🔧 Встановлення через: {sys.executable}\n")
        for pkg in missing:
            _install(pkg)
        print("\n✅ Усі залежності встановлено! Перезапускаємо...\n")
        os.execv(sys.executable, [sys.executable] + sys.argv)

_ensure_deps()

from dotenv import load_dotenv, set_key, dotenv_values
from telethon import TelegramClient
from telethon.tl.functions.channels import GetFullChannelRequest
from telethon.tl.functions.messages import GetDiscussionMessageRequest
from telethon.errors import (
    FloodWaitError, ChatWriteForbiddenError,
    UserBannedInChannelError, PeerIdInvalidError
)
from colorama import Fore, Style, init
init(autoreset=True)

ENV_FILE    = ".env"
CONFIG_FILE = "config.json"

# ─────────────────────────────────────────────
#  Кольоровий вивід
# ─────────────────────────────────────────────
def info(msg):    print(f"{Fore.CYAN}ℹ  {msg}{Style.RESET_ALL}")
def success(msg): print(f"{Fore.GREEN}✅ {msg}{Style.RESET_ALL}")
def warn(msg):    print(f"{Fore.YELLOW}⚠️  {msg}{Style.RESET_ALL}")
def error(msg):   print(f"{Fore.RED}❌ {msg}{Style.RESET_ALL}")
def ask(msg):     return input(f"{Fore.MAGENTA}➤  {msg}{Style.RESET_ALL}").strip()
def header(msg):  print(f"\n{Fore.BLUE}{'─'*50}\n   {msg}\n{'─'*50}{Style.RESET_ALL}\n")

# ─────────────────────────────────────────────
#  Робота з .env
# ─────────────────────────────────────────────
def load_env() -> dict:
    """Завантажує .env і повертає словник зі змінними."""
    load_dotenv(ENV_FILE, override=True)
    return dotenv_values(ENV_FILE)

def save_env(key: str, value: str):
    """Записує або оновлює змінну у .env файлі."""
    set_key(ENV_FILE, key, value)

def ensure_env_file():
    """Якщо .env не існує — створює шаблон."""
    if not os.path.exists(ENV_FILE):
        with open(ENV_FILE, "w", encoding="utf-8") as f:
            f.write("# Telegram API credentials\n")
            f.write("# Отримайте на https://my.telegram.org\n")
            f.write("API_ID=\n")
            f.write("API_HASH=\n")
        info(f"Створено файл {ENV_FILE} — заповніть API_ID і API_HASH")

# ─────────────────────────────────────────────
#  Збереження / завантаження config.json
# ─────────────────────────────────────────────
def save_config(cfg: dict):
    # НЕ зберігаємо секрети у config.json — тільки налаштування
    safe = {k: v for k, v in cfg.items() if k not in ("api_id", "api_hash")}
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(safe, f, ensure_ascii=False, indent=2)

def load_config() -> dict:
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {}

# ─────────────────────────────────────────────
#  Wizard — тільки налаштування каналу
# ─────────────────────────────────────────────
def setup_wizard() -> dict:
    header("🤖 Налаштування Telegram Monitor Bot")

    # ── Крок 1: API credentials з .env ───────
    ensure_env_file()
    env = load_env()

    api_id   = env.get("API_ID", "").strip()
    api_hash = env.get("API_HASH", "").strip()

    if not api_id or not api_hash:
        print(f"{Fore.YELLOW}📌 API_ID і API_HASH не знайдено у файлі {ENV_FILE}{Style.RESET_ALL}")
        print(f"   Отримайте їх на {Fore.CYAN}https://my.telegram.org{Style.RESET_ALL}\n")

        api_id   = ask("API_ID:   ")
        api_hash = ask("API_HASH: ")

        if not api_id or not api_hash:
            error("API_ID та API_HASH обовʼязкові!")
            sys.exit(1)

        # Зберігаємо у .env — більше питати не будемо
        save_env("API_ID",   api_id)
        save_env("API_HASH", api_hash)
        success(f"Збережено у {ENV_FILE} — наступного разу питати не буду!")
    else:
        masked_id   = api_id[:3] + "***"
        masked_hash = api_hash[:4] + "***" + api_hash[-4:]
        success(f"API_ID={masked_id}  API_HASH={masked_hash}  ← зчитано з {ENV_FILE}")

    cfg = load_config()

    # ── Крок 2: Канал ────────────────────────
    print()
    info("Введіть канал у форматі @username або https://t.me/username")
    channel_raw = ask(f"Канал [{cfg.get('channel', '')}]: ") or cfg.get("channel", "")
    channel = re.sub(r"https?://t\.me/", "@", channel_raw).strip()
    if channel and not channel.startswith("@"):
        channel = "@" + channel

    # ── Крок 3: Ключові слова ────────────────
    print()
    info("Введіть ключові слова через кому (регістр не важливий)")
    prev_kw = ", ".join(cfg.get("keywords", []))
    kw_raw  = ask(f"Ключові слова [{prev_kw}]: ") or prev_kw
    keywords = [w.strip() for w in kw_raw.split(",") if w.strip()]

    # ── Крок 4: Текст коментаря ──────────────
    print()
    info("Введіть коментар, який бот залишатиме під постом")
    reply_text = ask(f"Коментар [{cfg.get('reply_text', '')}]: ") or cfg.get("reply_text", "")

    # ── Крок 5: Час запуску ──────────────────
    print()
    info("Коли запустити моніторинг?")
    print("  1. Зараз")
    print("  2. Через N хвилин")
    print("  3. О конкретній годині (HH:MM)")
    choice = ask("Вибір [1/2/3]: ") or "1"

    start_delay_seconds = 0
    start_time_str      = "зараз"

    if choice == "2":
        mins = ask("Через скільки хвилин: ")
        try:
            start_delay_seconds = int(mins) * 60
            start_time_str      = f"через {mins} хв"
        except ValueError:
            warn("Невірне значення, запуск зараз.")

    elif choice == "3":
        t_str = ask("Час запуску (HH:MM): ")
        try:
            now    = datetime.now()
            target = datetime.strptime(t_str, "%H:%M").replace(
                year=now.year, month=now.month, day=now.day
            )
            if target <= now:
                target += timedelta(days=1)
            start_delay_seconds = int((target - now).total_seconds())
            start_time_str      = f"о {t_str}"
        except ValueError:
            warn("Невірний формат часу, запуск зараз.")

    # ── Крок 6: Інтервал перевірки ───────────
    print()
    interval = ask("Інтервал перевірки каналу в секундах [30]: ") or "30"
    try:
        interval_sec = max(10, int(interval))
    except ValueError:
        interval_sec = 30

    new_cfg = {
        "api_id":              api_id,
        "api_hash":            api_hash,
        "channel":             channel,
        "keywords":            keywords,
        "reply_text":          reply_text,
        "start_delay_seconds": start_delay_seconds,
        "start_time_str":      start_time_str,
        "interval_sec":        interval_sec,
    }
    save_config(new_cfg)
    return new_cfg

# ─────────────────────────────────────────────
#  Ядро моніторингу
# ─────────────────────────────────────────────
class ChannelMonitor:
    def __init__(self, client: TelegramClient, cfg: dict):
        self.client     = client
        self.channel    = cfg["channel"]
        self.keywords   = [kw.lower() for kw in cfg["keywords"]]
        self.reply_text = cfg["reply_text"]
        self.interval   = cfg["interval_sec"]
        self.seen_ids: set[int]      = set()
        self.commented: set[int]     = set()

    def _matches(self, text: str) -> bool:
        low = text.lower()
        return any(kw in low for kw in self.keywords)

    async def _try_comment(self, message) -> bool:
        try:
            channel_full   = await self.client(GetFullChannelRequest(self.channel))
            linked_chat_id = channel_full.full_chat.linked_chat_id

            if not linked_chat_id:
                warn(f"Канал {self.channel} не має підключеної групи коментарів.")
                return False

            disc            = await self.client(GetDiscussionMessageRequest(
                peer=self.channel, msg_id=message.id
            ))
            reply_to_msg_id = disc.messages[0].id
            linked_peer     = disc.messages[0].peer_id

            await self.client.send_message(
                entity   = linked_peer,
                message  = self.reply_text,
                reply_to = reply_to_msg_id,
            )
            return True

        except FloodWaitError as e:
            warn(f"FloodWait: чекаємо {e.seconds} сек...")
            await asyncio.sleep(e.seconds)
            return False
        except (ChatWriteForbiddenError, UserBannedInChannelError):
            error("Немає прав для коментування в цьому каналі.")
            return False
        except PeerIdInvalidError:
            error("Невірний ID каналу або канал не знайдено.")
            return False
        except Exception as exc:
            error(f"Помилка коментування: {exc}")
            return False

    async def run(self):
        info(f"Підключення до каналу {self.channel}...")
        try:
            entity = await self.client.get_entity(self.channel)
        except Exception as exc:
            error(f"Не вдалося знайти канал: {exc}")
            return

        success(f"Моніторинг каналу «{getattr(entity, 'title', self.channel)}» запущено!")
        info(f"Ключові слова: {', '.join(self.keywords)}")
        info(f"Інтервал перевірки: {self.interval} сек\n")

        info("Завантаження існуючих постів (щоб не дублювати коментарі)...")
        async for msg in self.client.iter_messages(entity, limit=50):
            self.seen_ids.add(msg.id)
        info(f"Збережено {len(self.seen_ids)} існуючих ID постів.\n")

        while True:
            try:
                async for msg in self.client.iter_messages(entity, limit=20):
                    if msg.id in self.seen_ids:
                        continue

                    self.seen_ids.add(msg.id)
                    text = msg.text or msg.caption or ""
                    if not text:
                        continue

                    timestamp = msg.date.strftime("%H:%M:%S")
                    preview   = text[:80].replace("\n", " ")
                    print(f"{Fore.WHITE}[{timestamp}] Новий пост #{msg.id}: {preview}…{Style.RESET_ALL}")

                    if self._matches(text):
                        found_kw = [kw for kw in self.keywords if kw in text.lower()]
                        success(f"Знайдено ключові слова {found_kw} у пості #{msg.id}")

                        if msg.id not in self.commented:
                            ok = await self._try_comment(msg)
                            if ok:
                                self.commented.add(msg.id)
                                success(f"Коментар залишено під постом #{msg.id} ✔")
                        else:
                            info(f"Пост #{msg.id} вже прокоментовано, пропускаємо.")

            except FloodWaitError as e:
                warn(f"FloodWait на головному циклі: чекаємо {e.seconds} сек...")
                await asyncio.sleep(e.seconds)
            except Exception as exc:
                error(f"Помилка циклу: {exc}")

            await asyncio.sleep(self.interval)

# ─────────────────────────────────────────────
#  Точка входу
# ─────────────────────────────────────────────
async def main():
    cfg = setup_wizard()

    header("🚀 Запуск бота")

    delay = cfg["start_delay_seconds"]
    if delay > 0:
        info(f"Моніторинг запуститься {cfg['start_time_str']} (через {delay} сек)...")
        print()
        for remaining in range(delay, 0, -1):
            print(f"\r⏳ Залишилось: {remaining} сек   ", end="", flush=True)
            await asyncio.sleep(1)
        print()

    client = TelegramClient(
        "monitor_session",
        int(cfg["api_id"]),
        cfg["api_hash"],
    )

    async with client:
        await client.start()
        me = await client.get_me()
        success(f"Авторизовано як: {me.first_name} (@{me.username})\n")

        monitor = ChannelMonitor(client, cfg)
        await monitor.run()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print(f"\n{Fore.YELLOW}🛑 Бот зупинено користувачем.{Style.RESET_ALL}")