from src.core.watch_polling import WatchPollingService


def _snapshot(
    *,
    symbol: str = "NVDA",
    price: float = 100.0,
    high: float = 101.0,
    low: float = 95.0,
    turnover_rate: float | None = 0.01,
    volume_ratio: float | None = 1.0,
    trend: str = "盘整",
    breakout_state: str = "none",
    earnings_days: int | None = None,
) -> dict:
    return {
        "symbol": symbol,
        "name": symbol,
        "market": "us",
        "computed_at": "2026-03-22T10:00:00+00:00",
        "source_chain": ["test"],
        "status": "ok",
        "partial": False,
        "quote": {
            "price": price,
            "change_pct": 0.01,
            "change_amount": 1.0,
            "open": 99.0,
            "high": high,
            "low": low,
            "pre_close": 99.0,
            "volume": 1000,
            "amount": 100000.0,
            "turnover_rate": turnover_rate,
            "amplitude": 0.03,
            "volume_ratio": volume_ratio,
            "source": "test",
            "as_of": "2026-03-22T10:00:00+00:00",
        },
        "fundamentals": {
            "pe_ratio": 20.0,
            "pb_ratio": 5.0,
            "market_cap": 1000000000.0,
            "dividend_yield": 0.01,
            "revenue_ttm": 500000000.0,
            "source": "test",
            "partial": False,
        },
        "technical": {
            "trend": trend,
            "ma_alignment": "test",
            "breakout_state": breakout_state,
            "volume_ratio": volume_ratio,
            "volume_ratio_state": "normal",
        },
        "earnings_watch": {
            "next_earnings_date": (
                "2026-03-25T00:00:00+00:00" if earnings_days is not None else None
            ),
            "earnings_proximity_days": earnings_days,
            "partial": earnings_days is None,
        },
    }


class TestWatchPollingService:
    def test_poll_deduplicates_and_preserves_order(self, monkeypatch):
        service = WatchPollingService()

        def fake_poll_symbol(symbol: str):
            return {"symbol": symbol}

        monkeypatch.setattr(service, "_poll_symbol", fake_poll_symbol)

        items = service.poll([" nvda ", "AAPL", "NVDA", "600519"])

        assert [item["symbol"] for item in items] == ["NVDA", "AAPL", "600519"]

    def test_initial_poll_marks_delta_initial(self, monkeypatch):
        service = WatchPollingService()
        current = _snapshot()

        monkeypatch.setattr(service, "_build_current_snapshot", lambda symbol: current)
        monkeypatch.setattr(service, "_load_baseline", lambda symbol: None)
        monkeypatch.setattr(service, "_save_baseline", lambda symbol, payload: None)

        result = service._poll_symbol("NVDA")

        assert result["delta"]["status"] == "initial"
        assert result["baseline_at"] is None

    def test_follow_up_poll_emits_expected_alerts(self, monkeypatch):
        service = WatchPollingService()
        previous = _snapshot(
            price=100.0, high=101.0, low=95.0, turnover_rate=0.01, volume_ratio=1.0
        )
        current = _snapshot(
            price=105.0,
            high=105.2,
            low=96.0,
            turnover_rate=0.03,
            volume_ratio=2.1,
            breakout_state="up",
            earnings_days=3,
            trend="多头排列",
        )

        monkeypatch.setattr(service, "_build_current_snapshot", lambda symbol: current)
        monkeypatch.setattr(service, "_load_baseline", lambda symbol: previous)
        monkeypatch.setattr(service, "_save_baseline", lambda symbol, payload: None)

        result = service._poll_symbol("NVDA")

        assert result["delta"]["status"] == "updated"
        assert "price" in result["delta"]["changed_fields"]
        assert "technical_state" in result["delta"]["changed_fields"]

        codes = {item["code"] for item in result["alerts"]}
        assert "price_jump_up" in codes
        assert "turnover_spike" in codes
        assert "volume_spike" in codes
        assert "breakout_up" in codes
        assert "near_day_high" in codes
        assert "earnings_soon" in codes

    def test_build_current_snapshot_marks_us_daily_fallback_partial(self, monkeypatch):
        service = WatchPollingService()

        monkeypatch.setattr(
            "src.core.watch_polling.data_manager.get_stock_info",
            lambda symbol: {"name": "NVIDIA"},
        )
        monkeypatch.setattr(
            "src.core.watch_polling.daily_market_data_service.get_stock_daily",
            lambda symbol: (None, "NVIDIA", "US_yfinance"),
        )
        monkeypatch.setattr(
            "src.core.watch_polling.data_manager.get_realtime_quote",
            lambda symbol: (None, ""),
        )
        monkeypatch.setattr(
            "src.core.watch_polling.data_manager.get_financial_data",
            lambda symbol: ({}, ""),
        )
        monkeypatch.setattr(
            service,
            "_build_quote_payload",
            lambda **kwargs: {
                "price": 100.0,
                "change_pct": 0.01,
                "change_amount": 1.0,
                "open": 99.0,
                "high": 101.0,
                "low": 98.0,
                "pre_close": 99.0,
                "volume": 1000.0,
                "amount": 100000.0,
                "turnover_rate": None,
                "amplitude": 0.03,
                "volume_ratio": 1.1,
                "source": "US_yfinance",
                "as_of": "2026-03-22T10:00:00+00:00",
                "mode": "daily_fallback",
            },
        )
        monkeypatch.setattr(
            service,
            "_build_technical_payload",
            lambda **kwargs: {
                "trend": "盘整",
                "ma_alignment": "数据不足",
                "breakout_state": "none",
                "volume_ratio": 1.1,
                "volume_ratio_state": "normal",
            },
        )
        monkeypatch.setattr(
            service,
            "_build_fundamentals_payload",
            lambda **kwargs: {
                "pe_ratio": 20.0,
                "pb_ratio": 5.0,
                "market_cap": 1000000000.0,
                "dividend_yield": 0.01,
                "revenue_ttm": 500000000.0,
                "source": "yfinance.info",
                "partial": False,
            },
        )
        monkeypatch.setattr(
            service,
            "_build_earnings_watch",
            lambda **kwargs: {
                "next_earnings_date": None,
                "earnings_proximity_days": None,
                "partial": False,
            },
        )

        result = service._build_current_snapshot("NVDA")

        assert result["status"] == "partial"
        assert result["partial"] is True
        assert result["degradation"]["quote_mode"] == "daily_fallback"
        assert result["degradation"]["quote_is_realtime"] is False
        assert result["degradation"]["quote_fallback_used"] is True
        assert any(
            source.get("provider") == "US_yfinance" and source.get("mode") == "daily_fallback"
            for source in result["source_chain"]
            if isinstance(source, dict)
        )

    def test_build_current_snapshot_marks_cn_daily_fallback_partial(self, monkeypatch):
        service = WatchPollingService()

        monkeypatch.setattr(
            "src.core.watch_polling.data_manager.get_stock_info",
            lambda symbol: {"name": "贵州茅台"},
        )
        monkeypatch.setattr(
            "src.core.watch_polling.daily_market_data_service.get_stock_daily",
            lambda symbol: (None, "贵州茅台", "CN_SQLiteDailyWarehouse"),
        )
        monkeypatch.setattr(
            "src.core.watch_polling.data_manager.get_realtime_quote",
            lambda symbol: (None, ""),
        )
        monkeypatch.setattr(
            "src.core.watch_polling.data_manager.get_financial_data",
            lambda symbol: ({}, ""),
        )
        monkeypatch.setattr(
            service,
            "_build_quote_payload",
            lambda **kwargs: {
                "price": 1500.0,
                "change_pct": 0.01,
                "change_amount": 15.0,
                "open": 1490.0,
                "high": 1510.0,
                "low": 1480.0,
                "pre_close": 1485.0,
                "volume": 1000.0,
                "amount": 100000.0,
                "turnover_rate": None,
                "amplitude": 0.03,
                "volume_ratio": 1.1,
                "source": "CN_SQLiteDailyWarehouse",
                "as_of": "2026-03-22T10:00:00+00:00",
                "mode": "daily_fallback",
            },
        )
        monkeypatch.setattr(
            service,
            "_build_technical_payload",
            lambda **kwargs: {
                "trend": "盘整",
                "ma_alignment": "数据不足",
                "breakout_state": "none",
                "volume_ratio": 1.1,
                "volume_ratio_state": "normal",
            },
        )
        monkeypatch.setattr(
            service,
            "_build_fundamentals_payload",
            lambda **kwargs: {
                "pe_ratio": 20.0,
                "pb_ratio": 5.0,
                "market_cap": 1000000000.0,
                "dividend_yield": 0.01,
                "revenue_ttm": 500000000.0,
                "source": "CN_Tushare",
                "partial": False,
            },
        )
        monkeypatch.setattr(
            service,
            "_build_earnings_watch",
            lambda **kwargs: {
                "next_earnings_date": None,
                "earnings_proximity_days": None,
                "partial": False,
            },
        )

        result = service._build_current_snapshot("600519")

        assert result["status"] == "partial"
        assert result["partial"] is True
        assert result["degradation"]["quote_mode"] == "daily_fallback"
        assert result["degradation"]["quote_is_realtime"] is False
        assert result["degradation"]["quote_fallback_used"] is True

    def test_extract_next_earnings_date_prefers_future_calendar_candidates(self):
        future_date = "2030-03-28T00:00:00+00:00"
        payload = {
            "raw_data": {
                "info": {
                    "earningsDate": ["2026-03-18", "2026-03-27"],
                },
                "calendar": {
                    "Earnings Date": [future_date, "2030-03-29T00:00:00+00:00"],
                },
                "earnings_dates": [
                    "2030-03-26T00:00:00+00:00",
                    "2030-04-01T00:00:00+00:00",
                ],
            }
        }

        result = WatchPollingService._extract_next_earnings_date(payload)

        assert result == "2030-03-26T00:00:00+00:00"

    def test_build_earnings_watch_uses_calendar_backfill(self):
        service = WatchPollingService()
        payload = {
            "raw_data": {
                "info": {},
                "calendar": {
                    "Earnings Date": ["2030-03-30T00:00:00+00:00"],
                },
            }
        }

        result = service._build_earnings_watch(payload)

        assert result["next_earnings_date"] == "2030-03-30T00:00:00+00:00"
        assert result["earnings_proximity_days"] is not None
        assert result["partial"] is False
