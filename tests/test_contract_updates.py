"""
Offline contract tests for Phase 3 updates.

These tests avoid network access and verify:
- HTTP/MCP stock list limit behavior is explicit and aligned
- newly added metadata fields exist in model outputs
"""

from src.mcp_server import server as mcp_server_module
from src.api.routes import stock as stock_routes
from src.model.comps import CompsResult
from src.model.dcf import DCFResult
from src.model.lbo import LBOResult


class TestStockListLimitContract:
    def test_http_stock_list_limit_is_explicit(self, monkeypatch):
        sample = [
            {"ts_code": "AAA.US", "symbol": "AAA", "name": "AAA", "market": "美股"},
            {"ts_code": "BBB.US", "symbol": "BBB", "name": "BBB", "market": "美股"},
            {"ts_code": "CCC.US", "symbol": "CCC", "name": "CCC", "market": "美股"},
        ]

        monkeypatch.setattr(stock_routes.stock_service, "get_stock_list", lambda market, refresh: sample)
        response = stock_routes.get_stock_list(market="美股", limit=2)
        data = response.data
        assert data.total == 2
        assert [item.symbol for item in data.stocks] == ["AAA", "BBB"]

    def test_mcp_stock_list_limit_is_explicit(self, monkeypatch):
        sample = [
            {"ts_code": "AAA.US", "symbol": "AAA", "name": "AAA", "market": "美股"},
            {"ts_code": "BBB.US", "symbol": "BBB", "name": "BBB", "market": "美股"},
            {"ts_code": "CCC.US", "symbol": "CCC", "name": "CCC", "market": "美股"},
        ]

        monkeypatch.setattr(mcp_server_module.stock_service, "get_stock_list", lambda market, refresh: sample)

        result = mcp_server_module.get_stock_list(market="美股", limit=2)
        assert result["total"] == 2
        assert [item["symbol"] for item in result["stocks"]] == ["AAA", "BBB"]


class TestModelMetadataContract:
    def test_dcf_result_to_dict_exposes_metadata(self):
        result = DCFResult(
            symbol="NVDA",
            model_type="quick_model",
            data_completeness="partial",
            assumptions_source="historical_cashflow_plus_model_assumptions",
            fcf_source="cashflow_statement",
            as_of="2025-01-31",
        )

        payload = result.to_dict()
        assert payload["model_type"] == "quick_model"
        assert payload["data_completeness"] == "partial"
        assert payload["assumptions_source"] == "historical_cashflow_plus_model_assumptions"
        assert payload["fcf_source"] == "cashflow_statement"
        assert payload["as_of"] == "2025-01-31"

    def test_comps_result_to_dict_exposes_peer_selection_metadata(self):
        result = CompsResult(
            target_symbol="NVDA",
            peer_selection_method="hardcoded_industry_peer_map",
            peer_universe=["AMD", "AVGO"],
            peer_selection_limitations=["Static peer universe"],
        )

        payload = result.to_dict()
        assert payload["peer_selection_method"] == "hardcoded_industry_peer_map"
        assert payload["peer_universe"] == ["AMD", "AVGO"]
        assert payload["peer_selection_limitations"] == ["Static peer universe"]

    def test_lbo_result_to_dict_exposes_model_metadata(self):
        result = LBOResult(
            symbol="NVDA",
            model_type="scenario",
            derived_from_assumptions=True,
            assumptions_source="entry_exit_multiples_leverage_and_margin_assumptions",
        )

        payload = result.to_dict()
        assert payload["model_type"] == "scenario"
        assert payload["derived_from_assumptions"] is True
        assert payload["assumptions_source"] == "entry_exit_multiples_leverage_and_margin_assumptions"
