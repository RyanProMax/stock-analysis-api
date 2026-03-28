"""
HTTP API contract tests for the HTTP-only structured response model.
"""

from fastapi.testclient import TestClient

import src.api.routes.research as research_route
import src.api.routes.stock as stock_route
import src.api.routes.watch as watch_route
import src.main as main_module

from tests.conftest import TEST_SYMBOL


def assert_structured_payload(payload: dict):
    assert "entity" in payload
    assert "facts" in payload
    assert "analysis" in payload
    assert "meta" in payload
    assert payload["meta"]["schema_version"] == "2.0.0"
    assert payload["meta"]["interface_type"] in {"fact", "mixed", "model"}


def assert_no_subjective_keys(value):
    forbidden = {
        "recommendation",
        "confidence",
        "price_target",
        "moat_assessment",
        "thesis",
        "conviction",
        "positioning",
    }
    if isinstance(value, dict):
        assert forbidden.isdisjoint(value.keys())
        for item in value.values():
            assert_no_subjective_keys(item)
    elif isinstance(value, list):
        for item in value:
            assert_no_subjective_keys(item)


def stub_structured_payload(interface_type: str = "mixed") -> dict:
    return {
        "entity": {"symbol": TEST_SYMBOL, "name": "NVIDIA"},
        "facts": {"market_snapshot": {}, "quote": {}},
        "analysis": {"technical_signals": {}, "delta": {}},
        "meta": {
            "schema_version": "2.0.0",
            "as_of": None,
            "sources": ["test"],
            "data_completeness": "ok",
            "limitations": [],
            "interface_type": interface_type,
        },
    }


class StubResult:
    def __init__(self, payload: dict | None = None, error: str | None = None):
        self._payload = payload or {}
        self.error = error

    def to_dict(self):
        return self._payload


def stub_snapshot_payload() -> dict:
    return {
        "status": "ok",
        "computed_at": "2026-03-28T10:00:00+00:00",
        "source": "research_snapshot_dispatcher",
        "market": "us",
        "strategy": "fsp_objective_research_snapshot_v1",
        "request": {
            "market": "us",
            "symbols": [TEST_SYMBOL],
            "start_date": "20260301",
            "end_date": "20260328",
            "modules": ["earnings", "dcf"],
            "module_options": {"dcf": {"risk_free_rate": 0.04}},
        },
        "items": [
            {
                "requested_symbol": TEST_SYMBOL,
                "status": "ok",
                "error": None,
                "info": {
                    "common": {
                        "ts_code": None,
                        "name": "NVIDIA",
                        "list_date": None,
                        "delist_date": None,
                    },
                    "cn_specific": {
                        "symbol": None,
                        "exchange": None,
                        "list_status": None,
                        "area": None,
                        "industry": None,
                        "market": None,
                    },
                    "us_specific": {
                        "ts_code": TEST_SYMBOL,
                        "name": "NVIDIA",
                        "enname": None,
                        "classify": "stock",
                        "list_date": None,
                        "delist_date": None,
                    },
                },
                "earnings": {
                    **stub_structured_payload("mixed"),
                    "module_status": "ok",
                    "module_error": None,
                    "attempted_sources": ["yfinance"],
                },
                "dcf": {
                    **stub_structured_payload("model"),
                    "module_status": "ok",
                    "module_error": None,
                    "attempted_sources": ["yfinance"],
                },
            }
        ],
    }


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

    def test_stock_list_a_share_can_include_etf(self, client: TestClient, monkeypatch):
        monkeypatch.setattr(
            stock_route.stock_service,
            "get_stock_list",
            lambda market=None: [
                {
                    "symbol": "510300",
                    "ts_code": "510300.SH",
                    "name": "沪深300ETF",
                    "market": "ETF",
                    "list_date": "2012-05-28",
                }
            ],
        )

        response = client.get("/stock/list?market=A股")

        assert response.status_code == 200
        data = response.json()
        assert data["status_code"] == 200
        assert data["data"]["stocks"][0]["symbol"] == "510300"
        assert data["data"]["stocks"][0]["market"] == "ETF"

    def test_stock_search(self, client: TestClient):
        response = client.post("/stock/search", json={"keyword": "NVDA", "market": "美股"})
        assert response.status_code == 200
        data = response.json()
        assert data["status_code"] == 200
        assert "meta" in data["data"]

    def test_stock_search_a_share_can_return_etf(self, client: TestClient, monkeypatch):
        monkeypatch.setattr(
            stock_route.stock_service,
            "search_stocks",
            lambda keyword, market=None: [
                {
                    "symbol": "510300",
                    "ts_code": "510300.SH",
                    "name": "沪深300ETF",
                    "market": "ETF",
                    "list_date": "2012-05-28",
                }
            ],
        )

        response = client.post("/stock/search", json={"keyword": "300ETF", "market": "A股"})

        assert response.status_code == 200
        data = response.json()
        assert data["status_code"] == 200
        assert data["data"]["stocks"][0]["symbol"] == "510300"
        assert data["data"]["stocks"][0]["market"] == "ETF"

    def test_stock_analyze_contract(self, client: TestClient, monkeypatch):
        monkeypatch.setattr(
            stock_route.stock_service,
            "batch_analyze",
            lambda symbols, include_qlib_factors=False: [StubResult()],
        )
        monkeypatch.setattr(
            stock_route,
            "stock_analysis_contract",
            lambda payload: stub_structured_payload("mixed"),
        )

        response = client.post(
            "/stock/analyze", json={"symbols": [TEST_SYMBOL], "include_qlib_factors": False}
        )
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


class TestResearchSnapshotEndpoints:
    def test_research_snapshot_contract(self, client: TestClient, monkeypatch):
        monkeypatch.setattr(
            research_route.research_snapshot_service,
            "poll_snapshot",
            lambda **kwargs: stub_snapshot_payload(),
        )

        response = client.post(
            "/analysis/research/snapshot",
            json={
                "market": "us",
                "symbols": [TEST_SYMBOL],
                "start_date": "20260301",
                "end_date": "20260328",
                "modules": ["earnings", "dcf"],
                "module_options": {"dcf": {"risk_free_rate": 0.04}},
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status_code"] == 200
        payload = data["data"]
        assert payload["source"] == "research_snapshot_dispatcher"
        assert payload["strategy"] == "fsp_objective_research_snapshot_v1"
        assert payload["request"]["modules"] == ["earnings", "dcf"]
        item = payload["items"][0]
        assert item["requested_symbol"] == TEST_SYMBOL
        assert item["earnings"]["module_status"] == "ok"
        assert item["dcf"]["module_status"] == "ok"
        assert_structured_payload(item["earnings"])
        assert_structured_payload(item["dcf"])
        assert_no_subjective_keys(payload)

    def test_research_snapshot_passes_modules_and_options(self, client: TestClient, monkeypatch):
        captured = {}

        def fake_poll_snapshot(**kwargs):
            captured.update(kwargs)
            return stub_snapshot_payload()

        monkeypatch.setattr(
            research_route.research_snapshot_service,
            "poll_snapshot",
            fake_poll_snapshot,
        )

        response = client.post(
            "/analysis/research/snapshot",
            json={
                "market": "cn",
                "symbols": ["600519", "600519"],
                "modules": ["screen"],
                "module_options": {"screen": {"filters": {"pe_ratio": {"lte": 20}}}},
            },
        )

        assert response.status_code == 200
        assert captured["market"] == "cn"
        assert captured["symbols"] == ["600519", "600519"]
        assert captured["modules"] == ["screen"]
        assert captured["module_options"] == {"screen": {"filters": {"pe_ratio": {"lte": 20}}}}

    def test_old_routes_removed_from_router_and_openapi(self, client: TestClient):
        for path in (
            f"/valuation/dcf?symbol={TEST_SYMBOL}",
            f"/valuation/comps?symbol={TEST_SYMBOL}",
            f"/model/lbo?symbol={TEST_SYMBOL}",
            f"/model/three-statement?symbol={TEST_SYMBOL}",
            f"/model/three-statement/scenarios?symbol={TEST_SYMBOL}",
            f"/analysis/competitive/competitive?symbol={TEST_SYMBOL}",
            f"/analysis/earnings/earnings?symbol={TEST_SYMBOL}",
        ):
            response = client.get(path)
            assert response.status_code == 404

        openapi_response = client.get("/openapi.json")
        assert openapi_response.status_code == 200
        paths = openapi_response.json()["paths"]
        assert "/analysis/research/snapshot" in paths
        assert "/valuation/dcf" not in paths
        assert "/valuation/comps" not in paths
        assert "/model/lbo" not in paths
        assert "/model/three-statement" not in paths
        assert "/model/three-statement/scenarios" not in paths
        assert "/analysis/competitive/competitive" not in paths
        assert "/analysis/earnings/earnings" not in paths

    def test_research_snapshot_validation_error(self, client: TestClient):
        response = client.post("/analysis/research/snapshot", json={})
        assert response.status_code == 400
