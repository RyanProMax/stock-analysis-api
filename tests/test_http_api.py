"""
HTTP API contract tests for the HTTP-only structured response model.
"""

from fastapi.testclient import TestClient

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
