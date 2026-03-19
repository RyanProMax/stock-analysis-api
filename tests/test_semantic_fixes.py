"""
Offline semantic tests for recent data-contract fixes.

These tests avoid live network access and lock in the expected behavior of:
- fiscal period derivation for non-calendar fiscal years
- report serialization for stock/analyze cache safety
- comps recommendation direction consistency
- dcf historical FCF extraction without pseudo-history backfill
"""

import json

import pandas as pd

from src.analyzer.comps_analyzer import CompsAnalyzer
from src.analyzer.dcf_model import DCFModel
from src.analyzer.earnings_analyzer import EarningsAnalyzer
from src.model.comps import CompCompany
from src.model.report import AnalysisReport, FactorAnalysis, FearGreed
from src.model.trend import TrendAnalysisResult, TrendStatus


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
