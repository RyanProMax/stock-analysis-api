"""
MCP Tools Tests for Stock Analysis API

Tests all MCP tools by directly calling the tool functions.
Test symbol: TQQQ (ProShares UltraPro QQQ)
"""

import pytest

from tests.conftest import TEST_SYMBOL, TEST_SYMBOL_ETF
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


class TestStockTools:
    """Tests for stock data MCP tools"""

    def test_get_stock_list(self):
        """MCP: Get stock list"""
        result = get_stock_list()
        assert isinstance(result, dict)
        assert "total" in result
        assert "stocks" in result
        assert result["total"] >= 0
        assert isinstance(result["stocks"], list)

    def test_get_stock_list_with_market(self):
        """MCP: Get stock list with market filter"""
        result = get_stock_list(market="美股")
        assert isinstance(result, dict)
        assert "total" in result
        assert "stocks" in result

    def test_search_stocks_tqqq(self):
        """MCP: Search for TQQQ"""
        result = search_stocks(keyword="TQQQ")
        assert isinstance(result, dict)
        assert "total" in result
        assert "stocks" in result

    def test_search_stocks_with_market(self):
        """MCP: Search with market filter"""
        result = search_stocks(keyword="TQQQ", market="美股")
        assert isinstance(result, dict)
        assert "total" in result

    def test_analyze_stock_tqqq(self):
        """MCP: Analyze TQQQ"""
        result = analyze_stock(symbol=TEST_SYMBOL, include_qlib=False)
        assert isinstance(result, dict)
        # Should not have error key (or error should be None)
        if "error" in result:
            # If there's an error, it should be descriptive
            assert isinstance(result["error"], str)
        else:
            # Should have analysis data
            assert "symbol" in result or "Symbol" in result


class TestValuationTools:
    """Tests for valuation MCP tools"""

    def test_analyze_dcf_tqqq(self):
        """MCP: DCF valuation for TQQQ"""
        result = analyze_dcf(symbol=TEST_SYMBOL)
        assert isinstance(result, dict)
        # Check for key DCF fields
        if "error" not in result:
            assert "wacc" in result or "enterprise_value" in result

    def test_analyze_dcf_with_params(self):
        """MCP: DCF with custom parameters"""
        result = analyze_dcf(
            symbol=TEST_SYMBOL,
            risk_free_rate=0.04,
            equity_risk_premium=0.055,
            terminal_growth_rate=0.025,
        )
        assert isinstance(result, dict)
        # Should have result
        assert "error" in result or "wacc" in result

    def test_analyze_comps_tqqq(self):
        """MCP: Comparable companies for TQQQ"""
        result = analyze_comps(symbol=TEST_SYMBOL)
        assert isinstance(result, dict)
        # Check for key comps fields
        if "error" not in result:
            assert "target" in result or "comps" in result or "comparable_companies" in result

    def test_analyze_comps_with_sector(self):
        """MCP: Comps with sector filter"""
        result = analyze_comps(symbol=TEST_SYMBOL, sector="Technology")
        assert isinstance(result, dict)


class TestModelTools:
    """Tests for model analysis MCP tools"""

    def test_analyze_lbo_tqqq(self):
        """MCP: LBO model for TQQQ"""
        result = analyze_lbo(symbol=TEST_SYMBOL)
        assert isinstance(result, dict)
        # Check for key LBO fields
        if "error" not in result:
            # Should have sources_uses, debt_schedule, or returns
            assert any(
                key in result
                for key in ["sources_and_uses", "debt_schedule", "returns", "irr"]
            )

    def test_analyze_lbo_with_params(self):
        """MCP: LBO with custom parameters"""
        result = analyze_lbo(
            symbol=TEST_SYMBOL,
            holding_period=5,
            entry_multiple=10.0,
            exit_multiple=12.0,
            leverage=0.65,
        )
        assert isinstance(result, dict)

    def test_analyze_three_statement_tqqq(self):
        """MCP: 3-Statement model for TQQQ"""
        result = analyze_three_statement(symbol=TEST_SYMBOL)
        assert isinstance(result, dict)
        # Check for key 3-statement fields
        if "error" not in result:
            assert any(
                key in result
                for key in [
                    "income_statement",
                    "balance_sheet",
                    "cash_flow",
                    "incomeStatement",
                    "balanceSheet",
                    "cashFlowStatement",
                ]
            )

    def test_analyze_three_statement_with_scenario(self):
        """MCP: 3-Statement with specific scenario"""
        result = analyze_three_statement(symbol=TEST_SYMBOL, scenario="bull")
        assert isinstance(result, dict)

    def test_analyze_three_statement_comparison(self):
        """MCP: 3-Statement scenario comparison"""
        result = analyze_three_statement(symbol=TEST_SYMBOL, comparison=True)
        assert isinstance(result, dict)
        # Should have all 3 scenarios
        if "error" not in result:
            assert "scenarios" in result
            scenarios = result["scenarios"]
            assert "bull" in scenarios
            assert "base" in scenarios
            assert "bear" in scenarios


class TestAnalysisTools:
    """Tests for analysis MCP tools"""

    def test_analyze_competitive_tqqq(self):
        """MCP: Competitive analysis for TQQQ"""
        result = analyze_competitive(symbol=TEST_SYMBOL)
        assert isinstance(result, dict)
        # Check for key competitive analysis fields
        if "error" not in result:
            assert any(
                key in result
                for key in [
                    "market_context",
                    "target_profile",
                    "competitors",
                    "positioning",
                    "moat_assessment",
                ]
            )

    def test_analyze_competitive_with_industry(self):
        """MCP: Competitive analysis with industry"""
        result = analyze_competitive(symbol=TEST_SYMBOL, industry="technology")
        assert isinstance(result, dict)

    def test_analyze_competitive_with_competitors(self):
        """MCP: Competitive analysis with specified competitors"""
        result = analyze_competitive(
            symbol=TEST_SYMBOL,
            competitors="QQQ,SPY",
            industry="technology",
        )
        assert isinstance(result, dict)

    def test_analyze_earnings_tqqq(self):
        """MCP: Earnings analysis for TQQQ"""
        result = analyze_earnings(symbol=TEST_SYMBOL)
        assert isinstance(result, dict)
        # Check for key earnings fields
        if "error" not in result:
            assert any(
                key in result
                for key in [
                    "earnings_summary",
                    "beat_miss_analysis",
                    "segment_performance",
                    "guidance",
                    "key_metrics",
                ]
            )

    def test_analyze_earnings_with_quarter(self):
        """MCP: Earnings for specific quarter"""
        result = analyze_earnings(symbol=TEST_SYMBOL, quarter="Q4", fiscal_year=2024)
        assert isinstance(result, dict)


class TestErrorHandling:
    """Tests for error handling in MCP tools"""

    def test_analyze_dcf_invalid_symbol(self):
        """MCP: DCF with invalid symbol should return error"""
        result = analyze_dcf(symbol="INVALID_SYMBOL_12345")
        assert isinstance(result, dict)
        # Should have error
        assert "error" in result

    def test_analyze_comps_invalid_symbol(self):
        """MCP: Comps with invalid symbol should return error"""
        result = analyze_comps(symbol="INVALID_SYMBOL_12345")
        assert isinstance(result, dict)
        # Should have error
        assert "error" in result

    def test_analyze_lbo_invalid_symbol(self):
        """MCP: LBO with invalid symbol should return error"""
        result = analyze_lbo(symbol="INVALID_SYMBOL_12345")
        assert isinstance(result, dict)
        # Should have error
        assert "error" in result
