"""
Offline HTTP-only contract tests for the structured response adapters.
"""

from src.analyzer.normalizers import (
    comps_contract,
    dcf_contract,
    earnings_contract,
    stock_analysis_contract,
    stock_record,
    three_statement_contract,
)


class TestHTTPOnlyStructuredContracts:
    def test_stock_record_adds_meta(self):
        payload = stock_record({"ts_code": "NVDA.US", "symbol": "NVDA", "name": "NVIDIA"})
        assert payload["meta"]["source"] == "stock_list_provider"
        assert payload["symbol"] == "NVDA"

    def test_stock_analysis_contract_uses_structured_shape(self):
        payload = stock_analysis_contract(
            {
                "symbol": "NVDA",
                "stock_name": "NVIDIA",
                "price": 100.0,
                "as_of": "2026-03-20",
                "fear_greed": {"index": 50.0, "label": "中性"},
                "technical": {"factors": [], "data_source": "US_yfinance"},
                "fundamental": {"factors": [], "data_source": "yfinance", "raw_data": {"info": {}}},
                "qlib": {"factors": []},
                "trend_analysis": None,
            }
        )
        assert payload["meta"]["interface_type"] == "mixed"
        assert payload["meta"]["schema_version"] == "2.0.0"
        assert payload["facts"]["fundamentals"]["valuation"]["status"] in {
            "partial",
            "ok",
            "not_supported",
        }
        assert "coverage" in payload["facts"]["fundamentals"]
        assert "fundamental_context" not in payload["analysis"]

    def test_stock_analysis_contract_removes_legacy_scattered_fundamental_fields(self):
        payload = stock_analysis_contract(
            {
                "symbol": "AAPL",
                "stock_name": "Apple",
                "price": 200.0,
                "as_of": "2026-03-20",
                "fear_greed": {"index": 55.0, "label": "中性"},
                "technical": {"factors": [], "data_source": "US_yfinance"},
                "fundamental": {
                    "factors": [
                        {"key": "trailingPE", "status": "30.0x"},
                        {"key": "totalRevenue", "status": "$100B"},
                        {"key": "bookValue", "status": "$4.00"},
                    ],
                    "data_source": "yfinance",
                    "raw_data": {
                        "info": {
                            "trailingPE": 30.0,
                            "totalRevenue": 100_000_000_000,
                            "bookValue": 4.0,
                            "marketCap": 3_000_000_000_000,
                        }
                    },
                },
                "qlib": {"factors": []},
                "trend_analysis": None,
            }
        )

        assert set(payload["facts"].keys()) == {"market_snapshot", "fundamentals"}
        assert "trailingPE" not in payload["facts"]["fundamentals"]
        assert "totalRevenue" not in payload["facts"]["fundamentals"]
        assert "bookValue" not in payload["facts"]["fundamentals"]
        assert payload["facts"]["fundamentals"]["market"] == "us"

    def test_earnings_contract_exposes_period_meta(self):
        payload = earnings_contract(
            {
                "symbol": "NVDA",
                "company_name": "NVIDIA",
                "quarter": "Q4",
                "fiscal_year": 2026,
                "fiscal_period": "Q4 FY2026",
                "report_date": "2026-01-31",
                "as_of": "2026-01-31",
                "earnings_summary": {
                    "revenue": {"actual": "$68.13B"},
                    "net_income": {"actual": "$42.96B"},
                    "ebitda": {"actual": "$51.28B"},
                    "earnings_per_share": {"eps": "$1.76"},
                },
                "beat_miss_analysis": {"status": "unavailable"},
                "segment_performance": [],
                "guidance": {},
                "key_metrics": {},
                "trends": {},
                "sources": [],
            }
        )
        assert payload["meta"]["report_date"] == "2026-01-31"
        assert payload["facts"]["consensus_comparison"]["status"] == "unavailable"
        assert payload["analysis"]["research_strategy"]["framework"].startswith("financial-services-plugins")

    def test_dcf_contract_marks_model_interface(self):
        payload = dcf_contract(
            {
                "symbol": "NVDA",
                "company_name": "NVIDIA",
                "currency": "USD",
                "current_price": 100.0,
                "wacc": 8.5,
                "fcf_source": "cashflow_statement",
                "data_completeness": "partial",
                "assumptions_source": "heuristic",
                "as_of": "2026-01-31",
            }
        )
        assert payload["meta"]["interface_type"] == "model"

    def test_comps_contract_keeps_peer_selection_meta(self):
        payload = comps_contract(
            {
                "target_symbol": "NVDA",
                "target_name": "NVIDIA",
                "sector": "Technology",
                "industry": "Semiconductors",
                "comps": [],
                "operating_metrics": {},
                "valuation_multiples": {},
                "percentiles": {},
                "implied_valuation": {},
                "recommendation": "FAIR",
                "confidence": "MEDIUM",
                "peer_selection_method": "hardcoded_industry_peer_map",
                "peer_universe": ["AMD"],
                "peer_selection_limitations": ["Static peer set"],
            }
        )
        assert payload["meta"]["peer_selection"]["method"] == "hardcoded_industry_peer_map"

    def test_three_statement_contract_marks_model_interface(self):
        payload = three_statement_contract(
            {
                "symbol": "NVDA",
                "company_name": "NVIDIA",
                "historical_source": "yfinance financial statements",
                "as_of": "2026-01-31",
                "limitations": [],
            }
        )
        assert payload["meta"]["interface_type"] == "model"
