from __future__ import annotations

from datetime import datetime, timedelta, timezone
import importlib
import sys

import pandas as pd

from src.repositories.market_data_repository import MarketDataRepository
from src.main import sync_market_data
from src.services.daily_data_read_service import DailyDataReadService
from src.services.daily_data_write_service import DailyDataWriteService
from src.services.symbol_catalog_service import SymbolCatalogService

daily_data_write_service_module = importlib.import_module("src.services.daily_data_write_service")


def _daily_df(end_offset_days: int = 0, periods: int = 6) -> pd.DataFrame:
    end_date = datetime.now(timezone.utc).date() + timedelta(days=end_offset_days)
    start_date = end_date - timedelta(days=periods - 1)
    dates = pd.date_range(start=start_date, periods=periods, freq="D")
    rows = []
    price = 10.0
    for idx, date in enumerate(dates):
        close = round(price + 0.2, 2)
        rows.append(
            {
                "date": date.strftime("%Y-%m-%d"),
                "open": round(price, 2),
                "high": round(close + 0.3, 2),
                "low": round(price - 0.2, 2),
                "close": close,
                "volume": 1000 + idx * 100,
                "amount": 10000 + idx * 1000,
                "turnover_rate": round(0.01 + idx * 0.005, 4),
                "vwap": round((price + close) / 2, 2),
            }
        )
        price = close
    return pd.DataFrame(rows)


class FakeSource:
    def __init__(self, name: str, df: pd.DataFrame | None, market: str = "A股"):
        self.SOURCE_NAME = name
        self.priority = 0
        self._df = df
        self._market = market

    def is_available(self, market: str) -> bool:
        return market == self._market

    def get_daily_data(self, symbol: str):
        return self._df.copy() if self._df is not None else None


class FakeCatalog:
    def __init__(self, symbol_row):
        if isinstance(symbol_row, list):
            self.symbol_rows = [dict(row) for row in symbol_row]
            self.symbol_row = dict(symbol_row[0]) if symbol_row else {}
        else:
            self.symbol_rows = [dict(symbol_row)]
            self.symbol_row = dict(symbol_row)

    def refresh_market_snapshot(self, market: str):
        return [dict(row) for row in self.symbol_rows]

    def fetch_live_market_snapshot(self, market: str):
        return [dict(row) for row in self.symbol_rows]

    def resolve_symbol(self, symbol: str, market: str | None = None):
        return dict(self.symbol_row)


class FakeListSource:
    def __init__(self, name: str, rows: list[dict], market: str = "A股"):
        self.SOURCE_NAME = name
        self.priority = 0
        self._rows = rows
        self._market = market

    def is_available(self, market: str) -> bool:
        return market == self._market

    def get_a_stocks(self):
        return list(self._rows)

    def get_us_stocks(self):
        return list(self._rows)


class TestMarketDataRepository:
    def test_initialize_drops_legacy_tables(self, tmp_path):
        db_path = tmp_path / "market.sqlite"
        storage = MarketDataRepository(str(db_path))

        with storage.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS symbols (
                    symbol TEXT PRIMARY KEY,
                    name TEXT
                );
                CREATE TABLE IF NOT EXISTS daily_bars (
                    symbol TEXT NOT NULL,
                    trade_date TEXT NOT NULL,
                    close REAL,
                    PRIMARY KEY (symbol, trade_date)
                );
                CREATE INDEX IF NOT EXISTS idx_daily_bars_symbol_date
                ON daily_bars(symbol, trade_date DESC);
                CREATE TABLE IF NOT EXISTS a_share_symbols (
                    symbol TEXT PRIMARY KEY,
                    name TEXT
                );
                CREATE TABLE IF NOT EXISTS a_share_daily (
                    symbol TEXT NOT NULL,
                    trade_date TEXT NOT NULL,
                    close REAL,
                    PRIMARY KEY (symbol, trade_date)
                );
                CREATE INDEX IF NOT EXISTS idx_a_share_daily_symbol_date
                ON a_share_daily(symbol, trade_date DESC);
                """
            )

        storage.initialize()

        with storage.connect() as conn:
            names = {
                row["name"]
                for row in conn.execute(
                    "select name from sqlite_master where type = 'table'"
                ).fetchall()
            }
            index_names = {
                row["name"]
                for row in conn.execute(
                    "select name from sqlite_master where type = 'index'"
                ).fetchall()
            }

        assert "symbols" not in names
        assert "daily_bars" not in names
        assert "a_share_symbols" not in names
        assert "a_share_daily" not in names
        assert "idx_daily_bars_symbol_date" not in index_names
        assert "idx_a_share_daily_symbol_date" not in index_names

    def test_upsert_and_load_cn_daily_bars_with_extra_json(self, tmp_path):
        storage = MarketDataRepository(str(tmp_path / "market.sqlite"))
        storage.upsert_symbols(
            [
                {
                    "symbol": "300827",
                    "ts_code": "300827.SZ",
                    "name": "上能电气",
                    "market": "创业板",
                    "list_date": "2020-04-10",
                    "fullname": "上能电气股份有限公司",
                }
            ],
            market="cn",
        )

        inserted = storage.upsert_daily_bars("300827", _daily_df(), "CN_Tushare", market="cn")
        loaded = storage.load_daily_bars("300827", market="cn")

        assert inserted == 6
        assert len(loaded) == 6
        assert "ma5" not in loaded.columns
        assert "turnover" in loaded.columns
        assert "turnover_rate" in loaded.columns
        assert "total_mv" in loaded.columns
        assert loaded.iloc[-1]["turnover"] is not None
        assert storage.get_latest_trade_date("300827", market="cn") == str(loaded.iloc[-1]["date"])[:10]

        symbol_row = storage.get_symbol_record("300827", market="cn")
        assert symbol_row["name"] == "上能电气"
        assert symbol_row["daily_start_date"] == str(loaded.iloc[0]["date"])[:10]
        assert symbol_row["daily_end_date"] == str(loaded.iloc[-1]["date"])[:10]
        assert symbol_row["extra"]["fullname"] == "上能电气股份有限公司"

        with storage.connect() as conn:
            row = conn.execute(
                """
                SELECT extra FROM cn_daily
                WHERE symbol = ? ORDER BY trade_date ASC LIMIT 1
                """,
                ("300827",),
            ).fetchone()

        assert row is not None
        assert "vwap" in row["extra"]
        assert "date" not in row["extra"]
        assert "volume" not in row["extra"]

    def test_upsert_and_search_symbols_across_markets(self, tmp_path):
        storage = MarketDataRepository(str(tmp_path / "market.sqlite"))
        storage.upsert_symbols(
            [
                {"symbol": "300827", "ts_code": "300827.SZ", "name": "上能电气", "market": "创业板"},
                {"symbol": "NVDA", "ts_code": "NVDA.US", "name": "NVIDIA", "market": "美股"},
            ]
        )

        all_rows = storage.list_symbols()
        us_rows = storage.search_symbols("NVDA", market="us")
        cn_rows = storage.search_symbols("上能", market="cn")

        assert len(all_rows) == 2
        assert us_rows[0]["symbol"] == "NVDA"
        assert cn_rows[0]["symbol"] == "300827"

    def test_replace_symbols_preserves_daily_coverage_summary(self, tmp_path):
        storage = MarketDataRepository(str(tmp_path / "market.sqlite"))
        storage.upsert_symbols(
            [
                {
                    "symbol": "300827",
                    "ts_code": "300827.SZ",
                    "name": "上能电气",
                    "market": "创业板",
                    "exchange": "SZSE",
                    "list_date": "2020-04-10",
                }
            ],
            market="cn",
        )
        storage.upsert_daily_bars("300827", _daily_df(), "CN_Tushare", market="cn")

        storage.replace_symbols(
            [
                {
                    "symbol": "300827",
                    "ts_code": "300827.SZ",
                    "name": "上能电气",
                    "market": "创业板",
                    "exchange": "SZSE",
                    "list_date": "2020-04-10",
                }
            ],
            market="cn",
        )

        symbol_row = storage.get_symbol_record("300827", market="cn")
        assert symbol_row["daily_start_date"] is not None
        assert symbol_row["daily_end_date"] is not None


class TestDailyDataReadService:
    def test_prefers_fresh_sqlite_data(self, tmp_path, monkeypatch):
        storage = MarketDataRepository(str(tmp_path / "market.sqlite"))
        storage.upsert_symbols(
            [{"symbol": "300827", "ts_code": "300827.SZ", "name": "上能电气", "market": "创业板"}],
            market="cn",
        )
        storage.upsert_daily_bars("300827", _daily_df(), "CN_Tushare", market="cn")

        service = DailyDataReadService(repository=storage)
        daily_data_read_module = importlib.import_module("src.services.daily_data_read_service")
        monkeypatch.setattr(
            daily_data_read_module.data_manager,
            "get_stock_daily",
            lambda symbol: (_ for _ in ()).throw(AssertionError("should not call external provider")),
        )

        df, name, source = service.get_stock_daily("300827")

        assert len(df) == 6
        assert "ma5" in df.columns
        assert name == "上能电气"
        assert source == "CN_SQLiteDailyWarehouse"

    def test_refreshes_stale_sqlite_data_and_persists(self, tmp_path, monkeypatch):
        storage = MarketDataRepository(str(tmp_path / "market.sqlite"))
        stale_df = _daily_df(end_offset_days=-20)
        fresh_df = _daily_df(end_offset_days=0)

        storage.upsert_symbols(
            [{"symbol": "300827", "ts_code": "300827.SZ", "name": "上能电气", "market": "创业板"}],
            market="cn",
        )
        storage.upsert_daily_bars("300827", stale_df, "CN_Old", market="cn")

        class FakeWriteService:
            def sync_symbol_daily(self, symbol: str, market: str, start_date: str | None = None):
                storage.upsert_daily_bars("300827", fresh_df.copy(), "CN_Tushare", market="cn", ts_code="300827.SZ")
                return {"symbol": symbol, "rows": len(fresh_df), "source": "CN_Tushare"}

        service = DailyDataReadService(repository=storage, write_service=FakeWriteService())

        df, name, source = service.get_stock_daily("300827")
        latest = storage.get_latest_trade_date("300827", market="cn")
        loaded = storage.load_daily_bars("300827", market="cn")

        assert len(df) >= 6
        assert "ma5" in df.columns
        assert name == "上能电气"
        assert source == "CN_Tushare"
        assert latest == fresh_df.iloc[-1]["date"]
        assert len(loaded) >= 6


class TestDailyDataWriteService:
    def test_sync_symbol_scope_records_sync_run(self, tmp_path, monkeypatch):
        storage = MarketDataRepository(str(tmp_path / "market.sqlite"))
        empty_source = FakeSource("EmptySource", None)
        good_source = FakeSource("Tushare", _daily_df())
        service = DailyDataWriteService(
            repository=storage,
            symbol_catalog=FakeCatalog(
                {
                    "symbol": "300827",
                    "ts_code": "300827.SZ",
                    "name": "上能电气",
                    "market": "创业板",
                    "exchange": "SZSE",
                    "list_date": "2020-04-10",
                }
            ),
            cn_daily_sources=[empty_source, good_source],
            us_daily_sources=[],
        )

        result = service.sync_market_data(
            market="cn",
            scope="symbol",
            symbol="300827",
            days=30,
        )

        assert result["success_count"] == 1
        assert result["failure_count"] == 0
        assert len(storage.load_daily_bars("300827", market="cn")) == 6

        with storage.connect() as conn:
            row = conn.execute(
                """
                SELECT source, mode, market, scope, status, success_count, failure_count, rows_written
                FROM sync_runs
                ORDER BY id DESC LIMIT 1
                """
            ).fetchone()

        assert row["source"] == "CN_MULTI_SOURCE"
        assert row["mode"] == "cn_symbol_300827_30d"
        assert row["market"] == "cn"
        assert row["scope"] == "symbol"
        assert row["status"] == "completed"
        assert row["success_count"] == 1
        assert row["failure_count"] == 0
        assert row["rows_written"] == 6

    def test_sync_market_data_updates_progress_by_symbol(self, tmp_path):
        storage = MarketDataRepository(str(tmp_path / "market.sqlite"))
        service = DailyDataWriteService(
            repository=storage,
            symbol_catalog=FakeCatalog(
                {
                    "symbol": "300827",
                    "ts_code": "300827.SZ",
                    "name": "上能电气",
                    "market": "创业板",
                    "exchange": "SZSE",
                    "list_date": "2020-04-10",
                }
            ),
            cn_daily_sources=[FakeSource("Tushare", _daily_df())],
            us_daily_sources=[],
        )

        updates = []
        result = service.sync_market_data(
            market="cn",
            scope="symbol",
            symbol="300827",
            days=30,
            progress_callback=updates.append,
        )

        assert result["processed_count"] == 1
        assert result["total_symbols"] == 1
        assert len(updates) == 1
        assert updates[0]["processed_count"] == 1
        assert updates[0]["skipped_count"] == 0
        assert updates[0]["success_count"] == 1
        assert updates[0]["failure_count"] == 0
        assert updates[0]["rows_written"] == 6
        assert updates[0]["item_status"] == "success"

    def test_sync_symbol_scope_accepts_exact_start_date(self, tmp_path):
        storage = MarketDataRepository(str(tmp_path / "market.sqlite"))
        service = DailyDataWriteService(
            repository=storage,
            symbol_catalog=FakeCatalog(
                {
                    "symbol": "300827",
                    "ts_code": "300827.SZ",
                    "name": "上能电气",
                    "market": "创业板",
                    "exchange": "SZSE",
                    "list_date": "2020-04-10",
                }
            ),
            cn_daily_sources=[FakeSource("Tushare", _daily_df())],
            us_daily_sources=[],
        )

        result = service.sync_market_data(
            market="cn",
            scope="symbol",
            symbol="300827",
            start_date="2026-01-01",
        )
        assert result["success_count"] == 1
        assert result["start_date"] == "2026-01-01"

    def test_sync_market_data_skips_when_state_is_current(self, tmp_path):
        storage = MarketDataRepository(str(tmp_path / "market.sqlite"))
        current_df = _daily_df().assign(total_mv=1_000_000.0, circ_mv=800_000.0)
        storage.upsert_symbols(
            [
                {
                    "symbol": "300827",
                    "ts_code": "300827.SZ",
                    "name": "上能电气",
                    "market": "创业板",
                    "exchange": "SZSE",
                    "list_date": "2020-04-10",
                }
            ],
            market="cn",
        )
        storage.upsert_daily_bars("300827", current_df, "CN_Tushare", market="cn")
        service = DailyDataWriteService(
            repository=storage,
            symbol_catalog=FakeCatalog(
                {
                    "symbol": "300827",
                    "ts_code": "300827.SZ",
                    "name": "上能电气",
                    "market": "创业板",
                    "exchange": "SZSE",
                    "list_date": "2020-04-10",
                }
            ),
            cn_daily_sources=[FakeSource("Tushare", current_df)],
            us_daily_sources=[],
        )

        first = service.sync_market_data(
            market="cn",
            scope="symbol",
            symbol="300827",
            start_date=str(current_df.iloc[0]["date"])[:10],
        )
        second = service.sync_market_data(
            market="cn",
            scope="symbol",
            symbol="300827",
            start_date=str(current_df.iloc[0]["date"])[:10],
        )

        assert first["status"] == "skipped"
        assert second["status"] == "skipped"
        assert first["skipped_count"] == 1
        assert second["skipped_count"] == 1

    def test_sync_market_data_backfills_daily_basic_in_batch(self, tmp_path, monkeypatch):
        storage = MarketDataRepository(str(tmp_path / "market.sqlite"))
        base_df = _daily_df()
        symbol_row = {
            "symbol": "300827",
            "ts_code": "300827.SZ",
            "name": "上能电气",
            "market": "创业板",
            "exchange": "SZSE",
            "list_date": "2020-04-10",
        }
        storage.upsert_symbols([symbol_row], market="cn")
        storage.upsert_daily_bars("300827", base_df, "CN_Tushare", market="cn", ts_code="300827.SZ")

        trade_dates = [str(value)[:10] for value in base_df["date"].tolist()]

        def fake_list_cn_open_trade_dates(start_date=None, end_date=None):
            return trade_dates

        def fake_fetch_cn_daily_basic_by_trade_date(trade_date: str):
            return pd.DataFrame(
                [
                    {
                        "ts_code": "300827.SZ",
                        "trade_date": trade_date,
                        "turnover_rate": 1.0,
                        "turnover_rate_f": 1.1,
                        "volume_ratio": 1.2,
                        "pe": 10.0,
                        "pe_ttm": 11.0,
                        "pb": 1.5,
                        "ps": 2.0,
                        "ps_ttm": 2.1,
                        "dv_ratio": 0.4,
                        "dv_ttm": 0.5,
                        "float_share": 100.0,
                        "free_share": 90.0,
                        "total_share": 120.0,
                        "circ_mv": 800.0,
                        "total_mv": 1000.0,
                    }
                ]
            )

        monkeypatch.setattr(
            daily_data_write_service_module.TushareDataSource,
            "list_cn_open_trade_dates",
            fake_list_cn_open_trade_dates,
        )
        monkeypatch.setattr(
            daily_data_write_service_module.TushareDataSource,
            "fetch_cn_daily_basic_by_trade_date",
            fake_fetch_cn_daily_basic_by_trade_date,
        )

        service = DailyDataWriteService(
            repository=storage,
            symbol_catalog=FakeCatalog(symbol_row),
            cn_daily_sources=[FakeSource("Tushare", base_df)],
            us_daily_sources=[],
        )

        result = service.sync_market_data(
            market="cn",
            scope="all",
            start_date=trade_dates[0],
        )

        loaded = storage.load_daily_bars("300827", market="cn")
        assert result["status"] == "completed"
        assert result["success_count"] == 1
        assert result["failure_count"] == 0
        assert result["rows_written"] == len(base_df)
        assert loaded["total_mv"].notna().all()
        assert loaded["circ_mv"].notna().all()
        assert storage.list_symbols_missing_standardized_daily_fields("cn", start_trade_date=trade_dates[0]) == []
        symbol_row_loaded = storage.get_symbol_record("300827", market="cn")
        assert symbol_row_loaded["daily_start_date"] == trade_dates[0]
        assert symbol_row_loaded["daily_end_date"] == trade_dates[-1]

    def test_sync_market_data_skips_stale_symbol_when_suspend_signal_exists(self, tmp_path, monkeypatch):
        storage = MarketDataRepository(str(tmp_path / "market.sqlite"))
        stale_df = _daily_df(end_offset_days=-30).assign(total_mv=1_000_000.0, circ_mv=800_000.0)
        symbol_row = {
            "symbol": "300827",
            "ts_code": "300827.SZ",
            "name": "上能电气",
            "market": "创业板",
            "exchange": "SZSE",
            "list_date": "2020-04-10",
        }
        storage.upsert_symbols([symbol_row], market="cn")
        storage.upsert_daily_bars("300827", stale_df, "CN_Tushare", market="cn", ts_code="300827.SZ")

        service = DailyDataWriteService(
            repository=storage,
            symbol_catalog=FakeCatalog(symbol_row),
            cn_daily_sources=[FakeSource("EmptySource", None)],
            us_daily_sources=[],
        )

        monkeypatch.setattr(
            service,
            "_resolve_trade_window",
            lambda market, start_date, end_date: (start_date, "2026-03-20"),
        )
        monkeypatch.setattr(
            daily_data_write_service_module.TushareDataSource,
            "fetch_cn_suspend_dates",
            lambda symbol, start_date=None, end_date=None: {"2026-03-10"},
        )

        result = service.sync_market_data(
            market="cn",
            scope="symbol",
            symbol="300827",
            start_date=str(stale_df.iloc[0]["date"])[:10],
        )

        latest_run = storage.get_latest_sync_run(
            f"cn_symbol_300827_since_{str(stale_df.iloc[0]['date'])[:10]}"
        )
        assert result["status"] == "skipped"
        assert result["skipped_count"] == 1
        assert latest_run is not None
        assert latest_run["stale_symbol_count"] == 0
        assert latest_run["is_data_current"] is True


class TestSyncCli:
    def test_sync_market_data_cli_defaults_to_30_days(self, monkeypatch):
        captured = {}

        def fake_sync_market_data(**kwargs):
            captured.update(kwargs)
            return {"ok": True}

        monkeypatch.setattr(
            "src.main.daily_data_write_service.sync_market_data",
            fake_sync_market_data,
        )
        monkeypatch.setattr(sys, "argv", ["sync-market-data", "--market", "cn", "--scope", "symbol", "--symbol", "300827"])

        sync_market_data()

        assert captured["market"] == "cn"
        assert captured["scope"] == "symbol"
        assert captured["symbol"] == "300827"
        assert captured["days"] == 30
        assert captured["years"] is None
        assert captured["start_date"] is None
        assert callable(captured["progress_callback"])


class TestSymbolCatalogService:
    def test_prefers_sqlite_symbol_store_for_a_shares(self, tmp_path):
        storage = MarketDataRepository(str(tmp_path / "market.sqlite"))
        service = SymbolCatalogService(repository=storage, cn_sources=[], us_sources=[])
        storage.upsert_symbols(
            [
                {
                    "symbol": "300827",
                    "ts_code": "300827.SZ",
                    "name": "上能电气",
                    "market": "创业板",
                    "list_date": "2020-04-10",
                }
            ],
            market="cn",
        )

        stocks = service.list_symbols("cn")

        assert len(stocks) == 1
        assert stocks[0]["symbol"] == "300827"
        assert stocks[0]["name"] == "上能电气"

    def test_search_cold_starts_and_persists_to_repository(self, tmp_path):
        storage = MarketDataRepository(str(tmp_path / "market.sqlite"))
        rows = [
            {
                "symbol": "NVDA",
                "ts_code": "NVDA.US",
                "name": "NVIDIA",
                "market": "美股",
                "exchange": "NASDAQ",
            }
        ]
        service = SymbolCatalogService(
            repository=storage,
            cn_sources=[],
            us_sources=[FakeListSource("NASDAQ", rows, market="美股")],
        )

        results = service.search_symbols("NVDA", "美股")

        assert len(results) == 1
        assert results[0]["symbol"] == "NVDA"
        assert storage.search_symbols("NVDA", market="us")[0]["name"] == "NVIDIA"
