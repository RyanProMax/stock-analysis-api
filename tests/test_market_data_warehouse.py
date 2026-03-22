from __future__ import annotations

from datetime import datetime, timedelta, timezone
import sys

import pandas as pd

from src.core.market_data_service import DailyMarketDataService
from src.core.market_data_sync import DailyWarehouseSyncService
from src.data_provider.stock_list import StockListService
from src.main import sync_market_data
from src.storage.market_data import MarketDataStorage


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


class TestMarketDataStorage:
    def test_initialize_drops_legacy_symbols_and_daily_bars_tables(self, tmp_path):
        db_path = tmp_path / "market.sqlite"
        storage = MarketDataStorage(str(db_path))

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
        assert "idx_daily_bars_symbol_date" not in index_names

    def test_upsert_and_load_cn_daily_bars_with_extra_json(self, tmp_path):
        storage = MarketDataStorage(str(tmp_path / "market.sqlite"))
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
        assert "ma5" in loaded.columns
        assert "turnover" in loaded.columns
        assert loaded.iloc[-1]["turnover"] is not None
        assert storage.get_latest_trade_date("300827", market="cn") == loaded.iloc[-1]["date"].strftime(
            "%Y-%m-%d"
        )

        symbol_row = storage.get_symbol_record("300827", market="cn")
        assert symbol_row["name"] == "上能电气"
        assert symbol_row["extra"]["fullname"] == "上能电气股份有限公司"

        with storage.connect() as conn:
            row = conn.execute(
                """
                SELECT extra FROM a_share_daily
                WHERE symbol = ? ORDER BY trade_date ASC LIMIT 1
                """,
                ("300827",),
            ).fetchone()

        assert row is not None
        assert "turnover_rate" in row["extra"]
        assert "vwap" in row["extra"]
        assert "date" not in row["extra"]
        assert "volume" not in row["extra"]

    def test_upsert_and_search_symbols_across_markets(self, tmp_path):
        storage = MarketDataStorage(str(tmp_path / "market.sqlite"))
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


class TestDailyMarketDataService:
    def test_prefers_fresh_sqlite_data(self, tmp_path, monkeypatch):
        storage = MarketDataStorage(str(tmp_path / "market.sqlite"))
        storage.upsert_symbols(
            [{"symbol": "300827", "ts_code": "300827.SZ", "name": "上能电气", "market": "创业板"}],
            market="cn",
        )
        storage.upsert_daily_bars("300827", _daily_df(), "CN_Tushare", market="cn")

        service = DailyMarketDataService(warehouse=storage)
        monkeypatch.setattr(
            "src.core.market_data_service.data_manager.get_stock_daily",
            lambda symbol: (_ for _ in ()).throw(AssertionError("should not call external provider")),
        )

        df, name, source = service.get_stock_daily("300827")

        assert len(df) == 6
        assert name == "上能电气"
        assert source == "CN_SQLiteDailyWarehouse"

    def test_refreshes_stale_sqlite_data_and_persists(self, tmp_path, monkeypatch):
        storage = MarketDataStorage(str(tmp_path / "market.sqlite"))
        stale_df = _daily_df(end_offset_days=-20)
        fresh_df = _daily_df(end_offset_days=0)

        storage.upsert_symbols(
            [{"symbol": "300827", "ts_code": "300827.SZ", "name": "上能电气", "market": "创业板"}],
            market="cn",
        )
        storage.upsert_daily_bars("300827", stale_df, "CN_Old", market="cn")

        service = DailyMarketDataService(warehouse=storage)
        monkeypatch.setattr(
            "src.core.market_data_service.data_manager.get_stock_daily",
            lambda symbol: (fresh_df.copy(), "上能电气", "CN_Tushare"),
        )
        monkeypatch.setattr(
            "src.core.market_data_service.StockListService.search_stocks",
            lambda keyword, market=None: [
                {
                    "symbol": "300827",
                    "ts_code": "300827.SZ",
                    "name": "上能电气",
                    "market": "创业板",
                    "exchange": "SZSE",
                    "list_date": "2020-04-10",
                }
            ],
        )

        df, name, source = service.get_stock_daily("300827")
        latest = storage.get_latest_trade_date("300827", market="cn")
        loaded = storage.load_daily_bars("300827", market="cn")

        assert len(df) == 6
        assert name == "上能电气"
        assert source == "CN_Tushare"
        assert latest == fresh_df.iloc[-1]["date"]
        assert len(loaded) >= 6


class TestDailyWarehouseSyncService:
    def test_sync_symbol_scope_records_sync_run(self, tmp_path, monkeypatch):
        storage = MarketDataStorage(str(tmp_path / "market.sqlite"))
        empty_source = FakeSource("EmptySource", None)
        good_source = FakeSource("Tushare", _daily_df())
        service = DailyWarehouseSyncService(
            warehouse=storage,
            cn_daily_sources=[empty_source, good_source],
            us_daily_sources=[],
        )

        monkeypatch.setattr(
            "src.core.market_data_sync.StockListService.search_stocks",
            lambda keyword, market=None: [
                {
                    "symbol": "300827",
                    "ts_code": "300827.SZ",
                    "name": "上能电气",
                    "market": "创业板",
                    "exchange": "SZSE",
                    "list_date": "2020-04-10",
                }
            ],
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
                SELECT source, mode, status, success_count, failure_count
                FROM sync_runs
                ORDER BY id DESC LIMIT 1
                """
            ).fetchone()

        assert row["source"] == "CN_MULTI_SOURCE"
        assert row["mode"] == "cn_symbol_300827_30d"
        assert row["status"] == "completed"
        assert row["success_count"] == 1
        assert row["failure_count"] == 0

    def test_sync_symbol_scope_fills_metadata_from_tushare_when_search_misses(self, tmp_path, monkeypatch):
        storage = MarketDataStorage(str(tmp_path / "market.sqlite"))
        service = DailyWarehouseSyncService(
            warehouse=storage,
            cn_daily_sources=[FakeSource("Tushare", _daily_df())],
            us_daily_sources=[],
        )

        monkeypatch.setattr(
            "src.core.market_data_sync.StockListService.search_stocks",
            lambda keyword, market=None: [],
        )
        monkeypatch.setattr(
            "src.core.market_data_sync.TushareDataSource.fetch_cn_stock_basic",
            lambda symbol: {
                "symbol": "300827",
                "ts_code": "300827.SZ",
                "name": "上能电气",
                "market": "创业板",
                "exchange": "SZSE",
                "list_date": "2020-04-10",
            },
        )

        result = service.sync_market_data(market="cn", scope="symbol", symbol="300827", days=30)
        symbol_row = storage.get_symbol_record("300827", market="cn")

        assert result["success_count"] == 1
        assert symbol_row["name"] == "上能电气"

    def test_sync_symbol_scope_enriches_degraded_cached_metadata(self, tmp_path, monkeypatch):
        storage = MarketDataStorage(str(tmp_path / "market.sqlite"))
        storage.upsert_symbols(
            [{"symbol": "300827", "ts_code": "300827.SZ", "name": "300827", "market": "A股"}],
            market="cn",
        )
        service = DailyWarehouseSyncService(
            warehouse=storage,
            cn_daily_sources=[FakeSource("Tushare", _daily_df())],
            us_daily_sources=[],
        )

        monkeypatch.setattr(
            "src.core.market_data_sync.StockListService.search_stocks",
            lambda keyword, market=None: [
                {"symbol": "300827", "ts_code": "300827.SZ", "name": "300827", "market": "A股"}
            ],
        )
        monkeypatch.setattr(
            "src.core.market_data_sync.TushareDataSource.fetch_cn_stock_basic",
            lambda symbol: {
                "symbol": "300827",
                "ts_code": "300827.SZ",
                "name": "上能电气",
                "market": "创业板",
                "exchange": "SZSE",
            },
        )

        result = service.sync_market_data(market="cn", scope="symbol", symbol="300827", days=30)
        symbol_row = storage.get_symbol_record("300827", market="cn")

        assert result["success_count"] == 1
        assert symbol_row["name"] == "上能电气"


class TestSyncCli:
    def test_sync_market_data_cli_defaults_to_30_days(self, monkeypatch):
        captured = {}

        def fake_sync_market_data(**kwargs):
            captured.update(kwargs)
            return {"ok": True}

        monkeypatch.setattr(
            "src.main.daily_warehouse_sync_service.sync_market_data",
            fake_sync_market_data,
        )
        monkeypatch.setattr(sys, "argv", ["sync-market-data", "--market", "cn", "--scope", "symbol", "--symbol", "300827"])

        sync_market_data()

        assert captured == {
            "market": "cn",
            "scope": "symbol",
            "symbol": "300827",
            "days": 30,
            "years": None,
        }


class TestStockListServiceWithSQLite:
    def test_prefers_sqlite_symbol_store_for_a_shares(self, tmp_path, monkeypatch):
        storage = MarketDataStorage(str(tmp_path / "market.sqlite"))
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

        monkeypatch.setattr("src.data_provider.stock_list.market_data_storage", storage)
        monkeypatch.setattr(
            "src.data_provider.stock_list.StockListService._a_stock_sources",
            [FakeSource("ShouldNotFetch", _daily_df())],
        )

        stocks = StockListService.get_a_stock_list()

        assert len(stocks) == 1
        assert stocks[0]["symbol"] == "300827"
        assert stocks[0]["name"] == "上能电气"

    def test_search_cold_starts_and_persists_to_sqlite(self, tmp_path, monkeypatch):
        storage = MarketDataStorage(str(tmp_path / "market.sqlite"))
        rows = [
            {
                "symbol": "NVDA",
                "ts_code": "NVDA.US",
                "name": "NVIDIA",
                "market": "美股",
                "exchange": "NASDAQ",
            }
        ]

        monkeypatch.setattr("src.data_provider.stock_list.market_data_storage", storage)

        def fake_get_us_stock_list(use_tushare: bool = True):
            storage.upsert_symbols(rows, market="us")
            return rows

        monkeypatch.setattr(StockListService, "get_us_stock_list", fake_get_us_stock_list)

        results = StockListService.search_stocks("NVDA", "美股")

        assert len(results) == 1
        assert results[0]["symbol"] == "NVDA"
        assert storage.search_symbols("NVDA", market="us")[0]["name"] == "NVIDIA"
