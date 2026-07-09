"""
mt5_client.py
Обгортка над офіційним пакетом MetaTrader5 (MetaQuotes).

ВАЖЛИВО (архітектурне обмеження, не помилка коду):
Пакет MetaTrader5 працює ТІЛЬКИ на Windows і ТІЛЬКИ з локально запущеним
терміналом MT5 на цій же машині. Він не підключається "по мережі" до чужого
термінала. Тому бот і термінал повинні бути на одному Windows-сервері/ПК.

Тут закладено:
- reconnect-логіку (термінал може відвалитись через розрив мережі,
  нічну паузу брокера, оновлення термінала тощо)
- отримання останніх N свічок по символу/таймфрейму
- отримання поточної ціни (bid/ask) для формування зони входу
"""
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd

try:
    import MetaTrader5 as mt5
except ImportError:  # дозволяє імпортувати модуль для лінтингу/тестів поза Windows
    mt5 = None

from config import mt5_cfg

logger = logging.getLogger("mt5_client")

TIMEFRAME_MAP = {
    "M1": "TIMEFRAME_M1",
    "M5": "TIMEFRAME_M5",
    "M15": "TIMEFRAME_M15",
    "M30": "TIMEFRAME_M30",
    "H1": "TIMEFRAME_H1",
    "H4": "TIMEFRAME_H4",
    "D1": "TIMEFRAME_D1",
}


class MT5ConnectionError(Exception):
    pass


@dataclass
class Tick:
    bid: float
    ask: float
    time: datetime


class MT5Client:
    def __init__(self):
        if mt5 is None:
            raise RuntimeError(
                "Пакет MetaTrader5 не встановлено або платформа не Windows. "
                "Встановіть: pip install MetaTrader5 (тільки на Windows)."
            )
        self._connected = False
        tf_name = TIMEFRAME_MAP.get(mt5_cfg.timeframe.upper())
        if tf_name is None:
            raise ValueError(f"Невідомий таймфрейм у .env: {mt5_cfg.timeframe}")
        self._timeframe = getattr(mt5, tf_name)

    def connect(self) -> None:
        """Підключення до терміналу з ретраями. Кидає MT5ConnectionError, якщо не вдалось."""
        attempts = 0
        while attempts < mt5_cfg.reconnect_max_attempts:
            attempts += 1
            kwargs = {}
            if mt5_cfg.terminal_path:
                kwargs["path"] = mt5_cfg.terminal_path
            if mt5_cfg.login and mt5_cfg.password and mt5_cfg.server:
                kwargs.update(
                    login=mt5_cfg.login,
                    password=mt5_cfg.password,
                    server=mt5_cfg.server,
                )
            ok = mt5.initialize(**kwargs)
            if ok:
                info = mt5.terminal_info()
                account = mt5.account_info()
                logger.info(
                    "MT5 підключено. Термінал: %s, рахунок: %s",
                    getattr(info, "name", "?"),
                    getattr(account, "login", "?"),
                )
                if not mt5.symbol_select(mt5_cfg.symbol, True):
                    logger.warning(
                        "Не вдалось вибрати символ %s у Market Watch — перевірте назву "
                        "(деякі брокери використовують XAUUSD.m, XAUUSD.pro тощо)",
                        mt5_cfg.symbol,
                    )
                self._connected = True
                return
            err = mt5.last_error()
            logger.warning(
                "Спроба підключення %d/%d не вдалась: %s",
                attempts,
                mt5_cfg.reconnect_max_attempts,
                err,
            )
            time.sleep(mt5_cfg.reconnect_delay_sec)

        raise MT5ConnectionError(
            f"Не вдалось підключитись до MT5 після {mt5_cfg.reconnect_max_attempts} спроб"
        )

    def ensure_connected(self) -> None:
        """Викликати перед кожною операцією читання даних — перепідключає при потребі."""
        if not self._connected or mt5.terminal_info() is None:
            logger.warning("З'єднання з MT5 втрачено, перепідключаюсь...")
            self._connected = False
            self.connect()

    def get_candles(self, count: Optional[int] = None) -> pd.DataFrame:
        """Повертає DataFrame з колонками: time, open, high, low, close, tick_volume."""
        self.ensure_connected()
        n = count or mt5_cfg.bars_lookback
        rates = mt5.copy_rates_from_pos(mt5_cfg.symbol, self._timeframe, 0, n)
        if rates is None or len(rates) == 0:
            raise MT5ConnectionError(
                f"copy_rates_from_pos повернув порожній результат: {mt5.last_error()}"
            )
        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s")
        return df[["time", "open", "high", "low", "close", "tick_volume"]]

    def get_history(self, years: int) -> pd.DataFrame:
        """Тягне історію за N років для тренування моделі (скільки віддасть термінал)."""
        self.ensure_connected()
        date_to = datetime.now()
        # timedelta замість date_to.replace(year=...), бо .replace кине ValueError
        # 29 лютого, якщо цільовий рік не високосний.
        date_from = date_to - timedelta(days=365 * years)
        rates = mt5.copy_rates_range(mt5_cfg.symbol, self._timeframe, date_from, date_to)
        if rates is None or len(rates) == 0:
            raise MT5ConnectionError(
                f"copy_rates_range повернув порожній результат: {mt5.last_error()}"
            )
        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s")
        logger.info("Отримано %d свічок історії (%d років)", len(df), years)
        return df[["time", "open", "high", "low", "close", "tick_volume"]]

    def get_tick(self) -> Tick:
        self.ensure_connected()
        tick = mt5.symbol_info_tick(mt5_cfg.symbol)
        if tick is None:
            raise MT5ConnectionError(f"symbol_info_tick не повернув дані: {mt5.last_error()}")
        return Tick(bid=tick.bid, ask=tick.ask, time=datetime.fromtimestamp(tick.time))

    def shutdown(self) -> None:
        if mt5 is not None:
            mt5.shutdown()
        self._connected = False
