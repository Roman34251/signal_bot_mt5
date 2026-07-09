"""
train_model.py
Тренування XGBoost-моделі на реальній історії з MT5.

Розмітка (triple-barrier, стандартний підхід у фінансовому ML):
Для кожної свічки дивимось вперед на `label_horizon_bars` барів і перевіряємо,
яка "стінка" пробивається першою:
  - верхня (close + min_atr_move * ATR) -> це був би BUY, що дійшов до TP -> label_buy=1
  - нижня (close - min_atr_move * ATR) -> label_sell=1
  - жодна за горизонт -> обидва 0 (боковик / рух замалий)
Це чесніше за "просто дивимось чи ціна вища через N барів", бо враховує саме ту
логіку, за якою потім рахуються SL/TP у levels.py.

Walk-forward валідація: дані діляться на K послідовних фолдів у часовому порядку.
Модель тренується тільки на минулому і перевіряється на "майбутньому" відносно
себе фолді — так видно реальну здатність узагальнювати, а не підгонку під історію.

ЧЕСНО: на фінансових часових рядах будь-яка модель буде мати посередню точність.
Скрипт друкує precision/recall по кожному фолду — орієнтуйтесь на ці цифри,
а не на віру в "80% точності" з дефолту.
"""
import argparse
import logging

import numpy as np
import pandas as pd
from sklearn.metrics import precision_score, recall_score, roc_auc_score

from config import mt5_cfg, model_cfg
from features import build_features, FEATURE_COLUMNS
from ml_model import SignalModel
from mt5_client import MT5Client

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("train_model")


def triple_barrier_labels(
    df: pd.DataFrame, horizon: int, min_atr_move: float
) -> tuple[pd.Series, pd.Series]:
    close = df["close"].values
    high = df["high"].values
    low = df["low"].values
    atr = df["atr_14"].values
    n = len(df)

    label_buy = np.zeros(n, dtype=int)
    label_sell = np.zeros(n, dtype=int)

    for i in range(n - horizon):
        if np.isnan(atr[i]) or atr[i] == 0:
            continue
        upper = close[i] + min_atr_move * atr[i]
        lower = close[i] - min_atr_move * atr[i]
        window_high = high[i + 1 : i + 1 + horizon]
        window_low = low[i + 1 : i + 1 + horizon]

        hit_upper_idx = np.argmax(window_high >= upper) if np.any(window_high >= upper) else -1
        hit_lower_idx = np.argmax(window_low <= lower) if np.any(window_low <= lower) else -1

        if hit_upper_idx == -1 and hit_lower_idx == -1:
            continue
        if hit_lower_idx == -1 or (hit_upper_idx != -1 and hit_upper_idx <= hit_lower_idx):
            label_buy[i] = 1
        else:
            label_sell[i] = 1

    return pd.Series(label_buy, index=df.index), pd.Series(label_sell, index=df.index)


def load_dataset_from_csv(path: str) -> pd.DataFrame:
    df = pd.read_csv(path, parse_dates=["time"])
    required = {"time", "open", "high", "low", "close", "tick_volume"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"У CSV бракує колонок: {missing}")
    return df.sort_values("time").reset_index(drop=True)


def walk_forward_evaluate(df_feat: pd.DataFrame, folds: int) -> None:
    n = len(df_feat)
    fold_size = n // (folds + 1)
    threshold = model_cfg.probability_threshold

    logger.info("Walk-forward валідація: %d фолдів, поріг=%.2f", folds, threshold)
    for fold in range(folds):
        train_end = fold_size * (fold + 1)
        test_end = fold_size * (fold + 2)
        train_df = df_feat.iloc[:train_end]
        test_df = df_feat.iloc[train_end:test_end]
        if len(test_df) < 20:
            continue

        y_buy_train, y_sell_train = triple_barrier_labels(
            train_df, model_cfg.label_horizon_bars, model_cfg.label_min_atr_move
        )
        y_buy_test, y_sell_test = triple_barrier_labels(
            test_df, model_cfg.label_horizon_bars, model_cfg.label_min_atr_move
        )

        model = SignalModel(model_cfg.model_path, model_cfg.meta_path)
        model.train(train_df, y_buy_train, y_sell_train)

        p_buy = model.model_buy.predict_proba(test_df[FEATURE_COLUMNS])[:, 1]
        p_sell = model.model_sell.predict_proba(test_df[FEATURE_COLUMNS])[:, 1]

        pred_buy = (p_buy >= threshold).astype(int)
        pred_sell = (p_sell >= threshold).astype(int)

        def safe_metric(fn, y_true, y_pred):
            try:
                return fn(y_true, y_pred, zero_division=0)
            except Exception:
                return float("nan")

        logger.info(
            "Фолд %d/%d | BUY: precision=%.3f recall=%.3f auc=%.3f (n_signals=%d) | "
            "SELL: precision=%.3f recall=%.3f auc=%.3f (n_signals=%d)",
            fold + 1,
            folds,
            safe_metric(precision_score, y_buy_test, pred_buy),
            safe_metric(recall_score, y_buy_test, pred_buy),
            roc_auc_score(y_buy_test, p_buy) if y_buy_test.nunique() > 1 else float("nan"),
            int(pred_buy.sum()),
            safe_metric(precision_score, y_sell_test, pred_sell),
            safe_metric(recall_score, y_sell_test, pred_sell),
            roc_auc_score(y_sell_test, p_sell) if y_sell_test.nunique() > 1 else float("nan"),
            int(pred_sell.sum()),
        )


def main():
    parser = argparse.ArgumentParser(description="Тренування ML-моделі сигналів на XAUUSD")
    parser.add_argument("--csv", type=str, default=None, help="Шлях до CSV з історією замість MT5")
    parser.add_argument("--skip-walk-forward", action="store_true")
    args = parser.parse_args()

    if args.csv:
        raw_df = load_dataset_from_csv(args.csv)
    else:
        client = MT5Client()
        client.connect()
        raw_df = client.get_history(model_cfg.train_history_years)
        client.shutdown()

    logger.info("Завантажено %d свічок сирих даних", len(raw_df))
    df_feat = build_features(raw_df).dropna().reset_index(drop=True)
    logger.info("Після розрахунку фіч і відкидання NaN: %d рядків", len(df_feat))

    if not args.skip_walk_forward:
        walk_forward_evaluate(df_feat, model_cfg.walk_forward_folds)
        print(
            "\n>>> Перегляньте precision вище. Якщо precision на BUY/SELL суттєво нижчий "
            "за ваші очікування — підніміть MODEL_PROBABILITY_THRESHOLD у .env або "
            "переглянте набір фіч, перш ніж довіряти сигналам.\n"
        )

    # Фінальне тренування на ВСІХ доступних даних (для продакшн-використання)
    y_buy_all, y_sell_all = triple_barrier_labels(
        df_feat, model_cfg.label_horizon_bars, model_cfg.label_min_atr_move
    )
    final_model = SignalModel(model_cfg.model_path, model_cfg.meta_path)
    final_model.train(df_feat, y_buy_all, y_sell_all)
    final_model.save(
        meta={
            "trained_rows": len(df_feat),
            "symbol": mt5_cfg.symbol,
            "timeframe": mt5_cfg.timeframe,
            "label_horizon_bars": model_cfg.label_horizon_bars,
            "label_min_atr_move": model_cfg.label_min_atr_move,
            "feature_columns": FEATURE_COLUMNS,
        }
    )
    logger.info("Фінальну модель натреновано і збережено.")


if __name__ == "__main__":
    main()
