from __future__ import annotations

import pandas as pd

from src.core.market_data_service import DailyMarketDataService
from src.core.market_data_sync import DailyWarehouseSyncService
from src.data_provider.stock_list import StockListService
from src.storage.market_data import MarketDataStorage


def _sample_daily_df() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"date": "2026-03-17", "open": 10.0, "high": 10.5, "low": 9.8, "close": 10.2, "volume": 1000, "amount": 10000, "turnover": 0.01},
            {"date": "2026-03-18", "open": 10.2, "high": 10.6, "low": 10.0, "close": 10.4, "volume": 1100, "amount": 11000, "turnover": 0.02},
            {"date": "2026-03-19", "open": 10.4, "high": 10.7, "low": 10.2, "close": 10.5, "volume": 1200, "amount": 12000, "turnover": 0.02},
            {"date": "2026-03-20", "open": 10.5, "high": 10.9, "low": 10.3, "close": 10.7, "volume": 1300, "amount": 13000, "turnover": 0.03},
            {"date": "2026-03-21", "open": 10.7, "high": 11.0, "low": 10.5, "close": 10.9, "volume": 1400, "amount": 14000, "turnover": 0.03},
            {"date": "2026-03-22", "open": 10.9, "high": 11.1, "low": 10.7, "close": 11.0, "volume": 1500, "amount": 15000, "turnover": 0.04},
        ]
    )


class FakeSource:
    def __init__(self, name: str, df: pd.DataFrame | None):
        self.SOURCE_NAME = name
        self.priority = 0
        self._df = df

    def is_available(self, market: str) -> bool:
        return market == "A股"

    def get_daily_data(self, symbol: str):
        return self._df.copy() if self._df is not None else None


class TestMarketDataStorage:
    def test_upsert_and_load_daily_bars(self, tmp_path):
        storage = MarketDataStorage(str(tmp_path / "market.sqlite"))
        storage.upsert_symbols(
            [
                {
                    "symbol": "600519",
                    "ts_code": "600519.SH",
                    "name": "贵州茅台",
                    "market": "cn",
                    "list_date": "2001-08-27",
                }
            ]
        )

        inserted = storage.upsert_daily_bars("600519", _sample_daily_df(), "CN_Tushare")
        loaded = storage.load_daily_bars("600519")

        assert inserted == 6
        assert len(loaded) == 6
        assert loaded.iloc[-1]["close"] == 11.0
        assert "ma5" in loaded.columns
        assert storage.get_latest_trade_date("600519") == "2026-03-22"
        assert storage.get_symbol_record("600519")["name"] == "贵州茅台"


class TestDailyMarketDataService:
    def test_prefers_sqlite_for_cn_symbols(self, tmp_path, monkeypatch):
        storage = MarketDataStorage(str(tmp_path / "market.sqlite"))
        storage.upsert_symbols(
            [
                {
                    "symbol": "600519",
                    "ts_code": "600519.SH",
                    "name": "贵州茅台",
                    "market": "cn",
                    "list_date": "2001-08-27",
                }
            ]
        )
        storage.upsert_daily_bars("600519", _sample_daily_df(), "CN_Tushare")

        service = DailyMarketDataService(warehouse=storage)
        monkeypatch.setattr(
            "src.core.market_data_service.data_manager.get_stock_daily",
            lambda symbol: (_ for _ in ()).throw(AssertionError("should not call external provider")),
        )

        df, name, source = service.get_stock_daily("600519")

        assert len(df) == 6
        assert name == "贵州茅台"
        assert source == "CN_SQLiteDailyWarehouse"

    def test_persists_external_cn_fetch_to_sqlite(self, tmp_path, monkeypatch):
        storage = MarketDataStorage(str(tmp_path / "market.sqlite"))
        service = DailyMarketDataService(warehouse=storage)

        monkeypatch.setattr(
            "src.core.market_data_service.data_manager.get_stock_daily",
            lambda symbol: (_sample_daily_df(), "贵州茅台", "CN_Tushare"),
        )
        monkeypatch.setattr(
            "src.core.market_data_service.StockListService.search_stocks",
            lambda keyword, market=None: [
                {
                    "symbol": "600519",
                    "ts_code": "600519.SH",
                    "name": "贵州茅台",
                    "market": "主板",
                    "list_date": "2001-08-27",
                }
            ],
        )

        df, name, source = service.get_stock_daily("600519")
        loaded = storage.load_daily_bars("600519")

        assert len(df) == 6
        assert name == "贵州茅台"
        assert source == "CN_Tushare"
        assert len(loaded) == 6
        assert storage.get_symbol_record("600519")["ts_code"] == "600519.SH"


class TestDailyWarehouseSyncService:
    def test_sync_uses_priority_source_and_records_sync_run(self, tmp_path, monkeypatch):
        storage = MarketDataStorage(str(tmp_path / "market.sqlite"))
        empty_source = FakeSource("EmptySource", None)
        good_source = FakeSource("Tushare", _sample_daily_df())
        service = DailyWarehouseSyncService(
            warehouse=storage,
            cn_sources=[empty_source, good_source],
        )

        monkeypatch.setattr(
            "src.core.market_data_sync.StockListService.get_a_stock_list",
            lambda: [
                {
                    "symbol": "600519",
                    "ts_code": "600519.SH",
                    "name": "贵州茅台",
                    "market": "主板",
                    "list_date": "2001-08-27",
                }
            ],
        )

        result = service.backfill_a_share_history(years=5)

        assert result["success_count"] == 1
        assert result["failure_count"] == 0
        assert len(storage.load_daily_bars("600519")) == 6

        with storage.connect() as conn:
            row = conn.execute(
                "SELECT source, mode, status, success_count, failure_count FROM sync_runs ORDER BY id DESC LIMIT 1"
            ).fetchone()

        assert row["source"] == "A_SHARE_MULTI_SOURCE"
        assert row["mode"] == "backfill_5y"
        assert row["status"] == "completed"
        assert row["success_count"] == 1
        assert row["failure_count"] == 0


class TestStockListServiceWithSQLite:
    def test_prefers_sqlite_symbol_store_for_a_shares(self, tmp_path, monkeypatch):
        storage = MarketDataStorage(str(tmp_path / "market.sqlite"))
        storage.upsert_symbols(
            [
                {
                    "symbol": "600519",
                    "ts_code": "600519.SH",
                    "name": "贵州茅台",
                    "market": "主板",
                    "list_date": "2001-08-27",
                }
            ]
        )

        monkeypatch.setattr("src.data_provider.stock_list.market_data_storage", storage)
        monkeypatch.setattr(
            "src.data_provider.stock_list.StockListService._a_stock_sources",
            [FakeSource("ShouldNotFetch", _sample_daily_df())],
        )

        stocks = StockListService.get_a_stock_list()

        assert len(stocks) == 1
        assert stocks[0]["symbol"] == "600519"
        assert stocks[0]["name"] == "贵州茅台"

    def test_search_cold_starts_and_persists_to_sqlite(self, tmp_path, monkeypatch):
        storage = MarketDataStorage(str(tmp_path / "market.sqlite"))
        rows = [
            {
                "symbol": "NVDA",
                "ts_code": "NVDA",
                "name": "NVIDIA",
                "market": "美股",
                "list_date": None,
            }
        ]

        monkeypatch.setattr("src.data_provider.stock_list.market_data_storage", storage)

        def fake_get_us_stock_list(use_tushare: bool = True):
            storage.upsert_symbols(rows)
            return rows

        monkeypatch.setattr(StockListService, "get_us_stock_list", fake_get_us_stock_list)

        results = StockListService.search_stocks("NVDA", "美股")

        assert len(results) == 1
        assert results[0]["symbol"] == "NVDA"
        assert storage.search_symbols("NVDA", market="us")[0]["name"] == "NVIDIA"
