"""
Offline semantic tests for recent data-contract fixes.

These tests avoid live network access and lock in the expected behavior of:
- fiscal period derivation for non-calendar fiscal years
- report serialization for stock/analyze contract stability
- comps recommendation direction consistency
- dcf historical FCF extraction without pseudo-history backfill
"""

import json

import pandas as pd

from src.analyzer.competitive_analyzer import CompetitiveAnalyzer
from src.analyzer.comps_analyzer import CompsAnalyzer
from src.analyzer.dcf_model import DCFModel
from src.analyzer.earnings_analyzer import EarningsAnalyzer
from src.analyzer.fundamental_factors import _format_percent, _format_yahoo_dividend_yield
from src.analyzer.normalizers import (
    compute_trailing_dividend_yield,
    format_ratio_as_percent,
    select_latest_metric_column,
)
from src.data_provider.sources.akshare import AkShareDataSource
from src.data_provider.sources.tushare import TushareDataSource
from src.data_provider.sources.yfinance import YfinanceDataSource
from src.data_provider.fundamental_adapter import (
    build_dividend_payload_from_series,
    enrich_dividend_payload_with_yield,
)
from src.analyzer.three_statement_model import ThreeStatementModel
from src.model.comps import CompCompany
from src.model.report import AnalysisReport, FactorAnalysis, FearGreed
from src.model.trend import TrendAnalysisResult, TrendStatus
from src.data_provider.fundamental_context import build_fundamental_context
from src.analyzer.research_strategy import build_earnings_research_strategy


class TestEarningsSemanticFixes:
    def test_fiscal_period_derivation_for_january_year_end(self):
        analyzer = EarningsAnalyzer()
        fiscal_year_end = pd.Timestamp("2026-01-31")

        assert analyzer._derive_fiscal_period(pd.Timestamp("2026-01-31"), fiscal_year_end) == (
            "Q4",
            2026,
        )
        assert analyzer._derive_fiscal_period(pd.Timestamp("2025-10-31"), fiscal_year_end) == (
            "Q3",
            2026,
        )
        assert analyzer._derive_fiscal_period(pd.Timestamp("2025-07-31"), fiscal_year_end) == (
            "Q2",
            2026,
        )
        assert analyzer._derive_fiscal_period(pd.Timestamp("2025-04-30"), fiscal_year_end) == (
            "Q1",
            2026,
        )

    def test_dividend_yield_uses_trailing_cash_dividends_not_info_thresholds(self):
        dividends = pd.Series(
            [0.25, 0.25, 0.25, 0.25],
            index=pd.to_datetime(["2025-02-01", "2025-05-01", "2025-08-01", "2025-11-01"]),
        )
        ratio = compute_trailing_dividend_yield(dividends, 100.0, as_of="2025-12-31")
        payload = enrich_dividend_payload_with_yield(
            build_dividend_payload_from_series(dividends, as_of=pd.Timestamp("2025-12-31")),
            100.0,
        )

        assert ratio == 0.01
        assert payload["ttm_cash_dividend_per_share"] == 1.0
        assert payload["ttm_dividend_yield_pct"] == 1.0
        assert _format_yahoo_dividend_yield(ratio) == "1.00%"
        assert format_ratio_as_percent(ratio) == "1.00%"
        assert _format_percent(0.04211) == "4.21%"


class TestStockAnalyzeSerializationFixes:
    def test_analysis_report_to_dict_is_json_serializable(self):
        report = AnalysisReport(
            symbol="NVDA",
            stock_name="NVIDIA",
            price=100.0,
            as_of="2026-03-20",
            fear_greed=FearGreed(index=60.0, label="贪婪"),
            technical=FactorAnalysis(),
            fundamental=FactorAnalysis(),
            qlib=FactorAnalysis(),
            trend_analysis=TrendAnalysisResult(code="NVDA", trend_status=TrendStatus.BULL),
        )

        payload = report.to_dict()
        json.dumps(payload, ensure_ascii=False)

        assert payload["as_of"] == "2026-03-20"
        assert payload["trend_analysis"]["trend_status"] == "多头排列"


class TestCompsSemanticFixes:
    def test_recommendation_tracks_implied_valuation_direction(self):
        analyzer = CompsAnalyzer()
        target = CompCompany(
            symbol="T",
            company_name="Target",
            sector="Tech",
            industry="Tech",
            market_cap=1000,
            enterprise_value=1200,
            current_price=10,
        )

        undervalued = analyzer._generate_recommendation(
            target,
            {"pe": {"mid": 1400}, "ps": {"mid": 1300}, "ev_ebitda": {"mid": 1500}},
        )
        overvalued = analyzer._generate_recommendation(
            target,
            {"pe": {"mid": 700}, "ps": {"mid": 750}, "ev_ebitda": {"mid": 800}},
        )
        fair = analyzer._generate_recommendation(
            target,
            {"pe": {"mid": 1000}, "ps": {"mid": 1020}, "ev_ebitda": {"mid": 1180}},
        )

        assert undervalued["rating"] == "UNDERVALUED"
        assert overvalued["rating"] == "OVERVALUED"
        assert fair["rating"] == "FAIR"


class TestDCFSemanticFixes:
    def test_extracts_real_fcf_history_in_chronological_order(self):
        model = DCFModel()
        cashflow = pd.DataFrame(
            {
                pd.Timestamp("2024-01-31"): [1000, -200],
                pd.Timestamp("2025-01-31"): [1200, -250],
            },
            index=["Operating Cash Flow", "Capital Expenditure"],
        )

        history, as_of = model._extract_fcf_from_cashflow(cashflow)

        assert history == [800.0, 950.0]
        assert as_of == "2025-01-31"

    def test_fallback_partial_does_not_backfill_multiple_periods(self):
        model = DCFModel()
        stock = type("StockStub", (), {"cashflow": pd.DataFrame()})()

        history, source, completeness, as_of = model._get_historical_fcf(
            stock,
            {"operatingCashflow": 500, "capitalExpenditures": -100},
        )

        assert history == [400]
        assert source == "info_operating_cashflow_minus_capex"
        assert completeness == "partial"
        assert as_of is None


class TestThreeStatementSemanticFixes:
    def test_bs_projection_uses_baseline_working_capital_and_non_negative_debt(self):
        model = ThreeStatementModel()
        income_statements = model._project_income_statement(1000, model.SCENARIOS["base"])
        balance_sheets, cash_flows = model._project_bs_and_cf(
            income_statements,
            initial_equity=600,
            initial_cash=200,
            baseline={
                "accounts_receivable": 150,
                "inventory": 100,
                "accounts_payable": 90,
                "total_debt": 120,
                "ppe": 300,
            },
            params=model.SCENARIOS["base"],
        )

        assert balance_sheets[0]["cash"] > 0
        assert balance_sheets[0]["total_debt"] >= 0
        assert balance_sheets[0]["total_liabilities"] >= 0
        assert abs(balance_sheets[0]["balance_check"]) < 0.01
        assert cash_flows[0]["beginning_cash"] == 200


class TestCompetitiveSemanticFixes:
    def test_positioning_and_comparative_use_raw_peer_metrics(self):
        analyzer = CompetitiveAnalyzer()
        target = {"symbol": "NVDA", "marketCap": 1000, "revenueGrowth": 0.5, "revenue": 400}
        peer = {"symbol": "AMD", "longName": "AMD", "marketCap": 500, "revenueGrowth": 0.2, "revenue": 200}

        positioning = analyzer._generate_positioning(target, [peer], "technology")
        comparative = analyzer._generate_comparative(target, [peer], "technology")

        amd_point = next(item for item in positioning["data_points"] if item["symbol"] == "AMD")
        amd_row = next(item for item in comparative["comparison_table"] if item["symbol"] == "AMD")

        assert amd_point["x"] == 500 / 1e9
        assert amd_point["y"] == 20.0
        assert amd_row["market_cap"] == 500 / 1e9
        assert amd_row["revenue"] == 200 / 1e9


class TestSourceFieldNormalizationFixes:
    def test_yfinance_normalized_fields_use_canonical_names(self):
        class TickerStub:
            dividends = pd.Series(
                [0.1, 0.1, 0.1, 0.1],
                index=pd.to_datetime(["2025-04-01", "2025-07-01", "2025-10-01", "2026-01-01"]),
            )

        normalized = YfinanceDataSource._build_normalized_fields(
            TickerStub(),
            {
                "currentPrice": 50.0,
                "payoutRatio": 0.2,
                "bookValue": 6.5,
                "heldPercentInsiders": 0.04,
            },
        )

        assert normalized["dividend_yield"]["value"] == 0.008
        assert normalized["dividend_metrics"]["ttm_cash_dividend_per_share"] == 0.4
        assert normalized["dividend_yield"]["field"] == "dividend_yield"
        assert normalized["book_value_per_share"]["unit"] == "currency_per_share"
        assert normalized["payout_ratio"]["display_value"] == "20.00%"

    def test_tushare_revenue_growth_uses_same_period_comparable_reports(self):
        df = pd.DataFrame(
            [
                {"end_date": "20250930", "revenue": 1500, "ann_date": "20251101"},
                {"end_date": "20250630", "revenue": 1000, "ann_date": "20250801"},
                {"end_date": "20240930", "revenue": 1200, "ann_date": "20241101"},
            ]
        )
        growth = TushareDataSource._compute_same_period_revenue_growth(df)

        assert round(growth, 4) == 0.25

    def test_akshare_uses_latest_named_metric_column_not_position(self):
        df = pd.DataFrame(
            {
                "选项": ["常用指标"],
                "指标": ["净资产收益率(ROE)"],
                "2024-12-31": ["12.5%"],
                "2025-03-31": ["15.0%"],
            }
        )

        latest_col = select_latest_metric_column(df)
        value = AkShareDataSource._coerce_metric_value(df.iloc[0][latest_col])

        assert latest_col == "2025-03-31"
        assert value == 15.0

    def test_fundamental_context_matches_daily_stock_analysis_bundle_shape(self):
        context = build_fundamental_context(
            symbol="AAPL",
            financial_data={
                "raw_data": {
                    "info": {
                        "trailingPE": 30.0,
                        "priceToBook": 40.0,
                        "marketCap": 1000,
                        "enterpriseValue": 1100,
                        "revenueGrowth": 0.1,
                        "earningsGrowth": 0.2,
                        "returnOnEquity": 1.0,
                        "grossMargins": 0.4,
                        "totalRevenue": 500,
                        "netIncomeToCommon": 100,
                        "operatingCashflow": 120,
                    },
                    "normalized_fields": {
                        "dividend_metrics": {"ttm_cash_dividend_per_share": 1.0, "ttm_dividend_yield_pct": 0.5},
                        "held_percent_insiders": {"value": 0.01},
                        "held_percent_institutions": {"value": 0.65},
                        "shares_percent_shares_out": {"value": 0.02},
                    },
                }
            },
            latest_price=200.0,
            as_of="2026-03-19",
        )

        assert context["market"] == "us"
        assert set(context.keys()) >= {
            "coverage",
            "valuation",
            "growth",
            "earnings",
            "institution",
            "capital_flow",
            "dragon_tiger",
            "boards",
        }
        valuation_data = context["valuation"]["data"]
        assert valuation_data["total_mv"] == 1000
        assert valuation_data["circ_mv"] is None
        assert "market_cap" not in valuation_data
        assert valuation_data["extensions"]["enterprise_value"] == 1100
        assert context["growth"]["data"]["summary"] == "revenue_yoy=10.00%, net_profit_yoy=20.00%"
        assert context["earnings"]["source_chain"][1]["provider"] == "yfinance.dividends"
        institution_data = context["institution"]["data"]
        assert institution_data["insider_holding_ratio"] == 0.01
        assert institution_data["institution_holding_ratio"] == 0.65
        assert institution_data["short_interest_ratio"] == 0.02
        assert institution_data["institution_holding_change"] is None
        assert institution_data["top10_holder_change"] is None
        assert "held_percent_insiders" not in institution_data
        assert "insiders=1.00%" in institution_data["summary"]
        earnings_data = context["earnings"]["data"]
        assert earnings_data["forecast_summary"] == ""
        assert earnings_data["quick_report_summary"] == ""
        assert earnings_data["dividend"]["ttm_cash_dividend_per_share"] == 1.0

    def test_research_strategy_uses_plugin_style_sections(self):
        strategy = build_earnings_research_strategy(
            {
                "earnings_summary": {
                    "revenue": {"actual": "$10.00B"},
                    "earnings_per_share": {"eps": "$1.00"},
                },
                "key_metrics": {
                    "growth": {"revenue_growth": "10.0%", "earnings_growth": "12.0%"},
                    "profitability": {"gross_margin": "40.0%", "operating_margin": "20.0%"},
                    "dividends": {"dividend_yield": "1.00%"},
                },
                "guidance": {"direction": "Maintaining"},
                "beat_miss_analysis": {"status": "unavailable"},
            }
        )

        assert "earnings_summary_box" in strategy
        assert "thesis_scorecard" in strategy
        assert strategy["investment_impact"]["guidance_direction"] == "Maintaining"
