"""
本地 SQLite 行情仓 Repository。

统一管理 cn/us symbol 元数据、日线数据和同步任务记录。
"""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Generator, Iterable, Optional

import pandas as pd


class MarketDataRepository:
    """SQLite 行情仓 Repository。"""

    SYMBOL_COLUMNS = (
        "symbol",
        "ts_code",
        "name",
        "area",
        "industry",
        "market",
        "exchange",
        "list_date",
        "updated_at",
        "extra",
    )
    DAILY_COLUMNS = (
        "symbol",
        "ts_code",
        "trade_date",
        "open",
        "high",
        "low",
        "close",
        "pre_close",
        "change",
        "pct_chg",
        "vol",
        "amount",
        "adj_factor",
        "is_suspended",
        "up_limit",
        "down_limit",
        "source",
        "updated_at",
        "extra",
    )
    SYMBOL_EXTRA_KEYS = ("fullname", "curr_type", "is_hs", "country", "currency", "sector_raw")
    DAILY_EXTRA_KEYS = (
        "turnover_rate",
        "vwap",
        "free_share",
        "total_share",
        "free_mv",
        "total_mv",
    )
    DAILY_ALIAS_KEYS = {
        "date",
        "volume",
        "turnover",
    }
    NON_FACT_DAILY_KEYS = {
        "ma5",
        "ma10",
        "ma20",
        "rsi",
        "macd",
        "kdj",
        "boll",
        "volume_ratio",
        "trend",
        "breakout_state",
    }

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
                DROP INDEX IF EXISTS idx_daily_bars_symbol_date;
                DROP INDEX IF EXISTS idx_a_share_daily_symbol_date;
                DROP TABLE IF EXISTS daily_bars;
                DROP TABLE IF EXISTS symbols;
                DROP TABLE IF EXISTS a_share_symbols;
                DROP TABLE IF EXISTS a_share_daily;

                CREATE TABLE IF NOT EXISTS cn_symbols (
                    symbol TEXT PRIMARY KEY,
                    ts_code TEXT,
                    name TEXT,
                    area TEXT,
                    industry TEXT,
                    market TEXT,
                    exchange TEXT,
                    list_date TEXT,
                    updated_at TEXT NOT NULL,
                    extra TEXT
                );

                CREATE TABLE IF NOT EXISTS us_symbols (
                    symbol TEXT PRIMARY KEY,
                    ts_code TEXT,
                    name TEXT,
                    area TEXT,
                    industry TEXT,
                    market TEXT,
                    exchange TEXT,
                    list_date TEXT,
                    updated_at TEXT NOT NULL,
                    extra TEXT
                );

                CREATE TABLE IF NOT EXISTS cn_daily (
                    symbol TEXT NOT NULL,
                    ts_code TEXT,
                    trade_date TEXT NOT NULL,
                    open REAL,
                    high REAL,
                    low REAL,
                    close REAL,
                    pre_close REAL,
                    change REAL,
                    pct_chg REAL,
                    vol REAL,
                    amount REAL,
                    adj_factor REAL,
                    is_suspended INTEGER,
                    up_limit REAL,
                    down_limit REAL,
                    source TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    extra TEXT,
                    PRIMARY KEY (symbol, trade_date)
                );

                CREATE TABLE IF NOT EXISTS us_daily (
                    symbol TEXT NOT NULL,
                    ts_code TEXT,
                    trade_date TEXT NOT NULL,
                    open REAL,
                    high REAL,
                    low REAL,
                    close REAL,
                    pre_close REAL,
                    change REAL,
                    pct_chg REAL,
                    vol REAL,
                    amount REAL,
                    adj_factor REAL,
                    is_suspended INTEGER,
                    up_limit REAL,
                    down_limit REAL,
                    source TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    extra TEXT,
                    PRIMARY KEY (symbol, trade_date)
                );

                CREATE INDEX IF NOT EXISTS idx_cn_daily_symbol_date
                ON cn_daily(symbol, trade_date DESC);

                CREATE INDEX IF NOT EXISTS idx_us_daily_symbol_date
                ON us_daily(symbol, trade_date DESC);

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

    def upsert_symbols(self, rows: Iterable[Dict[str, Any]], market: Optional[str] = None) -> int:
        normalized_market = self._normalize_market(market) if market else None
        updated_at = self._now_iso()
        payload_by_market: dict[str, list[tuple[Any, ...]]] = {"cn": [], "us": []}

        for row in rows:
            symbol = str(row.get("symbol") or "").strip().upper()
            if not symbol:
                continue
            row_market = normalized_market or self._normalize_market(row.get("market") or symbol)
            extra = self._encode_extra(row, self.SYMBOL_COLUMNS, self.SYMBOL_EXTRA_KEYS)
            payload_by_market[row_market].append(
                (
                    symbol,
                    row.get("ts_code") or self._default_ts_code(symbol, row_market),
                    row.get("name"),
                    row.get("area"),
                    row.get("industry"),
                    row.get("market") or ("A股" if row_market == "cn" else "美股"),
                    row.get("exchange") or self._infer_exchange(row.get("ts_code"), row_market),
                    row.get("list_date"),
                    updated_at,
                    extra,
                )
            )

        inserted = 0
        with self.connect() as conn:
            for row_market, payload in payload_by_market.items():
                if not payload:
                    continue
                conn.executemany(
                    f"""
                    INSERT INTO {self._symbols_table(row_market)}(
                        symbol, ts_code, name, area, industry, market, exchange, list_date, updated_at, extra
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(symbol) DO UPDATE SET
                        ts_code=excluded.ts_code,
                        name=excluded.name,
                        area=excluded.area,
                        industry=excluded.industry,
                        market=excluded.market,
                        exchange=excluded.exchange,
                        list_date=excluded.list_date,
                        updated_at=excluded.updated_at,
                        extra=excluded.extra
                    """,
                    payload,
                )
                inserted += len(payload)
        return inserted

    def replace_symbols(self, rows: Iterable[Dict[str, Any]], market: str) -> int:
        normalized_market = self._normalize_market(market)
        table = self._symbols_table(normalized_market)
        with self.connect() as conn:
            conn.execute(f"DELETE FROM {table}")
        return self.upsert_symbols(rows, market=normalized_market)

    def upsert_daily_bars(
        self,
        symbol: str,
        daily_df: pd.DataFrame,
        source: str,
        market: Optional[str] = None,
        ts_code: Optional[str] = None,
    ) -> int:
        if daily_df is None or daily_df.empty:
            return 0

        normalized_symbol = str(symbol).strip().upper()
        normalized_market = self._normalize_market(market or normalized_symbol)
        normalized_ts_code = ts_code or self._default_ts_code(normalized_symbol, normalized_market)
        updated_at = self._now_iso()

        df = daily_df.copy()
        date_col = "trade_date" if "trade_date" in df.columns else "date"
        if date_col not in df.columns:
            return 0
        df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
        df = df.dropna(subset=[date_col]).sort_values(date_col, ascending=True).reset_index(drop=True)
        if df.empty:
            return 0

        payload = []
        previous_close: Optional[float] = None
        for _, row in df.iterrows():
            trade_date = self._normalize_trade_date(row.get(date_col))
            if trade_date is None:
                continue

            open_price = self._float_or_none(row.get("open"))
            high_price = self._float_or_none(row.get("high"))
            low_price = self._float_or_none(row.get("low"))
            close_price = self._float_or_none(row.get("close"))
            pre_close = self._float_or_none(row.get("pre_close"))
            if pre_close is None:
                pre_close = previous_close

            change = self._float_or_none(row.get("change"))
            if change is None and close_price is not None and pre_close is not None:
                change = close_price - pre_close

            pct_chg = self._float_or_none(row.get("pct_chg"))
            if pct_chg is None and change is not None and pre_close not in (None, 0):
                pct_chg = change / pre_close * 100.0

            vol = self._float_or_none(row.get("vol"))
            if vol is None:
                vol = self._float_or_none(row.get("volume"))

            extra = self._build_daily_extra(row)
            payload.append(
                (
                    normalized_symbol,
                    row.get("ts_code") or normalized_ts_code,
                    trade_date,
                    open_price,
                    high_price,
                    low_price,
                    close_price,
                    pre_close,
                    change,
                    pct_chg,
                    vol,
                    self._float_or_none(row.get("amount")),
                    self._float_or_none(row.get("adj_factor")),
                    self._bool_to_int(row.get("is_suspended")),
                    self._float_or_none(row.get("up_limit")),
                    self._float_or_none(row.get("down_limit")),
                    source or "unknown",
                    updated_at,
                    extra,
                )
            )
            if close_price is not None:
                previous_close = close_price

        if not payload:
            return 0

        with self.connect() as conn:
            conn.executemany(
                f"""
                INSERT INTO {self._daily_table(normalized_market)}(
                    symbol, ts_code, trade_date, open, high, low, close, pre_close,
                    change, pct_chg, vol, amount, adj_factor, is_suspended,
                    up_limit, down_limit, source, updated_at, extra
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol, trade_date) DO UPDATE SET
                    ts_code=excluded.ts_code,
                    open=excluded.open,
                    high=excluded.high,
                    low=excluded.low,
                    close=excluded.close,
                    pre_close=excluded.pre_close,
                    change=excluded.change,
                    pct_chg=excluded.pct_chg,
                    vol=excluded.vol,
                    amount=excluded.amount,
                    adj_factor=excluded.adj_factor,
                    is_suspended=excluded.is_suspended,
                    up_limit=excluded.up_limit,
                    down_limit=excluded.down_limit,
                    source=excluded.source,
                    updated_at=excluded.updated_at,
                    extra=excluded.extra
                """,
                payload,
            )
        return len(payload)

    def load_daily_bars(
        self,
        symbol: str,
        market: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> pd.DataFrame:
        normalized_symbol = str(symbol).strip().upper()
        normalized_market = self._normalize_market(market or normalized_symbol)
        clauses = ["symbol = ?"]
        params: list[Any] = [normalized_symbol]

        if start_date:
            clauses.append("trade_date >= ?")
            params.append(start_date)
        if end_date:
            clauses.append("trade_date <= ?")
            params.append(end_date)

        base_select = """
            SELECT
                trade_date AS date,
                ts_code,
                open,
                high,
                low,
                close,
                pre_close,
                change,
                pct_chg,
                vol AS volume,
                amount,
                adj_factor,
                is_suspended,
                up_limit,
                down_limit,
                extra
        """
        query = f"""
            {base_select}
            FROM {self._daily_table(normalized_market)}
            WHERE {' AND '.join(clauses)}
            ORDER BY trade_date ASC
        """
        if limit is not None and limit > 0:
            query = f"""
                SELECT * FROM (
                    {base_select}
                    FROM {self._daily_table(normalized_market)}
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

        df["turnover"] = None
        df["vwap"] = None
        for idx, extra_text in enumerate(df.pop("extra")):
            extra = self._decode_extra(extra_text)
            if "turnover_rate" in extra:
                df.at[idx, "turnover"] = extra.get("turnover_rate")
            if "vwap" in extra:
                df.at[idx, "vwap"] = extra.get("vwap")
        return df

    def get_symbol_record(self, symbol: str, market: Optional[str] = None) -> Optional[Dict[str, Any]]:
        normalized_symbol = str(symbol).strip().upper()
        normalized_market = self._normalize_market(market or normalized_symbol)
        with self.connect() as conn:
            row = conn.execute(
                f"""
                SELECT symbol, ts_code, name, area, industry, market, exchange, list_date, updated_at, extra
                FROM {self._symbols_table(normalized_market)}
                WHERE symbol = ?
                """,
                (normalized_symbol,),
            ).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["extra"] = self._decode_extra(result.get("extra"))
        return result

    def list_symbols(
        self,
        market: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> list[Dict[str, Any]]:
        normalized_market = self._normalize_market(market) if market else None
        if normalized_market:
            query = self._symbol_query(self._symbols_table(normalized_market), limit)
            params: list[Any] = [] if limit is None or limit < 0 else [limit]
        else:
            limit_clause = "" if limit is None or limit < 0 else " LIMIT ?"
            query = f"""
                SELECT * FROM (
                    SELECT symbol, ts_code, name, area, industry, market, exchange, list_date, updated_at, extra
                    FROM cn_symbols
                    UNION ALL
                    SELECT symbol, ts_code, name, area, industry, market, exchange, list_date, updated_at, extra
                    FROM us_symbols
                ) ORDER BY symbol ASC{limit_clause}
            """
            params = [] if limit is None or limit < 0 else [limit]

        with self.connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._decode_symbol_row(dict(row)) for row in rows]

    def search_symbols(
        self,
        keyword: str,
        market: Optional[str] = None,
    ) -> list[Dict[str, Any]]:
        normalized_keyword = str(keyword or "").strip().upper()
        if not normalized_keyword:
            return []

        like = f"%{normalized_keyword}%"
        params = [like, like, like]
        where_clause = """
            WHERE UPPER(symbol) LIKE ? OR UPPER(COALESCE(ts_code, '')) LIKE ? OR UPPER(COALESCE(name, '')) LIKE ?
        """
        normalized_market = self._normalize_market(market) if market else None

        if normalized_market:
            query = f"""
                SELECT symbol, ts_code, name, area, industry, market, exchange, list_date, updated_at, extra
                FROM {self._symbols_table(normalized_market)}
                {where_clause}
                ORDER BY symbol ASC
            """
        else:
            query = f"""
                SELECT * FROM (
                    SELECT symbol, ts_code, name, area, industry, market, exchange, list_date, updated_at, extra
                    FROM cn_symbols
                    UNION ALL
                    SELECT symbol, ts_code, name, area, industry, market, exchange, list_date, updated_at, extra
                    FROM us_symbols
                )
                {where_clause}
                ORDER BY symbol ASC
            """

        with self.connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._decode_symbol_row(dict(row)) for row in rows]

    def get_latest_trade_date(self, symbol: str, market: Optional[str] = None) -> Optional[str]:
        normalized_symbol = str(symbol).strip().upper()
        normalized_market = self._normalize_market(market or normalized_symbol)
        with self.connect() as conn:
            row = conn.execute(
                f"SELECT MAX(trade_date) AS latest_trade_date FROM {self._daily_table(normalized_market)} WHERE symbol = ?",
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

    def update_sync_run_progress(
        self,
        run_id: int,
        success_count: int,
        failure_count: int,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE sync_runs
                SET success_count = ?, failure_count = ?
                WHERE id = ?
                """,
                (success_count, failure_count, run_id),
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
        if text in {"cn", "a股", "主板", "创业板", "科创板", "北交所", "sse", "szse"}:
            return "cn"
        if text in {"us", "美股", "nasdaq", "nyse", "amex"}:
            return "us"
        if any(ch.isalpha() for ch in str(value or "")) and str(value or "").strip().upper().isalpha():
            return "us"
        return "cn"

    @staticmethod
    def _symbols_table(market: str) -> str:
        return "cn_symbols" if market == "cn" else "us_symbols"

    @staticmethod
    def _daily_table(market: str) -> str:
        return "cn_daily" if market == "cn" else "us_daily"

    @staticmethod
    def _default_ts_code(symbol: str, market: str) -> str:
        if market == "us":
            return f"{symbol}.US"
        if symbol.startswith("6"):
            return f"{symbol}.SH"
        return f"{symbol}.SZ"

    @classmethod
    def _infer_exchange(cls, ts_code: Any, market: str) -> Optional[str]:
        text = str(ts_code or "").upper()
        if text.endswith(".SH"):
            return "SSE"
        if text.endswith(".SZ"):
            return "SZSE"
        if text.endswith(".US") or market == "us":
            return "NASDAQ"
        return None

    @classmethod
    def _encode_extra(
        cls,
        row: Dict[str, Any],
        main_columns: Iterable[str],
        allowed_keys: Iterable[str],
    ) -> Optional[str]:
        extra: Dict[str, Any] = {}
        existing_extra = row.get("extra")
        if isinstance(existing_extra, dict):
            extra.update(existing_extra)

        main_set = set(main_columns)
        allowed_set = set(allowed_keys)
        for key in allowed_set:
            if key in main_set:
                continue
            value = row.get(key)
            if value is not None and value != "":
                extra[key] = value

        cleaned = {
            key: value
            for key, value in extra.items()
            if key not in main_set and value is not None and value != ""
        }
        if not cleaned:
            return None
        return json.dumps(cleaned, ensure_ascii=False, sort_keys=True)

    @classmethod
    def _build_daily_extra(cls, row: pd.Series) -> Optional[str]:
        extra: Dict[str, Any] = {}
        if isinstance(row.get("extra"), dict):
            extra.update(row.get("extra"))

        for key in cls.DAILY_EXTRA_KEYS:
            value = row.get(key)
            if value is not None and value != "":
                if not (isinstance(value, float) and pd.isna(value)):
                    extra[key] = value

        cleaned = {
            key: value
            for key, value in extra.items()
            if key not in cls.DAILY_COLUMNS
            and key not in cls.DAILY_ALIAS_KEYS
            and key not in cls.NON_FACT_DAILY_KEYS
            and value is not None
            and value != ""
        }
        if not cleaned:
            return None
        return json.dumps(cleaned, ensure_ascii=False, sort_keys=True)

    @staticmethod
    def _decode_extra(extra: Any) -> Dict[str, Any]:
        if extra in (None, "", b""):
            return {}
        if isinstance(extra, dict):
            return extra
        try:
            payload = json.loads(str(extra))
        except Exception:
            return {}
        return payload if isinstance(payload, dict) else {}

    @classmethod
    def _decode_symbol_row(cls, row: Dict[str, Any]) -> Dict[str, Any]:
        row["extra"] = cls._decode_extra(row.get("extra"))
        return row

    @staticmethod
    def _symbol_query(table: str, limit: Optional[int]) -> str:
        limit_clause = "" if limit is None or limit < 0 else " LIMIT ?"
        return f"""
            SELECT symbol, ts_code, name, area, industry, market, exchange, list_date, updated_at, extra
            FROM {table}
            ORDER BY symbol ASC{limit_clause}
        """

    @staticmethod
    def _float_or_none(value: Any) -> Optional[float]:
        if value is None or value == "":
            return None
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return None
        if pd.isna(numeric):
            return None
        return numeric

    @staticmethod
    def _bool_to_int(value: Any) -> Optional[int]:
        if value is None or value == "":
            return None
        if isinstance(value, bool):
            return int(value)
        text = str(value).strip().lower()
        if text in {"1", "true", "yes", "y"}:
            return 1
        if text in {"0", "false", "no", "n"}:
            return 0
        try:
            return 1 if int(value) else 0
        except Exception:
            return None

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()


market_data_repository = MarketDataRepository()
