"""
Offline HTTP-only contract tests for the structured response adapters.
"""

from src.analyzer.normalizers import (
    comps_contract,
    competitive_contract,
    dcf_contract,
    earnings_contract,
    lbo_contract,
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
        assert "yfinance.info" in payload["meta"]["sources"]
        assert "fundamental_pipeline" not in payload["meta"]["sources"]

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
                "fundamental_context": {
                    "earnings": {
                        "data": {
                            "dividend": {
                                "ttm_cash_dividend_per_share": 0.04,
                                "ttm_dividend_yield_pct": 0.02,
                            }
                        }
                    }
                },
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
        assert payload["analysis"]["key_metrics"]["dividend_metrics"]["ttm_cash_dividend_per_share"] == 0.04

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
                "fundamental_context": {"market": "us", "source_chain": [{"provider": "yfinance.info", "result": "ok"}]},
            }
        )
        assert payload["meta"]["interface_type"] == "model"
        assert payload["facts"]["fundamentals"]["market"] == "us"
        assert "yfinance.info" in payload["meta"]["sources"]

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
                "fundamental_context": {
                    "market": "us",
                    "source_chain": [{"provider": "yfinance.info", "result": "ok"}],
                    "earnings": {"data": {"financial_report": {"revenue": 1000}}},
                    "valuation": {"data": {"price": 100, "total_mv": 10000}},
                    "growth": {"data": {"revenue_yoy": 0.2}},
                },
            }
        )
        assert payload["meta"]["peer_selection"]["method"] == "hardcoded_industry_peer_map"
        assert payload["facts"]["fundamentals"]["market"] == "us"
        assert payload["facts"]["target"]["financial_report"]["revenue"] == 1000
        assert payload["facts"]["target"]["valuation_metrics"]["price"] == 100
        assert payload["facts"]["target"]["company_profile"]["overview"]["total_mv"]["field"] == "total_mv"

    def test_competitive_contract_uses_dsa_style_peer_fields_and_normalized_sources(self):
        payload = competitive_contract(
            {
                "symbol": "NVDA",
                "company_name": "NVIDIA",
                "fundamental_context": {
                    "market": "us",
                    "source_chain": [{"provider": "yfinance.info", "result": "ok"}],
                    "valuation": {
                        "data": {
                            "price": 100.0,
                            "total_mv": 1_000_000_000_000,
                            "pb_ratio": 10.0,
                            "pe_ratio": 30.0,
                            "extensions": {"price_to_sales": 5.0},
                        }
                    },
                    "growth": {"data": {"revenue_yoy": 0.2, "gross_margin": 0.7}},
                    "earnings": {"data": {"financial_report": {"revenue": 200_000_000_000}}},
                },
                "target_metrics": {
                    "sector": "Technology",
                    "industry": "Semiconductors",
                    "currentPrice": 100.0,
                    "marketCap": 1_000_000_000_000,
                    "revenue": 200_000_000_000,
                    "revenueGrowth": 0.2,
                    "grossMargins": 0.7,
                    "ebitdaMargins": 0.5,
                    "operatingMargins": 0.4,
                    "profitMargins": 0.3,
                    "peRatio": 30.0,
                    "forwardPE": 20.0,
                    "pegRatio": 1.5,
                    "priceToBook": 10.0,
                    "priceToSales": 5.0,
                    "recommendationKey": "buy",
                    "targetMeanPrice": 120.0,
                    "numberOfAnalystOpinions": 10,
                },
                "target_profile": {},
                "comparative": {
                    "comparison_table": [
                        {"symbol": "AMD", "name": "AMD", "market_cap": 500, "revenue": 200, "growth": 20}
                    ]
                },
                "market_context": {
                    "estimated_market_context": {"methodology": "heuristic_market_context_v1"}
                },
                "positioning": {},
                "moat_assessment": {},
                "industry_metrics": {},
                "scenario_analysis": {},
            }
        )

        peer = payload["facts"]["peer_set"][0]
        profile = payload["facts"]["company_profile"]
        assert payload["facts"]["fundamentals"]["market"] == "us"
        assert profile["overview"]["total_mv"]["field"] == "total_mv"
        assert profile["overview"]["revenue_yoy"]["field"] == "revenue_yoy"
        assert profile["valuation"]["pb_ratio"]["field"] == "pb_ratio"
        assert profile["analyst_consensus"]["target_mean_price"]["field"] == "target_mean_price"
        assert "total_mv" in peer
        assert "revenue_yoy" in peer
        assert "market_cap" not in peer
        assert "growth" not in peer
        assert "heuristic_market_context_v1" in payload["meta"]["sources"]

    def test_three_statement_contract_marks_model_interface(self):
        payload = three_statement_contract(
            {
                "symbol": "NVDA",
                "company_name": "NVIDIA",
                "historical_source": "yfinance financial statements",
                "as_of": "2026-01-31",
                "limitations": [],
                "fundamental_context": {"market": "us", "source_chain": [{"provider": "yfinance.info", "result": "ok"}]},
            }
        )
        assert payload["meta"]["interface_type"] == "model"
        assert payload["facts"]["fundamentals"]["market"] == "us"

    def test_lbo_contract_includes_shared_fundamental_context(self):
        payload = lbo_contract(
            {
                "symbol": "NVDA",
                "company_name": "NVIDIA",
                "purchase_price": 1000,
                "current_price": 100,
                "assumptions_source": "entry_exit_multiples_leverage_and_margin_assumptions",
                "fundamental_context": {"market": "us", "source_chain": [{"provider": "yfinance.info", "result": "ok"}]},
            }
        )
        assert payload["facts"]["fundamentals"]["market"] == "us"
        assert "yfinance.info" in payload["meta"]["sources"]
