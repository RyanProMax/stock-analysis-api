"""
HTTP API contract tests for the HTTP-only structured response model.
"""

from fastapi.testclient import TestClient
import src.api.routes.watch as watch_route

from tests.conftest import TEST_SYMBOL


def assert_structured_payload(payload: dict):
    assert "entity" in payload
    assert "facts" in payload
    assert "analysis" in payload
    assert "meta" in payload
    assert payload["meta"]["schema_version"] == "2.0.0"
    assert payload["meta"]["interface_type"] in {"fact", "mixed", "model"}


class TestHealthEndpoints:
    def test_ping(self, client: TestClient):
        response = client.get("/ping")
        assert response.status_code == 200
        data = response.json()
        assert data["status_code"] == 200
        assert data["data"]["message"] == "pong"


class TestStockEndpoints:
    def test_stock_list(self, client: TestClient):
        response = client.get("/stock/list?limit=2")
        assert response.status_code == 200
        data = response.json()
        assert data["status_code"] == 200
        assert "meta" in data["data"]
        assert len(data["data"]["stocks"]) <= 2
        if data["data"]["stocks"]:
            assert "meta" in data["data"]["stocks"][0]

    def test_stock_search(self, client: TestClient):
        response = client.post("/stock/search", json={"keyword": "NVDA", "market": "美股"})
        assert response.status_code == 200
        data = response.json()
        assert data["status_code"] == 200
        assert "meta" in data["data"]

    def test_stock_analyze_contract(self, client: TestClient):
        response = client.post("/stock/analyze", json={"symbols": [TEST_SYMBOL], "include_qlib_factors": False})
        assert response.status_code == 200
        data = response.json()
        assert data["status_code"] == 200
        assert isinstance(data["data"], list)
        if data["data"]:
            payload = data["data"][0]
            assert_structured_payload(payload)
            assert "market_snapshot" in payload["facts"]
            assert "technical_signals" in payload["analysis"]

    def test_watch_poll_contract(self, client: TestClient, monkeypatch):
        monkeypatch.setattr(
            watch_route.watch_polling_service,
            "poll",
            lambda symbols: [
                {
                    "symbol": "NVDA",
                    "name": "NVIDIA",
                    "market": "us",
                    "computed_at": "2026-03-22T10:00:00+00:00",
                    "source_chain": ["yfinance"],
                    "status": "ok",
                    "partial": False,
                    "baseline_at": None,
                    "degradation": {
                        "quote_mode": "realtime",
                        "quote_is_realtime": True,
                        "quote_fallback_used": False,
                        "fundamentals_partial": False,
                        "earnings_partial": False,
                    },
                    "quote": {
                        "price": 100.0,
                        "change_pct": 0.01,
                        "change_amount": 1.0,
                        "open": 99.0,
                        "high": 101.0,
                        "low": 98.0,
                        "pre_close": 99.0,
                        "volume": 1000,
                        "amount": 100000.0,
                        "turnover_rate": 0.02,
                        "amplitude": 0.03,
                        "source": "yfinance",
                        "as_of": "2026-03-22T10:00:00+00:00",
                    },
                    "fundamentals": {
                        "pe_ratio": 20.0,
                        "pb_ratio": 5.0,
                        "market_cap": 1000000000.0,
                        "dividend_yield": 0.01,
                        "revenue_ttm": 500000000.0,
                        "source": "yfinance",
                    },
                    "technical": {
                        "trend": "多头排列",
                        "ma_alignment": "MA5>MA10>MA20",
                        "breakout_state": "none",
                        "volume_ratio": 1.1,
                        "volume_ratio_state": "normal",
                    },
                    "earnings_watch": {
                        "next_earnings_date": None,
                        "earnings_proximity_days": None,
                    },
                    "delta": {"status": "initial", "changed_fields": []},
                    "alerts": [],
                }
            ],
        )

        response = client.post("/watch/poll", json={"symbols": ["NVDA", "AAPL"]})
        assert response.status_code == 200
        data = response.json()
        assert data["status_code"] == 200
        assert isinstance(data["data"], list)
        payload = data["data"][0]
        assert_structured_payload(payload)
        assert payload["entity"]["symbol"] == "NVDA"
        assert "quote" in payload["facts"]
        assert "delta" in payload["analysis"]
        assert payload["meta"]["poll_interval_hint"] == "5-10m"
        assert payload["meta"]["degradation"]["quote_mode"] == "realtime"


class TestValuationEndpoints:
    def test_dcf_contract(self, client: TestClient):
        response = client.get(f"/valuation/dcf?symbol={TEST_SYMBOL}")
        assert response.status_code == 200
        data = response.json()
        assert data["status_code"] == 200
        if data["data"]:
            assert_structured_payload(data["data"])
            assert data["data"]["meta"]["interface_type"] == "model"

    def test_comps_contract(self, client: TestClient):
        response = client.get(f"/valuation/comps?symbol={TEST_SYMBOL}")
        assert response.status_code == 200
        data = response.json()
        assert data["status_code"] == 200
        if data["data"]:
            assert_structured_payload(data["data"])
            assert data["data"]["meta"]["interface_type"] == "mixed"


class TestModelEndpoints:
    def test_lbo_contract(self, client: TestClient):
        response = client.get(f"/model/lbo?symbol={TEST_SYMBOL}")
        assert response.status_code == 200
        data = response.json()
        assert data["status_code"] == 200
        if data["data"]:
            assert_structured_payload(data["data"])
            assert data["data"]["meta"]["interface_type"] == "model"

    def test_three_statement_contract(self, client: TestClient):
        response = client.get(f"/model/three-statement?symbol={TEST_SYMBOL}")
        assert response.status_code == 200
        data = response.json()
        assert data["status_code"] == 200
        if data["data"]:
            assert_structured_payload(data["data"])
            assert data["data"]["meta"]["interface_type"] == "model"


class TestAnalysisEndpoints:
    def test_competitive_contract(self, client: TestClient):
        response = client.get(f"/analysis/competitive/competitive?symbol={TEST_SYMBOL}")
        assert response.status_code == 200
        data = response.json()
        assert data["status_code"] == 200
        if data["data"]:
            assert_structured_payload(data["data"])
            assert data["data"]["meta"]["interface_type"] == "mixed"

    def test_earnings_contract(self, client: TestClient):
        response = client.get(f"/analysis/earnings/earnings?symbol={TEST_SYMBOL}")
        assert response.status_code == 200
        data = response.json()
        assert data["status_code"] == 200
        if data["data"]:
            assert_structured_payload(data["data"])
            assert data["data"]["meta"]["interface_type"] == "mixed"


class TestErrorHandling:
    def test_missing_required_param(self, client: TestClient):
        response = client.get("/valuation/dcf")
        assert response.status_code in [400, 422]
