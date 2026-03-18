"""
HTTP API Tests for Stock Analysis API

Tests all HTTP endpoints using real data from yfinance.
Test symbol: TQQQ (ProShares UltraPro QQQ)
"""

import pytest
from fastapi.testclient import TestClient

from tests.conftest import TEST_SYMBOL, TEST_SYMBOL_ETF


class TestHealthEndpoints:
    """Tests for health check endpoints"""

    def test_ping(self, client: TestClient):
        """Health check should return pong"""
        response = client.get("/ping")
        assert response.status_code == 200
        data = response.json()
        assert data["status_code"] == 200
        assert data["data"]["message"] == "pong"
        assert data["data"]["status"] == "healthy"

    def test_root(self, client: TestClient):
        """Root endpoint should return welcome message"""
        response = client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert data["status_code"] == 200
        assert "Welcome" in data["data"]["message"]


class TestStockEndpoints:
    """Tests for /stock/* endpoints"""

    def test_stock_list(self, client: TestClient):
        """Stock list should return available stocks"""
        response = client.get("/stock/list")
        assert response.status_code == 200
        data = response.json()
        assert data["status_code"] == 200
        assert data["err_msg"] is None
        # Should have stocks data
        assert "data" in data
        assert data["data"] is not None

    def test_stock_list_with_market_filter(self, client: TestClient):
        """Stock list with market filter"""
        response = client.get("/stock/list?market=美股")
        assert response.status_code == 200
        data = response.json()
        assert data["status_code"] == 200

    def test_stock_search_tqqq(self, client: TestClient):
        """Search for TQQQ should find the stock"""
        response = client.post(
            "/stock/search", json={"keyword": "TQQQ", "market": "美股"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status_code"] == 200

    def test_stock_analyze_tqqq(self, client: TestClient):
        """Analyze TQQQ should return analysis report"""
        response = client.post(
            "/stock/analyze",
            json={"symbols": [TEST_SYMBOL], "include_qlib_factors": False},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status_code"] == 200
        assert data["err_msg"] is None
        # Should have analysis results
        assert "data" in data
        if data["data"]:
            # Check first result structure
            first_result = data["data"][0] if isinstance(data["data"], list) else data["data"]
            assert "symbol" in first_result or "Symbol" in first_result


class TestValuationEndpoints:
    """Tests for /valuation/* endpoints"""

    def test_dcf_tqqq(self, client: TestClient):
        """DCF valuation for TQQQ"""
        response = client.get(f"/valuation/dcf?symbol={TEST_SYMBOL}")
        assert response.status_code == 200
        data = response.json()
        assert data["status_code"] == 200
        assert data["err_msg"] is None
        # Should have DCF results
        assert "data" in data
        if data["data"]:
            dcf_data = data["data"]
            # Check key DCF fields
            assert "wacc" in dcf_data or "enterprise_value" in dcf_data or "error" in dcf_data

    def test_dcf_with_custom_params(self, client: TestClient):
        """DCF with custom WACC parameters"""
        response = client.get(
            f"/valuation/dcf?symbol={TEST_SYMBOL}"
            "&risk_free_rate=0.04"
            "&equity_risk_premium=0.055"
            "&terminal_growth_rate=0.025"
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status_code"] == 200

    def test_comps_tqqq(self, client: TestClient):
        """Comparable companies analysis for TQQQ"""
        response = client.get(f"/valuation/comps?symbol={TEST_SYMBOL}")
        assert response.status_code == 200
        data = response.json()
        assert data["status_code"] == 200
        assert data["err_msg"] is None
        # Should have comps results
        assert "data" in data
        if data["data"]:
            comps_data = data["data"]
            # Check key comps fields
            assert "target" in comps_data or "comps" in comps_data or "error" in comps_data

    def test_comps_with_sector(self, client: TestClient):
        """Comps with sector filter"""
        response = client.get(f"/valuation/comps?symbol={TEST_SYMBOL}&sector=Technology")
        assert response.status_code == 200
        data = response.json()
        assert data["status_code"] == 200


class TestModelEndpoints:
    """Tests for /model/* endpoints"""

    def test_lbo_tqqq(self, client: TestClient):
        """LBO model analysis for TQQQ"""
        response = client.get(f"/model/lbo?symbol={TEST_SYMBOL}")
        assert response.status_code == 200
        data = response.json()
        assert data["status_code"] == 200
        assert data["err_msg"] is None
        # Should have LBO results
        assert "data" in data

    def test_lbo_with_custom_params(self, client: TestClient):
        """LBO with custom parameters"""
        response = client.get(
            f"/model/lbo?symbol={TEST_SYMBOL}"
            "&holding_period=5"
            "&entry_multiple=10.0"
            "&exit_multiple=12.0"
            "&leverage=0.65"
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status_code"] == 200

    def test_three_statement_tqqq(self, client: TestClient):
        """3-Statement model for TQQQ"""
        response = client.get(f"/model/three-statement?symbol={TEST_SYMBOL}")
        assert response.status_code == 200
        data = response.json()
        assert data["status_code"] == 200
        assert data["err_msg"] is None
        # Should have 3-statement results
        assert "data" in data

    def test_three_statement_with_scenario(self, client: TestClient):
        """3-Statement model with specific scenario"""
        response = client.get(
            f"/model/three-statement?symbol={TEST_SYMBOL}&scenario=bull"
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status_code"] == 200

    def test_three_statement_scenarios_tqqq(self, client: TestClient):
        """3-Statement scenario comparison for TQQQ"""
        response = client.get(f"/model/three-statement/scenarios?symbol={TEST_SYMBOL}")
        assert response.status_code == 200
        data = response.json()
        assert data["status_code"] == 200
        # Should have all 3 scenarios
        assert "data" in data
        if data["data"]:
            scenarios_data = data["data"]
            # Check for bull/base/bear scenarios
            assert "bull" in scenarios_data or "scenarios" in scenarios_data


class TestAnalysisEndpoints:
    """Tests for /analysis/* endpoints"""

    def test_competitive_tqqq(self, client: TestClient):
        """Competitive analysis for TQQQ"""
        response = client.get(f"/analysis/competitive/competitive?symbol={TEST_SYMBOL}")
        assert response.status_code == 200
        data = response.json()
        assert data["status_code"] == 200
        assert data["err_msg"] is None
        # Should have competitive analysis results
        assert "data" in data

    def test_competitive_with_industry(self, client: TestClient):
        """Competitive analysis with industry filter"""
        response = client.get(
            f"/analysis/competitive/competitive?symbol={TEST_SYMBOL}&industry=technology"
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status_code"] == 200

    def test_earnings_tqqq(self, client: TestClient):
        """Earnings analysis for TQQQ"""
        response = client.get(f"/analysis/earnings/earnings?symbol={TEST_SYMBOL}")
        assert response.status_code == 200
        data = response.json()
        assert data["status_code"] == 200
        assert data["err_msg"] is None
        # Should have earnings analysis results
        assert "data" in data

    def test_earnings_with_quarter(self, client: TestClient):
        """Earnings analysis for specific quarter"""
        response = client.get(
            f"/analysis/earnings/earnings?symbol={TEST_SYMBOL}&quarter=Q4&fiscal_year=2024"
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status_code"] == 200


class TestErrorHandling:
    """Tests for error handling"""

    def test_invalid_symbol(self, client: TestClient):
        """Invalid symbol should return error or empty result"""
        response = client.get("/valuation/dcf?symbol=INVALID_SYMBOL_12345")
        # Should not crash - return 200 with error in data
        assert response.status_code == 200
        data = response.json()
        # Either error in err_msg or error in data
        assert data["err_msg"] is not None or (
            data["data"] and "error" in data["data"]
        )

    def test_missing_required_param(self, client: TestClient):
        """Missing required parameter should return 400 or 422"""
        response = client.get("/valuation/dcf")
        # Should return validation error
        assert response.status_code in [400, 422]
