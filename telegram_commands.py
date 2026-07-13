"""
telegram_commands.py

Простий Telegram command polling без aiogram/python-telegram-bot.
Підтримує:
- /start
- /help
- /price

Публічний режим:
TELEGRAM_PUBLIC_COMMANDS=true

Приватний режим:
TELEGRAM_PUBLIC_COMMANDS=false
і команди приймаються тільки від TELEGRAM_CHAT_ID.
"""

import logging
from datetime import datetime

import requests

from config import telegram_cfg, mt5_cfg
import telegram_publisher

logger = logging.getLogger("telegram_commands")


API_BASE = "https://api.telegram.org/bot{token}/{method}"


class TelegramCommandPoller:
    def __init__(self):
        self.offset: int | None = None

    def _api_url(self, method: str) -> str:
        return API_BASE.format(token=telegram_cfg.bot_token, method=method)

    def _is_allowed(self, chat_id: int | str) -> bool:
        """
        Якщо TELEGRAM_PUBLIC_COMMANDS=true — команди доступні всім.
        Якщо false — тільки chat_id з .env.
        """
        if telegram_cfg.public_commands:
            return True

        if not telegram_cfg.chat_id:
            return False

        return str(chat_id) == str(telegram_cfg.chat_id)

    def _send_private_mode_message(self, chat_id: int | str) -> None:
        telegram_publisher.send_text_to_chat(
            chat_id,
            "⛔ Бот зараз у приватному режимі. "
            "Доступ до команд має тільки власник.",
        )

    def _channel_link(self) -> str | None:
        """Посилання на канал сигналів для запрошення користувачів.
        Працює для публічних каналів виду '@username'. Для числових -100... id
        посилання не будуємо (немає публічного username)."""
        ch = telegram_cfg.channel_id.strip()
        if telegram_cfg.public_mode and ch.startswith("@"):
            return f"https://t.me/{ch[1:]}"
        return None

    def _handle_start(self, chat_id: int | str) -> None:
        visibility = "публічний" if telegram_cfg.public_commands else "приватний"

        lines = [
            "✅ Бот запущений і готовий до роботи.",
            "",
            f"Режим: {visibility}",
            f"Поточний символ: {mt5_cfg.symbol}",
            f"Таймфрейм: {mt5_cfg.timeframe}",
        ]

        link = self._channel_link()
        if link:
            lines += [
                "",
                "📢 Сигнали публікуються в каналі — підпишись, щоб їх отримувати:",
                link,
            ]

        lines += [
            "",
            "Доступні команди:",
            "/start — перевірити, що бот відповідає",
            "/price — показати поточну ціну з MetaTrader 5",
            "/help — список команд",
            "",
            "⚠️ Це не фінансова порада.",
        ]

        telegram_publisher.send_text_to_chat(chat_id, "\n".join(lines))

    def _handle_help(self, chat_id: int | str) -> None:
        text = (
            "📌 Команди бота:\n\n"
            "/start — перевірити підключення\n"
            "/price — поточна ціна з MetaTrader 5\n"
            "/help — допомога\n\n"
            f"Поточний символ з .env: {mt5_cfg.symbol}"
        )

        telegram_publisher.send_text_to_chat(chat_id, text)

    def _handle_price(self, chat_id: int | str, client) -> None:
        """
        Бере актуальний tick з MT5 через існуючий MT5Client.
        """
        try:
            tick = client.get_tick()

            mid_price = (tick.bid + tick.ask) / 2
            spread = tick.ask - tick.bid

            text = (
                f"💰 Поточна ціна з MetaTrader 5\n\n"
                f"Символ: {mt5_cfg.symbol}\n"
                f"Bid: {tick.bid:.2f}\n"
                f"Ask: {tick.ask:.2f}\n"
                f"Mid: {mid_price:.2f}\n"
                f"Spread: {spread:.2f}\n"
                f"Час tick: {tick.time.strftime('%Y-%m-%d %H:%M:%S')}"
            )

            telegram_publisher.send_text_to_chat(chat_id, text)

        except Exception as e:
            logger.exception("Не вдалось отримати ціну з MT5: %s", e)

            telegram_publisher.send_text_to_chat(
                chat_id,
                "❌ Не вдалось отримати поточну ціну з MetaTrader 5.\n\n"
                f"Помилка: {e}",
            )

    def _extract_command(self, text: str) -> str:
        """
        Підтримує команди типу:
        /start
        /start@Roman_XAU_bot
        """
        first = text.strip().split()[0]
        command = first.split("@")[0].lower()
        return command

    def poll(self, client) -> None:
        """
        Один короткий polling-запит до Telegram.
        Викликається з основного циклу main.py.
        """
        if not telegram_cfg.bot_token:
            logger.error("TELEGRAM_BOT_TOKEN не заданий в .env")
            return

        params = {
            "timeout": 0,
            "allowed_updates": ["message"],
        }

        if self.offset is not None:
            params["offset"] = self.offset

        try:
            resp = requests.get(
                self._api_url("getUpdates"),
                params=params,
                timeout=10,
            )
            resp.raise_for_status()
            payload = resp.json()

        except requests.RequestException as e:
            logger.error("Не вдалось отримати Telegram updates: %s", e)
            return

        if not payload.get("ok"):
            logger.error("Telegram getUpdates повернув помилку: %s", payload)
            return

        for update in payload.get("result", []):
            self.offset = update["update_id"] + 1

            message = update.get("message")
            if not message:
                continue

            chat = message.get("chat", {})
            chat_id = chat.get("id")
            text = message.get("text", "")

            if not chat_id or not text.startswith("/"):
                continue

            command = self._extract_command(text)

            logger.info("Telegram command: %s from chat_id=%s", command, chat_id)

            if not self._is_allowed(chat_id):
                self._send_private_mode_message(chat_id)
                continue

            if command == "/start":
                self._handle_start(chat_id)

            elif command == "/help":
                self._handle_help(chat_id)

            elif command == "/price":
                self._handle_price(chat_id, client)

            else:
                telegram_publisher.send_text_to_chat(
                    chat_id,
                    "Невідома команда. Напиши /help",
                )