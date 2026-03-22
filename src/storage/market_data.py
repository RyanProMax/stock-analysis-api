"""
本地 SQLite 行情仓

存储 A 股 symbol 元数据、日线数据和同步任务记录。
"""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Generator, Iterable, Optional

import pandas as pd

from ..data_provider.base import BaseStockDataSource


class MarketDataStorage:
    """SQLite 行情仓存储封装。"""

    def __init__(self, db_path: Optional[str] = None):
        cache_root = os.environ.get("CACHE_DIR") or ".cache"
        self.db_path = Path(
            db_path or os.environ.get("MARKET_DATA_DB_PATH") or (Path(cache_root) / "market_data.sqlite")
        )
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    @contextmanager
    def connect(self) -> Generator[sqlite3.Connection, None, None]:
        conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA journal_mode=WAL")
        except sqlite3.OperationalError:
            # 允许在已有锁或只读场景下退化为默认模式，避免导入期直接失败。
            pass
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def initialize(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS symbols (
                    symbol TEXT PRIMARY KEY,
                    ts_code TEXT,
                    name TEXT,
                    market TEXT NOT NULL,
                    list_date TEXT,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS daily_bars (
                    symbol TEXT NOT NULL,
                    trade_date TEXT NOT NULL,
                    open REAL,
                    high REAL,
                    low REAL,
                    close REAL,
                    volume REAL,
                    amount REAL,
                    turnover_rate REAL,
                    source TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (symbol, trade_date),
                    FOREIGN KEY (symbol) REFERENCES symbols(symbol)
                );

                CREATE INDEX IF NOT EXISTS idx_daily_bars_symbol_date
                ON daily_bars(symbol, trade_date DESC);

                CREATE TABLE IF NOT EXISTS sync_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    ended_at TEXT,
                    status TEXT NOT NULL,
                    total_symbols INTEGER NOT NULL DEFAULT 0,
                    success_count INTEGER NOT NULL DEFAULT 0,
                    failure_count INTEGER NOT NULL DEFAULT 0,
                    error_summary TEXT
                );
                """
            )

    def upsert_symbols(self, rows: Iterable[Dict[str, Any]]) -> int:
        payload = []
        updated_at = self._now_iso()
        for row in rows:
            symbol = str(row.get("symbol") or "").strip().upper()
            if not symbol:
                continue
            payload.append(
                (
                    symbol,
                    row.get("ts_code"),
                    row.get("name"),
                    self._normalize_market(row.get("market")),
                    row.get("list_date"),
                    updated_at,
                )
            )
        if not payload:
            return 0

        with self.connect() as conn:
            conn.executemany(
                """
                INSERT INTO symbols(symbol, ts_code, name, market, list_date, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol) DO UPDATE SET
                    ts_code=excluded.ts_code,
                    name=excluded.name,
                    market=excluded.market,
                    list_date=excluded.list_date,
                    updated_at=excluded.updated_at
                """,
                payload,
            )
        return len(payload)

    def upsert_daily_bars(
        self,
        symbol: str,
        daily_df: pd.DataFrame,
        source: str,
    ) -> int:
        if daily_df is None or daily_df.empty:
            return 0

        normalized_symbol = str(symbol).strip().upper()
        updated_at = self._now_iso()
        payload = []
        for _, row in daily_df.iterrows():
            trade_date = self._normalize_trade_date(row.get("date"))
            if trade_date is None:
                continue
            payload.append(
                (
                    normalized_symbol,
                    trade_date,
                    self._float_or_none(row.get("open")),
                    self._float_or_none(row.get("high")),
                    self._float_or_none(row.get("low")),
                    self._float_or_none(row.get("close")),
                    self._float_or_none(row.get("volume")),
                    self._float_or_none(row.get("amount")),
                    self._float_or_none(row.get("turnover"))
                    or self._float_or_none(row.get("turnover_rate")),
                    source or "unknown",
                    updated_at,
                )
            )
        if not payload:
            return 0

        with self.connect() as conn:
            conn.executemany(
                """
                INSERT INTO daily_bars(
                    symbol, trade_date, open, high, low, close, volume, amount, turnover_rate, source, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol, trade_date) DO UPDATE SET
                    open=excluded.open,
                    high=excluded.high,
                    low=excluded.low,
                    close=excluded.close,
                    volume=excluded.volume,
                    amount=excluded.amount,
                    turnover_rate=excluded.turnover_rate,
                    source=excluded.source,
                    updated_at=excluded.updated_at
                """,
                payload,
            )
        return len(payload)

    def load_daily_bars(
        self,
        symbol: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> pd.DataFrame:
        normalized_symbol = str(symbol).strip().upper()
        clauses = ["symbol = ?"]
        params: list[Any] = [normalized_symbol]

        if start_date:
            clauses.append("trade_date >= ?")
            params.append(start_date)
        if end_date:
            clauses.append("trade_date <= ?")
            params.append(end_date)

        base_query = f"""
            SELECT trade_date AS date, open, high, low, close, volume, amount, turnover_rate AS turnover
            FROM daily_bars
            WHERE {' AND '.join(clauses)}
            ORDER BY trade_date ASC
        """
        query = base_query
        if limit is not None and limit > 0:
            query = f"""
                SELECT * FROM (
                    SELECT trade_date AS date, open, high, low, close, volume, amount, turnover_rate AS turnover
                    FROM daily_bars
                    WHERE {' AND '.join(clauses)}
                    ORDER BY trade_date DESC
                    LIMIT ?
                ) ORDER BY date ASC
            """
            params.append(limit)

        with self.connect() as conn:
            df = pd.read_sql_query(query, conn, params=params)

        if df.empty:
            return df

        df = BaseStockDataSource._clean_daily(df)
        return BaseStockDataSource._calculate_indicators(df)

    def get_symbol_record(self, symbol: str) -> Optional[Dict[str, Any]]:
        normalized_symbol = str(symbol).strip().upper()
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT symbol, ts_code, name, market, list_date, updated_at
                FROM symbols
                WHERE symbol = ?
                """,
                (normalized_symbol,),
            ).fetchone()
        if row is None:
            return None
        return dict(row)

    def get_latest_trade_date(self, symbol: str) -> Optional[str]:
        normalized_symbol = str(symbol).strip().upper()
        with self.connect() as conn:
            row = conn.execute(
                "SELECT MAX(trade_date) AS latest_trade_date FROM daily_bars WHERE symbol = ?",
                (normalized_symbol,),
            ).fetchone()
        if row is None:
            return None
        return row["latest_trade_date"]

    def start_sync_run(self, source: str, mode: str, total_symbols: int) -> int:
        with self.connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO sync_runs(source, mode, started_at, status, total_symbols)
                VALUES (?, ?, ?, ?, ?)
                """,
                (source, mode, self._now_iso(), "running", total_symbols),
            )
            return int(cursor.lastrowid)

    def finish_sync_run(
        self,
        run_id: int,
        status: str,
        success_count: int,
        failure_count: int,
        error_summary: Optional[str] = None,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE sync_runs
                SET ended_at = ?, status = ?, success_count = ?, failure_count = ?, error_summary = ?
                WHERE id = ?
                """,
                (self._now_iso(), status, success_count, failure_count, error_summary, run_id),
            )

    @staticmethod
    def _normalize_trade_date(value: Any) -> Optional[str]:
        if value is None:
            return None
        try:
            return pd.Timestamp(value).strftime("%Y-%m-%d")
        except Exception:
            return None

    @staticmethod
    def _normalize_market(value: Any) -> str:
        text = str(value or "").strip().lower()
        if text in {"主板", "创业板", "科创板", "北交所", "cn", "a股"}:
            return "cn"
        if text in {"us", "美股"}:
            return "us"
        return "cn"

    @staticmethod
    def _float_or_none(value: Any) -> Optional[float]:
        if value is None or value == "":
            return None
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return None
        return numeric

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()


market_data_storage = MarketDataStorage()
