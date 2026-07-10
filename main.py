"""
main.py
Точка входу. Розрахований на роботу 24/7 на Windows-сервері без нагляду:
- нескінченний цикл з обробкою винятків на кожній ітерації (одна помилка не вбиває процес)
- автоперепідключення до MT5 (див. mt5_client.ensure_connected)
- heartbeat у Telegram, щоб було видно, що бот живий
- cooldown, щоб не спамити однаковими сигналами

Запуск на сервері (коротко, повна інструкція в README.md):
  1. Термінал MT5 запущений і залогінений на VPS.
  2. python main.py — вручну для перевірки.
  3. Для 24/7 без відкритої консолі — обгорнути через nssm у Windows-службу
     або через Task Scheduler ("At startup").
"""
import argparse
from http import client
import logging
import os
import time
from datetime import datetime, timezone
from telegram_commands import TelegramCommandPoller
from config import general_cfg, levels_cfg, mt5_cfg, model_cfg, telegram_cfg
from levels import calculate_levels
from mt5_client import MT5ConnectionError
import storage
import telegram_publisher
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from mt5_client import MT5Client
    from ml_model import SignalModel
# Важкі залежності (pandas/xgboost/MetaTrader5) імпортуються ліниво всередині
# live-режиму, щоб `python main.py --test-telegram` можна було запустити маючи
# лише requests + python-dotenv (перевірка Telegram без MT5 і без моделі).

# Каталог для лог-файлу треба створити ДО того, як FileHandler спробує його відкрити,
# інакше logging.basicConfig кине FileNotFoundError ще на етапі імпорту.
os.makedirs(os.path.dirname(general_cfg.log_path) or ".", exist_ok=True)

logging.basicConfig(
    level=getattr(logging, general_cfg.log_level.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(general_cfg.log_path, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("main")


def run_iteration(client: "MT5Client", model: "SignalModel", last_bar_time):
    """Один прохід. Повертає час останньої обробленої закритої свічки.

    Інференс робиться рівно один раз на кожну нову ЗАКРИТУ свічку: на H1 опитування
    раз на 30с давало б 120 однакових прогнозів на годину.
    """
    from features import build_features

    df = client.get_candles()  # тільки закриті свічки
    bar_time = df["time"].iloc[-1]
    if bar_time == last_bar_time:
        logger.debug("Нової закритої свічки ще немає (остання: %s)", bar_time)
        return last_bar_time

    df_feat = build_features(df).dropna().reset_index(drop=True)
    if df_feat.empty:
        logger.warning("Недостатньо даних для розрахунку фіч цієї ітерації")
        return last_bar_time

    last_row = df_feat.iloc[[-1]]
    prediction = model.predict(last_row)
    atr = float(last_row["atr_14"].iloc[0])
    tick = client.get_tick()
    spread = tick.ask - tick.bid

    logger.info(
        "Свічка %s | P(buy)=%.3f P(sell)=%.3f поріг=%.2f | bid=%.2f ask=%.2f spread=%.2f ATR=%.2f",
        bar_time,
        prediction.probability_buy,
        prediction.probability_sell,
        model_cfg.probability_threshold,
        tick.bid,
        tick.ask,
        spread,
        atr,
    )

    if storage.is_in_cooldown(mt5_cfg.symbol):
        logger.debug("Cooldown активний, сигнал пропущено")
        return bar_time

    direction = None
    probability = 0.0
    if prediction.probability_buy >= model_cfg.probability_threshold:
        direction = "BUY"
        probability = prediction.probability_buy
    elif prediction.probability_sell >= model_cfg.probability_threshold:
        direction = "SELL"
        probability = prediction.probability_sell

    if direction is None:
        return bar_time

    # Обробка спреду: широкий спред з'їдає TP1 (0.8*ATR) — краще пропустити сигнал.
    max_spread = atr * levels_cfg.max_spread_atr_ratio
    if spread > max_spread:
        logger.warning(
            "Сигнал %s пропущено: спред %.2f > %.2f (%.0f%% від ATR %.2f)",
            direction,
            spread,
            max_spread,
            levels_cfg.max_spread_atr_ratio * 100,
            atr,
        )
        return bar_time

    # Вхід за реальною ціною виконання: BUY купуємо по ask, SELL продаємо по bid.
    entry_price = tick.ask if direction == "BUY" else tick.bid
    levels = calculate_levels(direction, entry_price, atr)
    signal_id = storage.save_signal(mt5_cfg.symbol, levels, probability)
    sent = telegram_publisher.send_signal(mt5_cfg.symbol, levels, probability)
    logger.info(
        "Сигнал #%d %s %s збережено (Telegram: %s)",
        signal_id,
        direction,
        mt5_cfg.symbol,
        "надіслано" if sent else "ПОМИЛКА відправки",
    )
    return bar_time


def self_test_telegram() -> None:
    """Перевірка наскрізного зв'язку з Telegram БЕЗ MT5 і без натренованої моделі.
    Шле heartbeat + один зразковий сигнал у форматі, який отримуватимуть підписники,
    щоб можна було одразу глянути в ТГ, чи все налаштовано (токен/chat_id/формат)."""
    logger.info("Self-test Telegram: шлю тестові повідомлення (MT5/модель не потрібні)")
    ok_hb = telegram_publisher.send_text(
        f"✅ Self-test: бот на зв'язку. {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')} UTC"
    )
    # Зразкові рівні для XAUUSD (ціна/ATR умовні, лише для перевірки формату повідомлення)
    sample = calculate_levels("BUY", current_price=2350.0, atr=15.0)
    ok_sig = telegram_publisher.send_signal(mt5_cfg.symbol, sample, probability=0.87)

    if ok_hb and ok_sig:
        logger.info("Self-test УСПІШНИЙ — обидва повідомлення в Telegram. Перевірте чат.")
    else:
        logger.error(
            "Self-test НЕ пройдено (heartbeat=%s, signal=%s). "
            "Перевірте TELEGRAM_BOT_TOKEN і TELEGRAM_CHAT_ID у .env, "
            "а також що бота додано в чат/канал.",
            ok_hb,
            ok_sig,
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Signal bot XAUUSD (MT5 + XGBoost)")
    parser.add_argument(
        "--test-telegram",
        action="store_true",
        help="Надіслати тестовий сигнал у Telegram і вийти (без MT5 і без моделі)",
    )
    args = parser.parse_args()

    if args.test_telegram:
        self_test_telegram()
        return

    logger.info("Запуск signal bot (MT5 + XGBoost)")

    # Ліниві імпорти важких залежностей — лише для live-режиму.
    from ml_model import SignalModel
    from mt5_client import MT5Client, MT5ConnectionError

    storage.init_db()

    model = SignalModel(model_cfg.model_path, model_cfg.meta_path)
    model.load()

    client = MT5Client()
    client.connect()

    from telegram_commands import TelegramCommandPoller
    command_poller = TelegramCommandPoller()

    last_heartbeat = datetime.min.replace(tzinfo=timezone.utc)
    last_market_poll = datetime.min.replace(tzinfo=timezone.utc)
    last_bar_time = None

    while True:
        try:
            now = datetime.now(timezone.utc)

            # 1. Перевіряємо Telegram-команди часто
            command_poller.poll(client)

            # 2. Ринкову логіку запускаємо по MT5_POLL_INTERVAL_SEC
            elapsed_market_sec = (now - last_market_poll).total_seconds()
            if elapsed_market_sec >= mt5_cfg.poll_interval_sec:
                last_bar_time = run_iteration(client, model, last_bar_time)
                last_market_poll = now

            # 3. Heartbeat
            if telegram_cfg.heartbeat_enabled:
                elapsed_min = (now - last_heartbeat).total_seconds() / 60
                if elapsed_min >= telegram_cfg.heartbeat_interval_min:
                    # last_heartbeat оновлюємо в будь-якому разі, інакше при
                    # непрацюючому Telegram спроба повторювалась би щоітерації.
                    last_heartbeat = now
                    if telegram_publisher.send_text(
                        f"✅ Бот працює. {now.strftime('%Y-%m-%d %H:%M')} UTC"
                    ):
                        storage.record_heartbeat()
                    else:
                        logger.error(
                            "Heartbeat НЕ доставлено в Telegram — перевірте "
                            "TELEGRAM_CHAT_ID / TELEGRAM_BOT_TOKEN у .env"
                        )

        except MT5ConnectionError as e:
            logger.error("Проблема з MT5-з'єднанням: %s. Наступна спроба через паузу.", e)
        except Exception as e:
            logger.exception("Неочікувана помилка в основному циклі: %s", e)

        time.sleep(2)


if __name__ == "__main__":
    main()



 
