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

    STALE_GRACE_DAYS = 7

    SYMBOL_COLUMNS = (
        "symbol",
        "ts_code",
        "name",
        "area",
        "industry",
        "market",
        "exchange",
        "cnspell",
        "list_date",
        "daily_start_date",
        "daily_end_date",
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
        "turnover_rate",
        "turnover_rate_f",
        "volume_ratio",
        "pe",
        "pe_ttm",
        "pb",
        "ps",
        "ps_ttm",
        "dv_ratio",
        "dv_ttm",
        "float_share",
        "free_share",
        "total_share",
        "circ_mv",
        "total_mv",
        "adj_factor",
        "is_suspended",
        "up_limit",
        "down_limit",
        "source",
        "updated_at",
        "extra",
    )
    DAILY_BASIC_COLUMNS = (
        "turnover_rate",
        "turnover_rate_f",
        "volume_ratio",
        "pe",
        "pe_ttm",
        "pb",
        "ps",
        "ps_ttm",
        "dv_ratio",
        "dv_ttm",
        "float_share",
        "free_share",
        "total_share",
        "circ_mv",
        "total_mv",
    )
    SYMBOL_EXTRA_KEYS = (
        "fullname",
        "curr_type",
        "is_hs",
        "country",
        "currency",
        "sector_raw",
        "act_name",
        "act_ent_type",
    )
    DAILY_EXTRA_KEYS = ("vwap",)
    DAILY_ALIAS_KEYS = {"date", "volume", "turnover"}
    NON_FACT_DAILY_KEYS = {
        "ma5",
        "ma10",
        "ma20",
        "rsi",
        "macd",
        "kdj",
        "boll",
        "volume_ratio_state",
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
                    cnspell TEXT,
                    list_date TEXT,
                    daily_start_date TEXT,
                    daily_end_date TEXT,
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
                    cnspell TEXT,
                    list_date TEXT,
                    daily_start_date TEXT,
                    daily_end_date TEXT,
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
                    turnover_rate REAL,
                    turnover_rate_f REAL,
                    volume_ratio REAL,
                    pe REAL,
                    pe_ttm REAL,
                    pb REAL,
                    ps REAL,
                    ps_ttm REAL,
                    dv_ratio REAL,
                    dv_ttm REAL,
                    float_share REAL,
                    free_share REAL,
                    total_share REAL,
                    circ_mv REAL,
                    total_mv REAL,
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
                    turnover_rate REAL,
                    turnover_rate_f REAL,
                    volume_ratio REAL,
                    pe REAL,
                    pe_ttm REAL,
                    pb REAL,
                    ps REAL,
                    ps_ttm REAL,
                    dv_ratio REAL,
                    dv_ttm REAL,
                    float_share REAL,
                    free_share REAL,
                    total_share REAL,
                    circ_mv REAL,
                    total_mv REAL,
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
                    market TEXT,
                    scope TEXT,
                    symbol TEXT,
                    requested_start_date TEXT,
                    requested_end_date TEXT,
                    requested_days INTEGER,
                    requested_years INTEGER,
                    universe_source TEXT,
                    started_at TEXT NOT NULL,
                    ended_at TEXT,
                    status TEXT NOT NULL,
                    total_symbols INTEGER NOT NULL DEFAULT 0,
                    processed_count INTEGER NOT NULL DEFAULT 0,
                    skipped_count INTEGER NOT NULL DEFAULT 0,
                    success_count INTEGER NOT NULL DEFAULT 0,
                    failure_count INTEGER NOT NULL DEFAULT 0,
                    rows_written INTEGER NOT NULL DEFAULT 0,
                    error_summary TEXT,
                    error_details TEXT,
                    symbol_snapshot_count INTEGER,
                    symbol_snapshot_updated_at TEXT,
                    target_latest_trade_date TEXT,
                    coverage_start_date TEXT,
                    coverage_end_date TEXT,
                    covered_symbol_count INTEGER,
                    missing_symbol_count INTEGER,
                    stale_symbol_count INTEGER,
                    daily_row_count INTEGER,
                    is_data_current INTEGER
                );
                """
            )
            self._ensure_columns(
                conn,
                "cn_symbols",
                {
                    "cnspell": "TEXT",
                    "daily_start_date": "TEXT",
                    "daily_end_date": "TEXT",
                },
            )
            self._ensure_columns(
                conn,
                "us_symbols",
                {
                    "cnspell": "TEXT",
                    "daily_start_date": "TEXT",
                    "daily_end_date": "TEXT",
                },
            )
            self._ensure_columns(
                conn,
                "cn_daily",
                {
                    "turnover_rate": "REAL",
                    "turnover_rate_f": "REAL",
                    "volume_ratio": "REAL",
                    "pe": "REAL",
                    "pe_ttm": "REAL",
                    "pb": "REAL",
                    "ps": "REAL",
                    "ps_ttm": "REAL",
                    "dv_ratio": "REAL",
                    "dv_ttm": "REAL",
                    "float_share": "REAL",
                    "free_share": "REAL",
                    "total_share": "REAL",
                    "circ_mv": "REAL",
                    "total_mv": "REAL",
                },
            )
            self._ensure_columns(
                conn,
                "us_daily",
                {
                    "turnover_rate": "REAL",
                    "turnover_rate_f": "REAL",
                    "volume_ratio": "REAL",
                    "pe": "REAL",
                    "pe_ttm": "REAL",
                    "pb": "REAL",
                    "ps": "REAL",
                    "ps_ttm": "REAL",
                    "dv_ratio": "REAL",
                    "dv_ttm": "REAL",
                    "float_share": "REAL",
                    "free_share": "REAL",
                    "total_share": "REAL",
                    "circ_mv": "REAL",
                    "total_mv": "REAL",
                },
            )
            self._ensure_columns(
                conn,
                "sync_runs",
                {
                    "market": "TEXT",
                    "scope": "TEXT",
                    "symbol": "TEXT",
                    "requested_start_date": "TEXT",
                    "requested_end_date": "TEXT",
                    "requested_days": "INTEGER",
                    "requested_years": "INTEGER",
                    "universe_source": "TEXT",
                    "processed_count": "INTEGER NOT NULL DEFAULT 0",
                    "skipped_count": "INTEGER NOT NULL DEFAULT 0",
                    "rows_written": "INTEGER NOT NULL DEFAULT 0",
                    "error_details": "TEXT",
                    "symbol_snapshot_count": "INTEGER",
                    "symbol_snapshot_updated_at": "TEXT",
                    "target_latest_trade_date": "TEXT",
                    "coverage_start_date": "TEXT",
                    "coverage_end_date": "TEXT",
                    "covered_symbol_count": "INTEGER",
                    "missing_symbol_count": "INTEGER",
                    "stale_symbol_count": "INTEGER",
                    "daily_row_count": "INTEGER",
                    "is_data_current": "INTEGER",
                },
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
                    row.get("cnspell"),
                    row.get("list_date"),
                    row.get("daily_start_date"),
                    row.get("daily_end_date"),
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
                        symbol, ts_code, name, area, industry, market, exchange, cnspell, list_date,
                        daily_start_date, daily_end_date, updated_at, extra
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(symbol) DO UPDATE SET
                        ts_code=excluded.ts_code,
                        name=excluded.name,
                        area=excluded.area,
                        industry=excluded.industry,
                        market=excluded.market,
                        exchange=excluded.exchange,
                        cnspell=excluded.cnspell,
                        list_date=excluded.list_date,
                        daily_start_date=COALESCE(excluded.daily_start_date, daily_start_date),
                        daily_end_date=COALESCE(excluded.daily_end_date, daily_end_date),
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
            existing_summaries = {
                str(row["symbol"]).strip().upper(): {
                    "daily_start_date": row["daily_start_date"],
                    "daily_end_date": row["daily_end_date"],
                }
                for row in conn.execute(
                    f"SELECT symbol, daily_start_date, daily_end_date FROM {table}"
                ).fetchall()
            }

        normalized_rows: list[Dict[str, Any]] = []
        for row in rows:
            current = dict(row)
            summary = existing_summaries.get(str(current.get("symbol") or "").strip().upper(), {})
            if summary.get("daily_start_date") and not current.get("daily_start_date"):
                current["daily_start_date"] = summary["daily_start_date"]
            if summary.get("daily_end_date") and not current.get("daily_end_date"):
                current["daily_end_date"] = summary["daily_end_date"]
            normalized_rows.append(current)
        with self.connect() as conn:
            conn.execute(f"DELETE FROM {table}")
        return self.upsert_symbols(normalized_rows, market=normalized_market)

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

            circ_mv = row.get("circ_mv")
            if circ_mv in (None, ""):
                circ_mv = row.get("free_mv")

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
                    self._float_or_none(row.get("turnover_rate")),
                    self._float_or_none(row.get("turnover_rate_f")),
                    self._float_or_none(row.get("volume_ratio")),
                    self._float_or_none(row.get("pe")),
                    self._float_or_none(row.get("pe_ttm")),
                    self._float_or_none(row.get("pb")),
                    self._float_or_none(row.get("ps")),
                    self._float_or_none(row.get("ps_ttm")),
                    self._float_or_none(row.get("dv_ratio")),
                    self._float_or_none(row.get("dv_ttm")),
                    self._float_or_none(row.get("float_share")),
                    self._float_or_none(row.get("free_share")),
                    self._float_or_none(row.get("total_share")),
                    self._float_or_none(circ_mv),
                    self._float_or_none(row.get("total_mv")),
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
                    change, pct_chg, vol, amount, turnover_rate, turnover_rate_f, volume_ratio,
                    pe, pe_ttm, pb, ps, ps_ttm, dv_ratio, dv_ttm,
                    float_share, free_share, total_share, circ_mv, total_mv,
                    adj_factor, is_suspended, up_limit, down_limit, source, updated_at, extra
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    turnover_rate=excluded.turnover_rate,
                    turnover_rate_f=excluded.turnover_rate_f,
                    volume_ratio=excluded.volume_ratio,
                    pe=excluded.pe,
                    pe_ttm=excluded.pe_ttm,
                    pb=excluded.pb,
                    ps=excluded.ps,
                    ps_ttm=excluded.ps_ttm,
                    dv_ratio=excluded.dv_ratio,
                    dv_ttm=excluded.dv_ttm,
                    float_share=excluded.float_share,
                    free_share=excluded.free_share,
                    total_share=excluded.total_share,
                    circ_mv=excluded.circ_mv,
                    total_mv=excluded.total_mv,
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
        self.refresh_symbol_daily_coverage(normalized_symbol, market=normalized_market)
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
                turnover_rate,
                turnover_rate_f,
                volume_ratio,
                pe,
                pe_ttm,
                pb,
                ps,
                ps_ttm,
                dv_ratio,
                dv_ttm,
                float_share,
                free_share,
                total_share,
                circ_mv,
                total_mv,
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
            if df.at[idx, "turnover_rate"] is not None:
                df.at[idx, "turnover"] = df.at[idx, "turnover_rate"]
            elif "turnover_rate" in extra:
                df.at[idx, "turnover"] = extra.get("turnover_rate")
            if "vwap" in extra:
                df.at[idx, "vwap"] = extra.get("vwap")
        return df

    def bulk_update_cn_daily_basic(self, daily_basic_df: pd.DataFrame) -> int:
        if daily_basic_df is None or daily_basic_df.empty:
            return 0

        payload: list[tuple[Any, ...]] = []
        for row in daily_basic_df.to_dict("records"):
            ts_code = str(row.get("ts_code") or "").strip().upper()
            symbol = str(row.get("symbol") or ts_code.split(".")[0] if ts_code else "").strip().upper()
            trade_date = self._normalize_trade_date(row.get("trade_date") or row.get("date"))
            if not symbol or not trade_date:
                continue
            payload.append(
                tuple(self._float_or_none(row.get(column)) for column in self.DAILY_BASIC_COLUMNS)
                + (self._now_iso(), symbol, trade_date)
            )

        if not payload:
            return 0

        set_clause = ", ".join(f"{column} = ?" for column in self.DAILY_BASIC_COLUMNS)
        with self.connect() as conn:
            cursor = conn.executemany(
                f"""
                UPDATE cn_daily
                SET {set_clause}, updated_at = ?
                WHERE symbol = ? AND trade_date = ?
                """,
                payload,
            )
        return int(cursor.rowcount or 0)

    def refresh_symbol_daily_coverage(self, symbol: str, market: Optional[str] = None) -> None:
        normalized_symbol = str(symbol).strip().upper()
        normalized_market = self._normalize_market(market or normalized_symbol)
        with self.connect() as conn:
            row = conn.execute(
                f"""
                SELECT MIN(trade_date) AS daily_start_date, MAX(trade_date) AS daily_end_date
                FROM {self._daily_table(normalized_market)}
                WHERE symbol = ?
                """,
                (normalized_symbol,),
            ).fetchone()
            conn.execute(
                f"""
                UPDATE {self._symbols_table(normalized_market)}
                SET daily_start_date = ?, daily_end_date = ?, updated_at = ?
                WHERE symbol = ?
                """,
                (
                    row["daily_start_date"] if row else None,
                    row["daily_end_date"] if row else None,
                    self._now_iso(),
                    normalized_symbol,
                ),
            )

    def backfill_symbol_daily_coverage(self, market: Optional[str] = None) -> None:
        markets = [self._normalize_market(market)] if market else ["cn", "us"]
        with self.connect() as conn:
            for normalized_market in markets:
                conn.execute(
                    f"""
                    UPDATE {self._symbols_table(normalized_market)}
                    SET daily_start_date = (
                            SELECT MIN(d.trade_date)
                            FROM {self._daily_table(normalized_market)} d
                            WHERE d.symbol = {self._symbols_table(normalized_market)}.symbol
                        ),
                        daily_end_date = (
                            SELECT MAX(d.trade_date)
                            FROM {self._daily_table(normalized_market)} d
                            WHERE d.symbol = {self._symbols_table(normalized_market)}.symbol
                        )
                    """
                )

    def get_symbol_record(self, symbol: str, market: Optional[str] = None) -> Optional[Dict[str, Any]]:
        normalized_symbol = str(symbol).strip().upper()
        normalized_market = self._normalize_market(market or normalized_symbol)
        with self.connect() as conn:
            row = conn.execute(
                f"""
                SELECT symbol, ts_code, name, area, industry, market, exchange, cnspell, list_date,
                       daily_start_date, daily_end_date, updated_at, extra
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
                    SELECT symbol, ts_code, name, area, industry, market, exchange, cnspell, list_date,
                           daily_start_date, daily_end_date, updated_at, extra
                    FROM cn_symbols
                    UNION ALL
                    SELECT symbol, ts_code, name, area, industry, market, exchange, cnspell, list_date,
                           daily_start_date, daily_end_date, updated_at, extra
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
        params = [like, like, like, like]
        where_clause = """
            WHERE UPPER(symbol) LIKE ? OR UPPER(COALESCE(ts_code, '')) LIKE ? OR UPPER(COALESCE(name, '')) LIKE ? OR UPPER(COALESCE(cnspell, '')) LIKE ?
        """
        normalized_market = self._normalize_market(market) if market else None

        if normalized_market:
            query = f"""
                SELECT symbol, ts_code, name, area, industry, market, exchange, cnspell, list_date,
                       daily_start_date, daily_end_date, updated_at, extra
                FROM {self._symbols_table(normalized_market)}
                {where_clause}
                ORDER BY symbol ASC
            """
        else:
            query = f"""
                SELECT * FROM (
                    SELECT symbol, ts_code, name, area, industry, market, exchange, cnspell, list_date,
                           daily_start_date, daily_end_date, updated_at, extra
                    FROM cn_symbols
                    UNION ALL
                    SELECT symbol, ts_code, name, area, industry, market, exchange, cnspell, list_date,
                           daily_start_date, daily_end_date, updated_at, extra
                    FROM us_symbols
                )
                {where_clause}
                ORDER BY symbol ASC
            """

        with self.connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._decode_symbol_row(dict(row)) for row in rows]

    def get_symbol_snapshot_meta(self, market: str) -> Dict[str, Any]:
        normalized_market = self._normalize_market(market)
        with self.connect() as conn:
            row = conn.execute(
                f"""
                SELECT
                    COUNT(*) AS symbol_count,
                    MIN(updated_at) AS min_updated_at,
                    MAX(updated_at) AS max_updated_at
                FROM {self._symbols_table(normalized_market)}
                """
            ).fetchone()
        if row is None:
            return {"symbol_count": 0, "min_updated_at": None, "max_updated_at": None}
        return {
            "symbol_count": int(row["symbol_count"] or 0),
            "min_updated_at": row["min_updated_at"],
            "max_updated_at": row["max_updated_at"],
        }

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

    def start_sync_run(
        self,
        *,
        source: str,
        mode: str,
        market: Optional[str] = None,
        scope: Optional[str] = None,
        symbol: Optional[str] = None,
        requested_start_date: Optional[str] = None,
        requested_end_date: Optional[str] = None,
        requested_days: Optional[int] = None,
        requested_years: Optional[int] = None,
        universe_source: Optional[str] = None,
        total_symbols: int = 0,
    ) -> int:
        with self.connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO sync_runs(
                    source, mode, market, scope, symbol, requested_start_date, requested_end_date,
                    requested_days, requested_years, universe_source, started_at, status, total_symbols,
                    processed_count, skipped_count, success_count, failure_count, rows_written
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, 0, 0, 0)
                """,
                (
                    source,
                    mode,
                    market,
                    scope,
                    symbol,
                    requested_start_date,
                    requested_end_date,
                    requested_days,
                    requested_years,
                    universe_source,
                    self._now_iso(),
                    "running",
                    total_symbols,
                ),
            )
            return int(cursor.lastrowid)

    def get_latest_sync_run(self, mode: str) -> Optional[Dict[str, Any]]:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM sync_runs WHERE mode = ? ORDER BY id DESC LIMIT 1",
                (mode,),
            ).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["error_details"] = self._decode_json_text(result.get("error_details"))
        if result.get("is_data_current") is not None:
            result["is_data_current"] = bool(result["is_data_current"])
        return result

    def finish_sync_run(
        self,
        run_id: int,
        status: str,
        processed_count: int,
        skipped_count: int,
        success_count: int,
        failure_count: int,
        rows_written: int,
        error_summary: Optional[str] = None,
        error_details: Optional[Any] = None,
        state_snapshot: Optional[Dict[str, Any]] = None,
    ) -> None:
        snapshot = state_snapshot or {}
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE sync_runs
                SET ended_at = ?, status = ?, processed_count = ?, skipped_count = ?,
                    success_count = ?, failure_count = ?, rows_written = ?, error_summary = ?,
                    error_details = ?, symbol_snapshot_count = ?, symbol_snapshot_updated_at = ?,
                    target_latest_trade_date = ?, coverage_start_date = ?, coverage_end_date = ?,
                    covered_symbol_count = ?, missing_symbol_count = ?, stale_symbol_count = ?,
                    daily_row_count = ?, is_data_current = ?
                WHERE id = ?
                """,
                (
                    self._now_iso(),
                    status,
                    processed_count,
                    skipped_count,
                    success_count,
                    failure_count,
                    rows_written,
                    error_summary,
                    self._encode_json_text(error_details),
                    snapshot.get("symbol_snapshot_count"),
                    snapshot.get("symbol_snapshot_updated_at"),
                    snapshot.get("target_latest_trade_date"),
                    snapshot.get("coverage_start_date"),
                    snapshot.get("coverage_end_date"),
                    snapshot.get("covered_symbol_count"),
                    snapshot.get("missing_symbol_count"),
                    snapshot.get("stale_symbol_count"),
                    snapshot.get("daily_row_count"),
                    self._bool_to_int(snapshot.get("is_data_current")),
                    run_id,
                ),
            )

    def update_sync_run_progress(
        self,
        run_id: int,
        processed_count: int,
        skipped_count: int,
        success_count: int,
        failure_count: int,
        rows_written: int,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE sync_runs
                SET processed_count = ?, skipped_count = ?, success_count = ?, failure_count = ?, rows_written = ?
                WHERE id = ?
                """,
                (processed_count, skipped_count, success_count, failure_count, rows_written, run_id),
            )

    def summarize_market_sync_state(
        self,
        market: str,
        *,
        start_trade_date: Optional[str] = None,
        target_latest_trade_date: Optional[str] = None,
    ) -> Dict[str, Any]:
        normalized_market = self._normalize_market(market)
        symbols_table = self._symbols_table(normalized_market)
        daily_table = self._daily_table(normalized_market)

        with self.connect() as conn:
            symbol_row = conn.execute(
                f"""
                SELECT COUNT(*) AS symbol_snapshot_count, MAX(updated_at) AS symbol_snapshot_updated_at
                FROM {symbols_table}
                """
            ).fetchone()
            coverage_row = conn.execute(
                f"""
                SELECT
                    MIN(trade_date) AS coverage_start_date,
                    MAX(trade_date) AS coverage_end_date,
                    COUNT(*) AS daily_row_count
                FROM {daily_table}
                """
            ).fetchone()

            if start_trade_date:
                covered_row = conn.execute(
                    f"SELECT COUNT(DISTINCT symbol) AS covered_symbol_count FROM {daily_table} WHERE trade_date >= ?",
                    (start_trade_date,),
                ).fetchone()
                missing_row = conn.execute(
                    f"""
                    SELECT COUNT(*) AS missing_symbol_count
                    FROM {symbols_table} s
                    LEFT JOIN (
                        SELECT DISTINCT symbol FROM {daily_table} WHERE trade_date >= ?
                    ) d ON d.symbol = s.symbol
                    WHERE d.symbol IS NULL
                    """,
                    (start_trade_date,),
                ).fetchone()
            else:
                covered_row = conn.execute(
                    f"SELECT COUNT(DISTINCT symbol) AS covered_symbol_count FROM {daily_table}"
                ).fetchone()
                missing_row = conn.execute(
                    f"""
                    SELECT COUNT(*) AS missing_symbol_count
                    FROM {symbols_table} s
                    LEFT JOIN (
                        SELECT DISTINCT symbol FROM {daily_table}
                    ) d ON d.symbol = s.symbol
                    WHERE d.symbol IS NULL
                    """
                ).fetchone()

            stale_count = 0
            if target_latest_trade_date:
                try:
                    stale_cutoff = (
                        pd.Timestamp(target_latest_trade_date) - pd.Timedelta(days=self.STALE_GRACE_DAYS)
                    ).strftime("%Y-%m-%d")
                except Exception:
                    stale_cutoff = target_latest_trade_date
                stale_row = conn.execute(
                    f"""
                    SELECT COUNT(*) AS stale_symbol_count
                    FROM (
                        SELECT s.symbol, MAX(d.trade_date) AS latest_trade_date
                        FROM {symbols_table} s
                        LEFT JOIN {daily_table} d ON d.symbol = s.symbol
                        GROUP BY s.symbol
                    )
                    WHERE latest_trade_date IS NOT NULL AND latest_trade_date < ?
                    """,
                    (stale_cutoff,),
                ).fetchone()
                stale_count = int(stale_row["stale_symbol_count"] or 0)

        symbol_snapshot_count = int(symbol_row["symbol_snapshot_count"] or 0)
        coverage_start_date = coverage_row["coverage_start_date"] if coverage_row else None
        coverage_end_date = coverage_row["coverage_end_date"] if coverage_row else None
        covered_symbol_count = int(covered_row["covered_symbol_count"] or 0)
        missing_symbol_count = int(missing_row["missing_symbol_count"] or 0)
        daily_row_count = int(coverage_row["daily_row_count"] or 0)

        has_required_history = True
        if start_trade_date:
            has_required_history = coverage_start_date is not None and coverage_start_date <= start_trade_date

        is_data_current = (
            symbol_snapshot_count > 0
            and has_required_history
            and missing_symbol_count == 0
            and stale_count == 0
            and (target_latest_trade_date is None or coverage_end_date == target_latest_trade_date)
        )

        return {
            "symbol_snapshot_count": symbol_snapshot_count,
            "symbol_snapshot_updated_at": symbol_row["symbol_snapshot_updated_at"] if symbol_row else None,
            "target_latest_trade_date": target_latest_trade_date,
            "coverage_start_date": coverage_start_date,
            "coverage_end_date": coverage_end_date,
            "covered_symbol_count": covered_symbol_count,
            "missing_symbol_count": missing_symbol_count,
            "stale_symbol_count": stale_count,
            "daily_row_count": daily_row_count,
            "is_data_current": is_data_current,
        }

    def list_stale_symbols(
        self,
        market: str,
        *,
        stale_cutoff: str,
    ) -> list[Dict[str, Any]]:
        normalized_market = self._normalize_market(market)
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT symbol, latest_trade_date
                FROM (
                    SELECT s.symbol, MAX(d.trade_date) AS latest_trade_date
                    FROM {self._symbols_table(normalized_market)} s
                    LEFT JOIN {self._daily_table(normalized_market)} d ON d.symbol = s.symbol
                    GROUP BY s.symbol
                )
                WHERE latest_trade_date IS NOT NULL AND latest_trade_date < ?
                ORDER BY symbol ASC
                """,
                (stale_cutoff,),
            ).fetchall()
        return [
            {
                "symbol": str(row["symbol"]).strip().upper(),
                "latest_trade_date": row["latest_trade_date"],
            }
            for row in rows
        ]

    def get_symbol_date_ranges(
        self,
        market: str,
        *,
        symbols: Optional[Iterable[str]] = None,
    ) -> Dict[str, Dict[str, Any]]:
        normalized_market = self._normalize_market(market)
        normalized_symbols = sorted(
            {
                str(symbol).strip().upper()
                for symbol in (symbols or [])
                if str(symbol).strip()
            }
        )
        where_clause = ""
        params: list[Any] = []
        if normalized_symbols:
            placeholders = ", ".join("?" for _ in normalized_symbols)
            where_clause = f"WHERE symbol IN ({placeholders})"
            params.extend(normalized_symbols)
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT symbol, MIN(trade_date) AS min_trade_date, MAX(trade_date) AS max_trade_date, COUNT(*) AS row_count
                FROM {self._daily_table(normalized_market)}
                {where_clause}
                GROUP BY symbol
                """,
                params,
            ).fetchall()
        return {
            row["symbol"]: {
                "min_trade_date": row["min_trade_date"],
                "max_trade_date": row["max_trade_date"],
                "row_count": int(row["row_count"] or 0),
            }
            for row in rows
        }

    def list_symbols_missing_standardized_daily_fields(
        self,
        market: str,
        *,
        start_trade_date: Optional[str] = None,
    ) -> list[str]:
        normalized_market = self._normalize_market(market)
        if normalized_market != "cn":
            return []

        clauses = ["total_mv IS NULL"]
        params: list[Any] = []
        if start_trade_date:
            clauses.append("trade_date >= ?")
            params.append(start_trade_date)

        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT DISTINCT symbol
                FROM {self._daily_table(normalized_market)}
                WHERE {' AND '.join(clauses)}
                ORDER BY symbol ASC
                """,
                params,
            ).fetchall()
        return [str(row["symbol"]).strip().upper() for row in rows]

    def count_symbols(self, market: str) -> int:
        normalized_market = self._normalize_market(market)
        with self.connect() as conn:
            row = conn.execute(
                f"SELECT COUNT(*) AS count FROM {self._symbols_table(normalized_market)}"
            ).fetchone()
        return int(row["count"] or 0)

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
        if text in {"cn", "a股", "主板", "创业板", "科创板", "北交所", "sse", "szse", "bse"}:
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
        if symbol.startswith(("4", "8", "92")):
            return f"{symbol}.BJ"
        if symbol.startswith("6"):
            return f"{symbol}.SH"
        return f"{symbol}.SZ"

    @classmethod
    def _infer_exchange(cls, ts_code: Any, market: str) -> Optional[str]:
        text = str(ts_code or "").upper()
        if text.endswith(".BJ"):
            return "BSE"
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
            SELECT symbol, ts_code, name, area, industry, market, exchange, cnspell, list_date,
                   daily_start_date, daily_end_date, updated_at, extra
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

    @staticmethod
    def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
        return {str(row["name"]) for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}

    @classmethod
    def _ensure_columns(
        cls,
        conn: sqlite3.Connection,
        table: str,
        columns: Dict[str, str],
    ) -> None:
        existing = cls._table_columns(conn, table)
        for name, definition in columns.items():
            if name in existing:
                continue
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")

    @staticmethod
    def _encode_json_text(value: Any) -> Optional[str]:
        if value in (None, "", [], {}, ()):
            return None
        if isinstance(value, str):
            return value
        return json.dumps(value, ensure_ascii=False, sort_keys=True)

    @staticmethod
    def _decode_json_text(value: Any) -> Any:
        if value in (None, "", b""):
            return None
        try:
            return json.loads(str(value))
        except Exception:
            return value


market_data_repository = MarketDataRepository()
