"""
ml_model.py
Тонка обгортка над XGBoost для бінарної класифікації "буде значущий рух вгору/вниз".
Дві окремі моделі: одна на BUY-сигнали, одна на SELL-сигнали (простіше й прозоріше
за одну multi-class модель, і дозволяє генерувати обидва типи сигналів незалежно).
"""
import json
import logging
import os
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd
import xgboost as xgb

from features import FEATURE_COLUMNS

logger = logging.getLogger("ml_model")


@dataclass
class Prediction:
    probability_buy: float
    probability_sell: float


class SignalModel:
    def __init__(self, model_path: str, meta_path: str):
        self.model_path = model_path
        self.meta_path = meta_path
        self.model_buy: Optional[xgb.XGBClassifier] = None
        self.model_sell: Optional[xgb.XGBClassifier] = None
        self.meta: dict = {}

    # --- тренування -----------------------------------------------------
    def train(
        self,
        X_train: pd.DataFrame,
        y_train_buy: pd.Series,
        y_train_sell: pd.Series,
        params: Optional[dict] = None,
    ) -> None:
        default_params = dict(
            n_estimators=300,
            max_depth=4,
            learning_rate=0.05,
            subsample=0.8,
            colsample_bytree=0.8,
            eval_metric="logloss",
            n_jobs=-1,
        )
        if params:
            default_params.update(params)

        self.model_buy = xgb.XGBClassifier(**default_params)
        self.model_buy.fit(X_train[FEATURE_COLUMNS], y_train_buy)

        self.model_sell = xgb.XGBClassifier(**default_params)
        self.model_sell.fit(X_train[FEATURE_COLUMNS], y_train_sell)

    # --- інференс ---------------------------------------------------------
    def predict(self, X_row: pd.DataFrame) -> Prediction:
        if self.model_buy is None or self.model_sell is None:
            raise RuntimeError("Модель не завантажена. Викличте load() або train() спочатку.")
        p_buy = float(self.model_buy.predict_proba(X_row[FEATURE_COLUMNS])[:, 1][0])
        p_sell = float(self.model_sell.predict_proba(X_row[FEATURE_COLUMNS])[:, 1][0])
        return Prediction(probability_buy=p_buy, probability_sell=p_sell)

    # --- збереження / завантаження -----------------------------------------
    def save(self, meta: dict) -> None:
        os.makedirs(os.path.dirname(self.model_path) or ".", exist_ok=True)
        self.model_buy.save_model(self.model_path.replace(".json", "_buy.json"))
        self.model_sell.save_model(self.model_path.replace(".json", "_sell.json"))
        with open(self.meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
        logger.info("Модель збережено: %s", self.model_path)

    def load(self) -> None:
        buy_path = self.model_path.replace(".json", "_buy.json")
        sell_path = self.model_path.replace(".json", "_sell.json")
        if not (os.path.exists(buy_path) and os.path.exists(sell_path)):
            raise FileNotFoundError(
                f"Файли моделі не знайдено ({buy_path}, {sell_path}). "
                "Спочатку запустіть train_model.py"
            )
        self.model_buy = xgb.XGBClassifier()
        self.model_buy.load_model(buy_path)
        self.model_sell = xgb.XGBClassifier()
        self.model_sell.load_model(sell_path)
        if os.path.exists(self.meta_path):
            with open(self.meta_path, "r", encoding="utf-8") as f:
                self.meta = json.load(f)
        logger.info("Модель завантажено з %s", self.model_path)
