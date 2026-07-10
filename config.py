"""
config.py
Централізована конфігурація. Всі значення читаються з .env через python-dotenv.
Ніяких секретів у коді — тільки тут перелічені назви змінних і дефолти.
"""
import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


def _get_bool(name: str, default: bool) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


def _get_int(name: str, default: int) -> int:
    val = os.getenv(name)
    return int(val) if val else default


def _get_float(name: str, default: float) -> float:
    val = os.getenv(name)
    return float(val) if val else default


@dataclass
class MT5Config:
    login: int = _get_int("MT5_LOGIN", 0)
    password: str = os.getenv("MT5_PASSWORD", "")
    server: str = os.getenv("MT5_SERVER", "")
    # Шлях до terminal64.exe. Якщо MT5 вже запущений і залогінений вручну —
    # можна лишити пустим, mt5.initialize() підхопить активний термінал.
    terminal_path: str = os.getenv("MT5_TERMINAL_PATH", "")
    symbol: str = os.getenv("MT5_SYMBOL", "XAUUSD")
    # Таймфрейм для розрахунку сигналів. Мапиться на mt5.TIMEFRAME_* в mt5_client.py
    timeframe: str = os.getenv("MT5_TIMEFRAME", "H1")
    # Скільки останніх свічок тягнути на кожній ітерації для розрахунку фіч
    bars_lookback: int = _get_int("MT5_BARS_LOOKBACK", 500)
    # Інтервал опитування термінала (секунди). Для H1 немає сенсу частіше за 30-60с.
    poll_interval_sec: int = _get_int("MT5_POLL_INTERVAL_SEC", 30)
    # Скільки разів намагатись перепідключитись перед тим як почекати довше
    reconnect_max_attempts: int = _get_int("MT5_RECONNECT_MAX_ATTEMPTS", 5)
    reconnect_delay_sec: int = _get_int("MT5_RECONNECT_DELAY_SEC", 15)


@dataclass
class ModelConfig:
    model_path: str = os.getenv("MODEL_PATH", "models/xgb_xauusd.json")
    meta_path: str = os.getenv("MODEL_META_PATH", "models/xgb_xauusd_meta.json")
    # Поріг ймовірності для генерації сигналу. НЕ довіряти дефолту 80% сліпо —
    # підбирається за результатами walk-forward тесту в train_model.py
    probability_threshold: float = _get_float("MODEL_PROBABILITY_THRESHOLD", 0.65)
    # Скільки свічок вперед дивимось при розмітці "успішний/неуспішний рух" для тренування
    label_horizon_bars: int = _get_int("MODEL_LABEL_HORIZON_BARS", 6)
    # Мінімальний рух у ATR, щоб вважати рух "значущим" для класу 1
    label_min_atr_move: float = _get_float("MODEL_LABEL_MIN_ATR_MOVE", 1.0)
    # Скільки років історії тягнути для тренування (якщо термінал дозволяє)
    train_history_years: int = _get_int("MODEL_TRAIN_HISTORY_YEARS", 3)
    # Кількість walk-forward фолдів
    walk_forward_folds: int = _get_int("MODEL_WALK_FORWARD_FOLDS", 5)


@dataclass
class LevelsConfig:
    atr_period: int = _get_int("LEVELS_ATR_PERIOD", 14)
    sl_atr_mult: float = _get_float("LEVELS_SL_ATR_MULT", 1.5)
    tp1_atr_mult: float = _get_float("LEVELS_TP1_ATR_MULT", 0.8)
    tp2_atr_mult: float = _get_float("LEVELS_TP2_ATR_MULT", 1.6)
    tp3_atr_mult: float = _get_float("LEVELS_TP3_ATR_MULT", 2.8)
    tp4_atr_mult: float = _get_float("LEVELS_TP4_ATR_MULT", 5.0)
    # Ширина зони входу (Entry: 4148-4151), у пунктах ціни золота
    entry_zone_points: float = _get_float("LEVELS_ENTRY_ZONE_POINTS", 3.0)
    # Захист від широкого спреду (нічна сесія, новини): якщо spread > ATR * цей
    # коефіцієнт — сигнал пропускається, бо TP1 (0.8*ATR) з'їдається спредом.
    max_spread_atr_ratio: float = _get_float("LEVELS_MAX_SPREAD_ATR_RATIO", 0.15)


@dataclass
class TelegramConfig:
    bot_token: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id: str = os.getenv("TELEGRAM_CHAT_ID", "")

    # Якщо true — будь-хто може писати /start і /price.
    # Якщо false — команди приймаються тільки від TELEGRAM_CHAT_ID.
    public_commands: bool = _get_bool("TELEGRAM_PUBLIC_COMMANDS", False)

    # Чи слати heartbeat "бот працює" раз на N хвилин
    heartbeat_enabled: bool = _get_bool("TELEGRAM_HEARTBEAT_ENABLED", True)
    heartbeat_interval_min: int = _get_int("TELEGRAM_HEARTBEAT_INTERVAL_MIN", 60)


@dataclass
class GeneralConfig:
    # Мінімальний інтервал між двома сигналами по одному й тому ж символу (анти-спам)
    signal_cooldown_min: int = _get_int("SIGNAL_COOLDOWN_MIN", 60)
    db_path: str = os.getenv("DB_PATH", "signals.db")
    log_path: str = os.getenv("LOG_PATH", "logs/bot.log")
    log_level: str = os.getenv("LOG_LEVEL", "INFO")


    
mt5_cfg = MT5Config()
model_cfg = ModelConfig()
levels_cfg = LevelsConfig()
telegram_cfg = TelegramConfig()
general_cfg = GeneralConfig()
