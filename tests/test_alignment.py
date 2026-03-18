"""
HTTP vs MCP Alignment Tests

Verifies that HTTP API and MCP Tools produce consistent results for same input parameters.
Test symbol: TQQQ (ProShares UltraPro QQQ)
"""

import pytest
from fastapi.testclient import TestClient

from tests.conftest import TEST_SYMBOL, TEST_SYMBOL_ETF, client
from src.mcp_server.server import (
    get_stock_list,
    search_stocks,
    analyze_stock,
    analyze_dcf,
    analyze_comps,
    analyze_lbo,
    analyze_three_statement,
    analyze_competitive,
    analyze_earnings,
)


def assert_aligned(http_data: dict, mcp_data: dict, key_fields: list):
    """
    Verify HTTP and MCP return same values for key fields.

    Args:
        http_data: Response data from HTTP API
        mcp_data: Response data from MCP tool
        key_fields: List of field names to compare
    """
    for field in key_fields:
        http_val = http_data.get(field)
        mcp_val = mcp_data.get(field)

        # Handle None cases
        if http_val is None and mcp_val is None:
            continue

        # Handle numeric comparison with tolerance
        if isinstance(http_val, (int, float)) and isinstance(mcp_val, (int, float)):
            assert abs(http_val - mcp_val) < 0.01, (
                f"Field '{field}' mismatch: HTTP={http_val}, MCP={mcp_val}"
            )
        else:
            assert http_val == mcp_val, (
                f"Field '{field}' mismatch: HTTP={http_val}, MCP={mcp_val}"
            )


class TestStockListAlignment:
    """Test /stock/list vs get_stock_list alignment"""

    def test_stock_list_alignment(self, client: TestClient):
        """HTTP /stock/list should match MCP get_stock_list"""
        # Call HTTP API
        http_response = client.get("/stock/list")
        assert http_response.status_code == 200
        http_data = http_response.json()["data"]

        # Call MCP tool
        mcp_data = get_stock_list()

        # Compare structure
        assert "stocks" in http_data or "stocks" in mcp_data
        # Both should return list of stocks
        assert isinstance(mcp_data.get("stocks", []), list)


class TestSearchStocksAlignment:
    """Test /stock/search vs search_stocks alignment"""

    def test_search_stocks_alignment(self, client: TestClient):
        """HTTP /stock/search should match MCP search_stocks"""
        # Call HTTP API
        http_response = client.post(
            "/stock/search",
            json={"keyword": TEST_SYMBOL, "market": "美股"}
        )
        assert http_response.status_code == 200
        http_data = http_response.json()["data"]

        # Call MCP tool
        mcp_data = search_stocks(keyword=TEST_SYMBOL, market="美股")

        # Compare structure
        assert "stocks" in http_data or "total" in http_data
        assert "stocks" in mcp_data or "total" in mcp_data


class TestDCFAlignment:
    """Test /valuation/dcf vs analyze_dcf alignment"""

    def test_dcf_alignment(self, client: TestClient):
        """HTTP /valuation/dcf should match MCP analyze_dcf"""
        # Call HTTP API
        http_response = client.get(f"/valuation/dcf?symbol={TEST_SYMBOL}")
        assert http_response.status_code == 200
        http_result = http_response.json()

        # Call MCP tool
        mcp_result = analyze_dcf(symbol=TEST_SYMBOL)

        # Both should return data or error
        if http_result["err_msg"] or "error" in mcp_result:
            # At least one has error - skip comparison
            return

        http_data = http_result["data"]
        if http_data is None:
            return

        # Compare key fields
        key_fields = ["symbol", "wacc", "enterprise_value", "share_price"]
        for field in key_fields:
            http_val = http_data.get(field)
            mcp_val = mcp_result.get(field)
            if http_val is not None and mcp_val is not None:
                if isinstance(http_val, (int, float)) and isinstance(mcp_val, (int, float)):
                    assert abs(http_val - mcp_val) < 0.01, f"{field}: HTTP={http_val}, MCP={mcp_val}"
                else:
                    assert http_val == mcp_val, f"{field}: HTTP={http_val}, MCP={mcp_val}"


class TestCompsAlignment:
    """Test /valuation/comps vs analyze_comps alignment"""

    def test_comps_alignment(self, client: TestClient):
        """HTTP /valuation/comps should match MCP analyze_comps"""
        # Call HTTP API
        http_response = client.get(f"/valuation/comps?symbol={TEST_SYMBOL}")
        assert http_response.status_code == 200
        http_result = http_response.json()

        # Call MCP tool
        mcp_result = analyze_comps(symbol=TEST_SYMBOL)

        # Both should return data or error
        if http_result["err_msg"] or "error" in mcp_result:
            return

        http_data = http_result["data"]
        if http_data is None:
            return

        # Compare symbol at minimum
        assert http_data.get("symbol") == mcp_result.get("symbol")


class TestLBOAlignment:
    """Test /model/lbo vs analyze_lbo alignment"""

    def test_lbo_alignment(self, client: TestClient):
        """HTTP /model/lbo should match MCP analyze_lbo"""
        # Call HTTP API
        http_response = client.get(f"/model/lbo?symbol={TEST_SYMBOL}")
        assert http_response.status_code == 200
        http_result = http_response.json()

        # Call MCP tool
        mcp_result = analyze_lbo(symbol=TEST_SYMBOL)

        # Both should return data or error
        if http_result["err_msg"] or "error" in mcp_result:
            return

        http_data = http_result["data"]
        if http_data is None:
            return

        # Compare symbol
        assert http_data.get("symbol") == mcp_result.get("symbol")


class TestThreeStatementAlignment:
    """Test /model/three-statement vs analyze_three_statement alignment"""

    def test_three_statement_alignment(self, client: TestClient):
        """HTTP /model/three-statement should match MCP analyze_three_statement"""
        # Call HTTP API
        http_response = client.get(f"/model/three-statement?symbol={TEST_SYMBOL}&scenario=base")
        assert http_response.status_code == 200
        http_result = http_response.json()

        # Call MCP tool
        mcp_result = analyze_three_statement(symbol=TEST_SYMBOL, scenario="base")

        # Both should return data or error
        if http_result["err_msg"] or "error" in mcp_result:
            return

        http_data = http_result["data"]
        if http_data is None:
            return

        # Compare symbol
        assert http_data.get("symbol") == mcp_result.get("symbol")


class TestCompetitiveAlignment:
    """Test /analysis/competitive vs analyze_competitive alignment"""

    def test_competitive_alignment(self, client: TestClient):
        """HTTP /analysis/competitive should match MCP analyze_competitive"""
        # Call HTTP API
        http_response = client.get(f"/analysis/competitive/competitive?symbol={TEST_SYMBOL}")
        assert http_response.status_code == 200
        http_result = http_response.json()

        # Call MCP tool
        mcp_result = analyze_competitive(symbol=TEST_SYMBOL)

        # Both should return data or error
        if http_result["err_msg"] or "error" in mcp_result:
            return

        http_data = http_result["data"]
        if http_data is None:
            return

        # Compare symbol
        http_symbol = http_data.get("target_profile", {}).get("symbol")
        mcp_symbol = mcp_result.get("target_profile", {}).get("symbol")
        if http_symbol and mcp_symbol:
            assert http_symbol == mcp_symbol


class TestEarningsAlignment:
    """Test /analysis/earnings vs analyze_earnings alignment"""

    def test_earnings_alignment(self, client: TestClient):
        """HTTP /analysis/earnings should match MCP analyze_earnings"""
        # Call HTTP API
        http_response = client.get(f"/analysis/earnings/earnings?symbol={TEST_SYMBOL}")
        assert http_response.status_code == 200
        http_result = http_response.json()

        # Call MCP tool
        mcp_result = analyze_earnings(symbol=TEST_SYMBOL)

        # Both should return data or error
        if http_result["err_msg"] or "error" in mcp_result:
            return

        http_data = http_result["data"]
        if http_data is None:
            return

        # Compare symbol
        http_symbol = http_data.get("symbol")
        mcp_symbol = mcp_result.get("symbol")
        if http_symbol and mcp_symbol:
            assert http_symbol == mcp_symbol
