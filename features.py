"""
features.py
Розрахунок технічних індикаторів/фіч з OHLC-даних для XGBoost-моделі.
Без сторонніх TA-бібліотек — тільки pandas/numpy, щоб не тягнути зайві залежності
та мати повний контроль над формулами (важливо для узгодженості train/inference).
"""
import numpy as np
import pandas as pd


def _ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def _rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi.fillna(50)


def _atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    tr = pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False).mean()


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    df: колонки time, open, high, low, close, tick_volume (відсортовано за часом зростаюче).
    Повертає той самий df з доданими колонками фіч. Перші ~50 рядків матимуть NaN
    (недостатньо історії для indicators) — їх треба відкидати перед тренуванням/інференсом.
    """
    out = df.copy()
    close = out["close"]

    out["ema_9"] = _ema(close, 9)
    out["ema_21"] = _ema(close, 21)
    out["ema_50"] = _ema(close, 50)
    out["ema_diff_9_21"] = out["ema_9"] - out["ema_21"]
    out["ema_diff_21_50"] = out["ema_21"] - out["ema_50"]

    out["rsi_14"] = _rsi(close, 14)
    out["atr_14"] = _atr(out, 14)
    # ATR як % від ціни — щоб фіча була порівнянна між різними ціновими режимами золота
    out["atr_pct"] = out["atr_14"] / close

    out["momentum_5"] = close.pct_change(5)
    out["momentum_10"] = close.pct_change(10)

    out["volatility_20"] = close.pct_change().rolling(20).std()

    # Позиція ціни відносно нещодавнього діапазону (0 = на мінімумі, 1 = на максимумі)
    roll_high = out["high"].rolling(20).max()
    roll_low = out["low"].rolling(20).min()
    out["range_position"] = (close - roll_low) / (roll_high - roll_low).replace(0, np.nan)

    out["body_size"] = (out["close"] - out["open"]).abs() / out["atr_14"].replace(0, np.nan)
    out["upper_wick"] = (out["high"] - out[["open", "close"]].max(axis=1)) / out["atr_14"].replace(0, np.nan)
    out["lower_wick"] = (out[["open", "close"]].min(axis=1) - out["low"]) / out["atr_14"].replace(0, np.nan)

    return out


FEATURE_COLUMNS = [
    "ema_diff_9_21",
    "ema_diff_21_50",
    "rsi_14",
    "atr_pct",
    "momentum_5",
    "momentum_10",
    "volatility_20",
    "range_position",
    "body_size",
    "upper_wick",
    "lower_wick",
]
