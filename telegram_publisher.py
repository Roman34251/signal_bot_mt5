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


def send_signal(symbol: str, levels: SignalLevels, probability: float) -> bool:
    if not telegram_cfg.bot_token or not telegram_cfg.chat_id:
        logger.error("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID не задані в .env")
        return False

    text = _format_message(symbol, levels, probability)
    url = API_URL.format(token=telegram_cfg.bot_token)
    try:
        resp = requests.post(
            url,
            json={"chat_id": telegram_cfg.chat_id, "text": text},
            timeout=15,
        )
        resp.raise_for_status()
        logger.info("Сигнал %s %s надіслано в Telegram", levels.direction, symbol)
        return True
    except requests.RequestException as e:
        logger.error("Помилка відправки в Telegram: %s", e)
        return False


def send_text(text: str) -> bool:
    if not telegram_cfg.bot_token or not telegram_cfg.chat_id:
        return False
    url = API_URL.format(token=telegram_cfg.bot_token)
    try:
        resp = requests.post(url, json={"chat_id": telegram_cfg.chat_id, "text": text}, timeout=15)
        resp.raise_for_status()
        return True
    except requests.RequestException as e:
        logger.error("Помилка відправки heartbeat в Telegram: %s", e)
        return False
    
def send_text_to_chat(chat_id: str | int, text: str) -> bool:
    """
    Відправляє повідомлення в конкретний Telegram chat_id.
    Потрібно для відповідей на /start, /help, /price.
    """
    if not telegram_cfg.bot_token:
        logger.error("TELEGRAM_BOT_TOKEN не заданий в .env")
        return False

    url = API_URL.format(token=telegram_cfg.bot_token)

    try:
        resp = requests.post(
            url,
            json={"chat_id": str(chat_id), "text": text},
            timeout=15,
        )
        resp.raise_for_status()
        return True
    except requests.RequestException as e:
        logger.error("Помилка відправки повідомлення в chat_id=%s: %s", chat_id, e)
        return False
    
def send_text_to_chat(chat_id: str | int, text: str) -> bool:
    return send_text(text=text, chat_id=chat_id)
