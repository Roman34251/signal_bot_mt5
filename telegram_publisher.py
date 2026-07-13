"""
telegram_publisher.py
Відправка сигналів у Telegram у форматі, який користувач надав як приклад:

BUY XAU/USD
📍 4148 - 4151
❗ Stop loss (SL): 4128
✅ Take profit 1: 4154.4
✅ Take profit 2: 4158.3
✅ Take profit 3: 4165.4
✅ Take profit 4: 4195
"""
import logging

import requests

from config import telegram_cfg
from levels import SignalLevels

logger = logging.getLogger("telegram_publisher")

API_URL = "https://api.telegram.org/bot{token}/sendMessage"


def _format_message(symbol: str, levels: SignalLevels, probability: float) -> str:
    pair = symbol.replace("XAUUSD", "XAU/USD") if symbol.upper() == "XAUUSD" else symbol
    lines = [
        f"{levels.direction} {pair}",
        "",
        f"📍 {levels.entry_low} - {levels.entry_high}",
        "",
    ]
    if levels.direction == "BUY":
        lines.append(f"❗ Stop loss (SL): {levels.sl}")
        lines.append(f"✅ Take profit 1: {levels.tp1}")
        lines.append(f"✅ Take profit 2: {levels.tp2}")
        lines.append(f"✅ Take profit 3: {levels.tp3}")
        lines.append(f"✅ Take profit 4: {levels.tp4}")
    else:
        lines.append(f"✅ Take profit 1: {levels.tp1}")
        lines.append(f"✅ Take profit 2: {levels.tp2}")
        lines.append(f"✅ Take profit 3: {levels.tp3}")
        lines.append(f"✅ Take profit 4: {levels.tp4}")
        lines.append("")
        lines.append(f"❗ Stop loss (SL): {levels.sl}")

    lines.append("")
    lines.append(f"🎯 Впевненість моделі: {probability * 100:.1f}%")
    lines.append(
        "⚠️ Не є фінансовою порадою. Торгівля з кредитним плечем ризикована — "
        "керуйте розміром позиції самостійно."
    )
    return "\n".join(lines)


def _signal_target() -> str:
    """Куди слати сигнал.

    Публічний режим (TELEGRAM_PUBLIC_MODE=true) + заданий канал → у канал.
    Інакше — приватно власнику (TELEGRAM_CHAT_ID).
    """
    if telegram_cfg.public_mode and telegram_cfg.channel_id:
        return telegram_cfg.channel_id
    return telegram_cfg.chat_id


def send_signal(symbol: str, levels: SignalLevels, probability: float) -> bool:
    target_chat_id = _signal_target()

    if not telegram_cfg.bot_token or not target_chat_id:
        logger.error(
            "TELEGRAM_BOT_TOKEN відсутній, або немає адресата сигналу "
            "(перевір TELEGRAM_CHANNEL_ID / TELEGRAM_CHAT_ID у .env)"
        )
        return False

    text = _format_message(symbol, levels, probability)
    url = API_URL.format(token=telegram_cfg.bot_token)
    try:
        resp = requests.post(
            url,
            json={"chat_id": target_chat_id, "text": text},
            timeout=15,
        )
        resp.raise_for_status()
        logger.info(
            "Сигнал %s %s надіслано в Telegram (%s)",
            levels.direction,
            symbol,
            target_chat_id,
        )
        return True
    except requests.RequestException as e:
        logger.error("Помилка відправки в Telegram: %s", e)
        return False


def send_text(text: str, chat_id: str | int | None = None) -> bool:
    """
    Відправляє текст у Telegram.

    Якщо chat_id не переданий — шле в TELEGRAM_CHAT_ID з .env.
    Якщо chat_id переданий — шле конкретному користувачу/чату.
    """
    target_chat_id = str(chat_id) if chat_id is not None else telegram_cfg.chat_id

    if not telegram_cfg.bot_token or not target_chat_id:
        return False

    url = API_URL.format(token=telegram_cfg.bot_token)

    try:
        resp = requests.post(
            url,
            json={"chat_id": target_chat_id, "text": text},
            timeout=15,
        )
        resp.raise_for_status()
        return True
    except requests.RequestException as e:
        logger.error("Помилка відправки повідомлення в Telegram: %s", e)
        return False
    
def send_text_to_chat(chat_id: str | int, text: str) -> bool:
    return send_text(text=text, chat_id=chat_id)
