"""
storage.py
SQLite-зберігання: історія надісланих сигналів + cooldown-перевірка +
місце для подальшого логування фактичного результату сигналу (hit TP/SL),
щоб можна було відстежувати реальну точність моделі з часом, а не лише
на бектесті.
"""
import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Optional

from config import general_cfg
from levels import SignalLevels

logger = logging.getLogger("storage")

SCHEMA = """
CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    symbol TEXT NOT NULL,
    direction TEXT NOT NULL,
    entry_low REAL NOT NULL,
    entry_high REAL NOT NULL,
    sl REAL NOT NULL,
    tp1 REAL NOT NULL,
    tp2 REAL NOT NULL,
    tp3 REAL NOT NULL,
    tp4 REAL NOT NULL,
    probability REAL NOT NULL,
    outcome TEXT DEFAULT NULL,   -- NULL поки невідомо; далі: 'tp1'/'tp2'/'tp3'/'tp4'/'sl'/'open'
    closed_at TEXT DEFAULT NULL
);

CREATE TABLE IF NOT EXISTS heartbeats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL
);
"""


@contextmanager
def _connect():
    conn = sqlite3.connect(general_cfg.db_path)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with _connect() as conn:
        conn.executescript(SCHEMA)
    logger.info("БД ініціалізовано: %s", general_cfg.db_path)


def is_in_cooldown(symbol: str) -> bool:
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=general_cfg.signal_cooldown_min)).isoformat()
    with _connect() as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM signals WHERE symbol = ? AND created_at > ?",
            (symbol, cutoff),
        ).fetchone()
    return row[0] > 0


def save_signal(symbol: str, levels: SignalLevels, probability: float) -> int:
    with _connect() as conn:
        cur = conn.execute(
            """INSERT INTO signals
               (created_at, symbol, direction, entry_low, entry_high, sl, tp1, tp2, tp3, tp4, probability, outcome)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'open')""",
            (
                datetime.now(timezone.utc).isoformat(),
                symbol,
                levels.direction,
                levels.entry_low,
                levels.entry_high,
                levels.sl,
                levels.tp1,
                levels.tp2,
                levels.tp3,
                levels.tp4,
                probability,
            ),
        )
        return cur.lastrowid


def update_outcome(signal_id: int, outcome: str) -> None:
    """outcome: 'tp1' | 'tp2' | 'tp3' | 'tp4' | 'sl'. Викликається зовнішнім
    моніторингом ціни (не реалізовано в MVP — задокументовано в README як TODO)."""
    with _connect() as conn:
        conn.execute(
            "UPDATE signals SET outcome = ?, closed_at = ? WHERE id = ?",
            (outcome, datetime.now(timezone.utc).isoformat(), signal_id),
        )


def get_accuracy_summary(symbol: Optional[str] = None) -> dict:
    """Проста статистика по закритих сигналах — скільки дійшло бодай до TP1 vs SL."""
    query = "SELECT outcome, COUNT(*) FROM signals WHERE outcome IS NOT NULL AND outcome != 'open'"
    params = ()
    if symbol:
        query += " AND symbol = ?"
        params = (symbol,)
    query += " GROUP BY outcome"
    with _connect() as conn:
        rows = conn.execute(query, params).fetchall()
    return {outcome: count for outcome, count in rows}


def record_heartbeat() -> None:
    with _connect() as conn:
        conn.execute("INSERT INTO heartbeats (created_at) VALUES (?)", (datetime.now(timezone.utc).isoformat(),))
