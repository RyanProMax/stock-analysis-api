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
            "next_earnings_date": "2026-03-25T00:00:00+00:00" if earnings_days is not None else None,
            "earnings_proximity_days": earnings_days,
            "partial": earnings_days is None,
        },
    }


class TestWatchPollingService:
    def test_poll_deduplicates_and_preserves_order(self, monkeypatch):
        service = WatchPollingService()

        def fake_poll_symbol(symbol: str, refresh: bool = False):
            return {"symbol": symbol, "refresh": refresh}

        monkeypatch.setattr(service, "_poll_symbol", fake_poll_symbol)

        items = service.poll([" nvda ", "AAPL", "NVDA", "600519"], refresh=True)

        assert [item["symbol"] for item in items] == ["NVDA", "AAPL", "600519"]
        assert all(item["refresh"] is True for item in items)

    def test_initial_poll_marks_delta_initial(self, monkeypatch):
        service = WatchPollingService()
        current = _snapshot()

        monkeypatch.setattr(service, "_build_current_snapshot", lambda symbol, refresh=False: current)
        monkeypatch.setattr(service, "_load_baseline", lambda symbol: None)
        monkeypatch.setattr(service, "_save_baseline", lambda symbol, payload: None)

        result = service._poll_symbol("NVDA")

        assert result["delta"]["status"] == "initial"
        assert result["baseline_at"] is None

    def test_follow_up_poll_emits_expected_alerts(self, monkeypatch):
        service = WatchPollingService()
        previous = _snapshot(price=100.0, high=101.0, low=95.0, turnover_rate=0.01, volume_ratio=1.0)
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

        monkeypatch.setattr(service, "_build_current_snapshot", lambda symbol, refresh=False: current)
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
