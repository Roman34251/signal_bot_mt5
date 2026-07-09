"""
levels.py
Розрахунок Entry-зони, Stop Loss та Take Profit 1-4, ATR-based —
універсально для будь-якого цінового режиму золота (не хардкоджені пункти).

Формат відповідає прикладам, наданим користувачем:
BUY XAU/USD
  Entry: 4148 - 4151
  Stop loss (SL): 4128
  Take profit 1: 4154.4
  ...
"""
from dataclasses import dataclass

from config import levels_cfg


@dataclass
class SignalLevels:
    direction: str  # "BUY" | "SELL"
    entry_low: float
    entry_high: float
    sl: float
    tp1: float
    tp2: float
    tp3: float
    tp4: float


def _round_price(x: float) -> float:
    # Золото зазвичай котирується з 1-2 знаками після коми
    return round(x, 2)


def calculate_levels(direction: str, current_price: float, atr: float) -> SignalLevels:
    if direction not in ("BUY", "SELL"):
        raise ValueError("direction має бути 'BUY' або 'SELL'")
    if atr <= 0:
        raise ValueError("ATR має бути додатнім для розрахунку рівнів")

    half_zone = levels_cfg.entry_zone_points / 2

    if direction == "BUY":
        entry_low = current_price - half_zone
        entry_high = current_price + half_zone
        sl = current_price - atr * levels_cfg.sl_atr_mult
        tp1 = current_price + atr * levels_cfg.tp1_atr_mult
        tp2 = current_price + atr * levels_cfg.tp2_atr_mult
        tp3 = current_price + atr * levels_cfg.tp3_atr_mult
        tp4 = current_price + atr * levels_cfg.tp4_atr_mult
    else:  # SELL
        entry_low = current_price - half_zone
        entry_high = current_price + half_zone
        sl = current_price + atr * levels_cfg.sl_atr_mult
        tp1 = current_price - atr * levels_cfg.tp1_atr_mult
        tp2 = current_price - atr * levels_cfg.tp2_atr_mult
        tp3 = current_price - atr * levels_cfg.tp3_atr_mult
        tp4 = current_price - atr * levels_cfg.tp4_atr_mult

    return SignalLevels(
        direction=direction,
        entry_low=_round_price(entry_low),
        entry_high=_round_price(entry_high),
        sl=_round_price(sl),
        tp1=_round_price(tp1),
        tp2=_round_price(tp2),
        tp3=_round_price(tp3),
        tp4=_round_price(tp4),
    )
