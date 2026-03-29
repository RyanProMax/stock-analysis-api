"""
Minimal HTTP API regression tests for the remaining public routes.
"""

from fastapi.testclient import TestClient

import src.api.routes.watch as watch_route
import src.main as main_module


def assert_structured_payload(payload: dict):
    assert "entity" in payload
    assert "facts" in payload
    assert "analysis" in payload
    assert "meta" in payload
    assert payload["meta"]["schema_version"] == "2.0.0"
    assert payload["meta"]["interface_type"] in {"fact", "mixed", "model"}


class TestHealthEndpoints:
    def test_health(self, client: TestClient):
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status_code"] == 200
        assert data["data"]["message"] == "ok"
        assert data["data"]["status"] == "healthy"

    def test_health_invokes_preflight_without_blocking_response(self, monkeypatch):
        notified = []
        monkeypatch.setattr(
            main_module.symbol_snapshot_refresh_service,
            "notify_request",
            lambda path: notified.append(path),
        )

        with TestClient(main_module.app) as client:
            response = client.get("/health")

        assert response.status_code == 200
        assert notified == ["/health"]

    def test_ping_not_found(self, client: TestClient):
        response = client.get("/ping")
        assert response.status_code == 404


class TestPublicRouteSurface:
    def test_removed_routes_return_404_and_disappear_from_openapi(self, client: TestClient):
        removed_routes = (
            ("get", "/stock/list"),
            ("post", "/stock/search"),
            ("post", "/analysis/research/snapshot"),
            ("get", "/valuation/dcf"),
            ("get", "/valuation/comps"),
            ("get", "/model/lbo"),
            ("get", "/model/three-statement"),
            ("get", "/model/three-statement/scenarios"),
            ("get", "/analysis/competitive/competitive"),
            ("get", "/analysis/earnings/earnings"),
        )
        for method, path in removed_routes:
            response = getattr(client, method)(path)
            assert response.status_code == 404

        openapi_response = client.get("/openapi.json")
        assert openapi_response.status_code == 200
        paths = openapi_response.json()["paths"]
        assert "/stock/analyze" in paths
        assert "/watch/poll" in paths
        assert "/stock/list" not in paths
        assert "/stock/search" not in paths
        assert "/analysis/research/snapshot" not in paths


class TestWatchEndpoints:
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
