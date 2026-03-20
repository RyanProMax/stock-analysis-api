# -*- coding: utf-8 -*-
"""
Earnings Analysis 分析器

季报分析，包括:
- Beat/Miss 分析
- 关键财务指标
- 指引更新分析
- 趋势图表数据
"""

import yfinance as yf
from datetime import datetime
import requests
from typing import Dict, List, Any, Optional
import pandas as pd

from .normalizers import compute_trailing_dividend_yield, format_ratio_as_percent


class EarningsAnalysisResult:
    """季报分析结果"""

    def __init__(
        self,
        symbol: str,
        company_name: str = "",
        quarter: Optional[str] = "",
        fiscal_year: Optional[int] = None,
        fiscal_period: Optional[str] = None,
        report_date: Optional[str] = None,
        as_of: Optional[str] = None,
        earnings_summary: Optional[Dict] = None,
        beat_miss_analysis: Optional[Dict] = None,
        segment_performance: Optional[List[Dict]] = None,
        guidance: Optional[Dict] = None,
        key_metrics: Optional[Dict] = None,
        trends: Optional[Dict] = None,
        sources: Optional[List[str]] = None,
        error: Optional[str] = None,
    ):
        self.symbol = symbol
        self.company_name = company_name
        self.quarter = quarter
        self.fiscal_year = fiscal_year
        self.fiscal_period = fiscal_period
        self.report_date = report_date
        self.as_of = as_of
        self.earnings_summary = earnings_summary or {}
        self.beat_miss_analysis = beat_miss_analysis or {}
        self.segment_performance = segment_performance or []
        self.guidance = guidance or {}
        self.key_metrics = key_metrics or {}
        self.trends = trends or {}
        self.sources = sources or []
        self.error = error

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "company_name": self.company_name,
            "quarter": self.quarter,
            "fiscal_year": self.fiscal_year,
            "fiscal_period": self.fiscal_period,
            "report_date": self.report_date,
            "as_of": self.as_of,
            "earnings_summary": self.earnings_summary,
            "beat_miss_analysis": self.beat_miss_analysis,
            "segment_performance": self.segment_performance,
            "guidance": self.guidance,
            "key_metrics": self.key_metrics,
            "trends": self.trends,
            "sources": self.sources,
            "error": self.error,
        }


class EarningsAnalyzer:
    """
    季报分析器

    基于最新财报数据分析 Beat/Miss、关键指标和指引更新
    """

    def __init__(self):
        pass

    def analyze(
        self,
        symbol: str,
        quarter: Optional[str] = None,
        fiscal_year: Optional[int] = None,
    ) -> EarningsAnalysisResult:
        """
        执行季报分析

        Args:
            symbol: 股票代码
            quarter: 季度 (Q1, Q2, Q3, Q4)，默认最新季度
            fiscal_year: 财年，默认当前年份

        Returns:
            EarningsAnalysisResult: 季报分析结果
        """
        try:
            # 获取公司数据
            stock = yf.Ticker(symbol)
            info = stock.info

            if not info:
                return EarningsAnalysisResult(
                    symbol=symbol,
                    error=f"无法获取 {symbol} 的数据",
                )

            company_name = info.get("longName", info.get("shortName", symbol))
            dividend_metrics = self._extract_dividend_metrics(stock, info)

            # 获取历史财务数据
            financials = self._get_financials(stock)

            report_context = self._resolve_reporting_period(
                financials, quarter, fiscal_year
            )
            if report_context is None:
                return EarningsAnalysisResult(
                    symbol=symbol,
                    company_name=company_name,
                    error="无法确定有效的季度财报期",
                )

            quarter_data = report_context["quarter_data"]
            quarter = report_context["quarter"]
            fiscal_year = report_context["fiscal_year"]
            fiscal_period = report_context["fiscal_period"]
            report_date = report_context["report_date"]
            as_of = report_context["as_of"]

            # 构建分析结果
            return EarningsAnalysisResult(
                symbol=symbol,
                company_name=company_name,
                quarter=quarter,
                fiscal_year=fiscal_year,
                fiscal_period=fiscal_period,
                report_date=report_date,
                as_of=as_of,
                earnings_summary=self._build_earnings_summary(info, quarter_data),
                beat_miss_analysis=self._analyze_beat_miss(),
                segment_performance=self._analyze_segments(info, quarter_data),
                guidance=self._analyze_guidance(info),
                key_metrics=self._extract_key_metrics(info, dividend_metrics),
                trends=self._analyze_trends(financials),
                sources=self._collect_sources(
                    symbol, quarter, fiscal_year, report_date
                ),
            )

        except Exception as e:
            return EarningsAnalysisResult(
                symbol=symbol, error=f"季报分析异常: {str(e)}"
            )

    def _get_financials(self, stock) -> Dict:
        """获取历史财务数据"""
        financials = {
            "quarterly_income": None,
            "quarterly_balance_sheet": None,
            "quarterly_cashflow": None,
            "income": None,
            "balance_sheet": None,
            "cashflow": None,
            "earnings_dates": None,
        }

        try:
            financials["quarterly_income"] = stock.quarterly_income_stmt
        except Exception:
            pass

        try:
            financials["quarterly_balance_sheet"] = stock.quarterly_balance_sheet
        except Exception:
            pass

        try:
            financials["quarterly_cashflow"] = stock.quarterly_cashflow
        except Exception:
            pass

        try:
            financials["income"] = stock.income_stmt
        except Exception:
            pass

        try:
            financials["balance_sheet"] = stock.balance_sheet
        except Exception:
            pass

        try:
            financials["cashflow"] = stock.cashflow
        except Exception:
            pass

        try:
            financials["earnings_dates"] = stock.earnings_dates
        except Exception:
            pass

        return financials

    def _resolve_reporting_period(
        self,
        financials: Dict,
        requested_quarter: Optional[str],
        requested_fiscal_year: Optional[int],
    ) -> Optional[Dict[str, Any]]:
        """基于季度报表列确定财报期，避免按当前月份猜季度。"""
        income = financials.get("quarterly_income")
        if income is None or income.empty:
            return None

        columns = [col for col in income.columns if isinstance(col, pd.Timestamp)]
        if not columns:
            columns = list(income.columns)
        if not columns:
            return None

        fiscal_year_end = self._get_fiscal_year_end(financials.get("income"))

        target_column = None
        target_quarter = None
        target_year = None

        for col in columns:
            quarter, fiscal_year = self._derive_fiscal_period(col, fiscal_year_end)
            if requested_quarter and quarter != requested_quarter:
                continue
            if requested_fiscal_year and fiscal_year != requested_fiscal_year:
                continue
            target_column = col
            target_quarter = quarter
            target_year = fiscal_year
            break

        if target_column is None:
            if requested_quarter or requested_fiscal_year:
                return None
            target_column = columns[0]
            target_quarter, target_year = self._derive_fiscal_period(
                target_column, fiscal_year_end
            )

        report_date = self._find_report_date(
            financials.get("earnings_dates"), target_column
        )
        quarter_data = self._extract_quarter_data(financials, target_column)

        return {
            "quarter": target_quarter or requested_quarter or "Q?",
            "fiscal_year": target_year or requested_fiscal_year or 0,
            "fiscal_period": f"{target_quarter or requested_quarter or 'Q?'} FY{target_year or requested_fiscal_year or 0}",
            "report_date": report_date,
            "as_of": report_date or self._format_timestamp(target_column),
            "quarter_data": quarter_data,
        }

    def _get_fiscal_year_end(
        self, annual_income: Optional[pd.DataFrame]
    ) -> Optional[pd.Timestamp]:
        if annual_income is None or annual_income.empty:
            return None
        first_col = annual_income.columns[0]
        return first_col if isinstance(first_col, pd.Timestamp) else None

    def _derive_fiscal_period(
        self,
        period_end: Any,
        fiscal_year_end: Optional[pd.Timestamp],
    ) -> tuple[Optional[str], Optional[int]]:
        if not isinstance(period_end, pd.Timestamp):
            return None, None

        fy_end_month = fiscal_year_end.month if fiscal_year_end is not None else 12
        delta_months = (fy_end_month - period_end.month) % 12
        quarter_number = 4 - (delta_months // 3)
        if quarter_number < 1 or quarter_number > 4:
            quarter_number = ((period_end.month - 1) // 3) + 1

        fiscal_year = (
            period_end.year if period_end.month <= fy_end_month else period_end.year + 1
        )
        return f"Q{quarter_number}", fiscal_year

    def _find_report_date(
        self,
        earnings_dates: Optional[pd.DataFrame],
        target_column: Any,
    ) -> Optional[str]:
        """尽量从 earnings_dates 找到接近该财报期的披露日期。"""
        if (
            earnings_dates is None
            or earnings_dates.empty
            or not isinstance(target_column, pd.Timestamp)
        ):
            return self._format_timestamp(target_column)

        try:
            index_values = earnings_dates.index
            if len(index_values) == 0:
                return self._format_timestamp(target_column)
            nearest = min(index_values, key=lambda idx: abs((idx - target_column).days))
            return self._format_timestamp(nearest)
        except Exception:
            return self._format_timestamp(target_column)

    def _extract_quarter_data(
        self, financials: Dict, target_column: Any
    ) -> Dict[str, float]:
        """从季度三表抽取核心季度字段。"""
        income = financials.get("quarterly_income")
        balance_sheet = financials.get("quarterly_balance_sheet")
        cashflow = financials.get("quarterly_cashflow")

        revenue = self._get_statement_value(
            income, target_column, ["Total Revenue", "Operating Revenue"]
        )
        net_income = self._get_statement_value(
            income,
            target_column,
            [
                "Net Income",
                "Net Income Common Stockholders",
                "Net Income Including Noncontrolling Interests",
            ],
        )
        ebitda = self._get_statement_value(income, target_column, ["EBITDA"])
        basic_eps = self._get_statement_value(
            income,
            target_column,
            ["Diluted EPS", "Basic EPS", "Reported EPS"],
        )
        operating_cash_flow = self._get_statement_value(
            cashflow,
            target_column,
            ["Operating Cash Flow", "Cash Flow From Continuing Operating Activities"],
        )
        capex = self._get_statement_value(
            cashflow,
            target_column,
            ["Capital Expenditure", "Capital Expenditures"],
        )
        free_cash_flow = None
        if operating_cash_flow is not None:
            free_cash_flow = operating_cash_flow - abs(capex or 0.0)

        cash = self._get_statement_value(
            balance_sheet,
            target_column,
            [
                "Cash And Cash Equivalents",
                "Cash Cash Equivalents And Short Term Investments",
                "Cash",
            ],
        )
        total_debt = self._get_statement_value(
            balance_sheet,
            target_column,
            [
                "Total Debt",
                "Current Debt And Capital Lease Obligation",
                "Long Term Debt And Capital Lease Obligation",
            ],
        )

        return {
            "revenue": revenue or 0.0,
            "net_income": net_income or 0.0,
            "ebitda": ebitda or 0.0,
            "eps": basic_eps or 0.0,
            "operating_cash_flow": operating_cash_flow or 0.0,
            "capex": capex or 0.0,
            "free_cash_flow": free_cash_flow or 0.0,
            "cash": cash or 0.0,
            "total_debt": total_debt or 0.0,
        }

    def _get_statement_value(
        self,
        statement: Optional[pd.DataFrame],
        column: Any,
        candidates: List[str],
    ) -> Optional[float]:
        if statement is None or statement.empty or column not in statement.columns:
            return None

        normalized = {self._normalize_label(idx): idx for idx in statement.index}
        for candidate in candidates:
            row_key = normalized.get(self._normalize_label(candidate))
            if row_key is None:
                continue
            value = statement.at[row_key, column]
            if pd.isna(value):
                continue
            return float(value)
        return None

    def _normalize_label(self, value: Any) -> str:
        return str(value).strip().lower().replace("_", " ")

    def _format_timestamp(self, value: Any) -> Optional[str]:
        if isinstance(value, pd.Timestamp):
            return value.date().isoformat()
        if isinstance(value, datetime):
            return value.date().isoformat()
        if value is not None:
            return str(value)
        return None

    def _build_earnings_summary(
        self, info: Dict, quarter_data: Dict[str, float]
    ) -> Dict:
        """构建季度财报摘要，季度值必须来自季度报表。"""
        revenue = quarter_data.get("revenue", 0) / 1e9
        net_income = quarter_data.get("net_income", 0) / 1e9
        ebitda = quarter_data.get("ebitda", 0) / 1e9
        eps = quarter_data.get("eps", 0)
        net_margin = (
            (quarter_data.get("net_income", 0) / quarter_data.get("revenue", 1))
            if quarter_data.get("revenue", 0) > 0
            else None
        )
        ebitda_margin = (
            (quarter_data.get("ebitda", 0) / quarter_data.get("revenue", 1))
            if quarter_data.get("revenue", 0) > 0
            else None
        )

        return {
            "revenue": {
                "actual": f"${revenue:.2f}B" if revenue > 0 else "N/A",
                "yoy_change": self._calculate_yoy_change(info.get("revenueGrowth", 0)),
            },
            "net_income": {
                "actual": f"${net_income:.2f}B" if net_income > 0 else "N/A",
                "margin": (
                    f"{net_margin * 100:.1f}%" if net_margin is not None else "N/A"
                ),
            },
            "ebitda": {
                "actual": f"${ebitda:.2f}B" if ebitda > 0 else "N/A",
                "margin": (
                    f"{ebitda_margin * 100:.1f}%"
                    if ebitda_margin is not None
                    else "N/A"
                ),
            },
            "earnings_per_share": {
                "eps": f"${eps:.2f}" if eps else "N/A",
                "forward_eps": (
                    f"${info.get('forwardEPS', 0):.2f}"
                    if info.get("forwardEPS")
                    else "N/A"
                ),
            },
        }

    def _calculate_yoy_change(self, growth_rate: float) -> str:
        """计算同比变化"""
        if growth_rate is None or growth_rate == 0:
            return "N/A"
        direction = "+" if growth_rate > 0 else ""
        return f"{direction}{growth_rate * 100:.1f}% YoY"

    def _analyze_beat_miss(self) -> Dict:
        """缺少可靠季度 consensus 时明确降级，而不是伪造 beat/miss。"""
        return {
            "status": "unavailable",
            "summary": "缺少可验证的季度 consensus 数据，未输出 beat/miss 结论",
            "earnings": {
                "status": "unavailable",
                "variance": "N/A",
                "consensus": "N/A",
                "actual": "N/A",
            },
            "revenue": {
                "status": "unavailable",
                "variance": "N/A",
                "consensus": "N/A",
                "actual": "N/A",
            },
        }

    def _generate_beat_miss_summary(
        self, earnings_status: str, revenue_status: str
    ) -> str:
        """生成 beat/miss 总结"""
        if earnings_status == "Beat Expected" and revenue_status in ["Beat", "In-Line"]:
            return "公司有望双 beat，业绩超预期"
        elif earnings_status == "Miss Expected" and revenue_status == "Miss":
            return "公司业绩可能双 miss，面临压力"
        elif earnings_status == "In-Line" and revenue_status == "In-Line":
            return "业绩符合预期"
        else:
            return f"盈利预期 {earnings_status}，收入预期 {revenue_status}"

    def _analyze_segments(
        self, info: Dict, quarter_data: Dict[str, float]
    ) -> List[Dict]:
        """分析各业务板块表现"""
        segments = []

        if quarter_data.get("revenue"):
            segments.append(
                {
                    "segment": "Quarter Total Revenue",
                    "revenue": quarter_data.get("revenue", 0) / 1e9,
                    "growth": (info.get("revenueGrowth") or 0) * 100,
                    "note": "Quarterly filing aggregate",
                }
            )

        if info.get("sector"):
            segments.append(
                {
                    "segment": info.get("sector"),
                    "revenue": quarter_data.get("revenue", 0) / 1e9,
                    "note": "Primary segment (sector-level)",
                }
            )

        return segments

    def _analyze_guidance(self, info: Dict) -> Dict:
        """分析指引更新"""
        # 从 info 获取指引数据
        forward_eps = info.get("forwardEPS", 0)
        target_price = info.get("targetMeanPrice", 0)
        low_price = info.get("targetLowPrice", 0)
        high_price = info.get("targetHighPrice", 0)

        # PEG 比率
        peg = info.get("pegRatio", 0)

        guidance: Dict[str, Any] = {
            "eps_guidance": {
                "forward_eps": f"${forward_eps:.2f}" if forward_eps else "N/A",
                "trailing_eps": (
                    f"${info.get('trailingEPS', 0):.2f}"
                    if info.get("trailingEPS")
                    else "N/A"
                ),
            },
            "price_target": {
                "mean": f"${target_price:.0f}" if target_price else "N/A",
                "low": f"${low_price:.0f}" if low_price else "N/A",
                "high": f"${high_price:.0f}" if high_price else "N/A",
                "upside": (
                    f"{((target_price / info.get('currentPrice', 1)) - 1) * 100:.1f}%"
                    if target_price and info.get("currentPrice")
                    else "N/A"
                ),
            },
            "valuation": {
                "peg_ratio": f"{peg:.2f}x" if peg else "N/A",
                "beta": f"{info.get('beta', 1):.2f}",
            },
        }

        # 指引方向判断
        trailing_eps = info.get("trailingEPS")
        if forward_eps and trailing_eps:
            if forward_eps > trailing_eps * 1.1:
                guidance["direction"] = "Raising"
            elif forward_eps < trailing_eps * 0.9:
                guidance["direction"] = "Lowering"
            else:
                guidance["direction"] = "Maintaining"
        else:
            guidance["direction"] = "Unknown"

        return guidance

    def _extract_key_metrics(self, info: Dict, dividend_metrics: Dict[str, Any]) -> Dict:
        """提取关键指标"""
        return {
            "profitability": {
                "gross_margin": f"{(info.get('grossMargins') or 0) * 100:.1f}%",
                "operating_margin": f"{(info.get('operatingMargins') or 0) * 100:.1f}%",
                "net_margin": f"{(info.get('profitMargins') or 0) * 100:.1f}%",
                "ebitda_margin": f"{(info.get('ebitdaMargins') or 0) * 100:.1f}%",
            },
            "efficiency": {
                "roe": f"{(info.get('returnOnEquity') or 0) * 100:.1f}%",
                "roa": f"{(info.get('returnOnAssets') or 0) * 100:.1f}%",
            },
            "liquidity": {
                "current_ratio": f"{info.get('currentRatio') or 0:.2f}",
                "quick_ratio": f"{info.get('quickRatio') or 0:.2f}",
                "debt_to_equity": f"{info.get('debtToEquity') or 0:.1f}",
            },
            "growth": {
                "revenue_growth": f"{(info.get('revenueGrowth') or 0) * 100:.1f}%",
                "earnings_growth": f"{(info.get('earningsGrowth') or 0) * 100:.1f}%",
                "revenue_quarterly_growth": f"{(info.get('revenueQuarterlyGrowth') or 0) * 100:.1f}%",
            },
            "dividends": {
                "dividend_yield": dividend_metrics.get("dividend_yield", "N/A"),
                "dividend_yield_source": dividend_metrics.get("source", "unavailable"),
                "payout_ratio": f"{(info.get('payoutRatio') or 0) * 100:.1f}%",
            },
        }

    def _extract_dividend_metrics(self, stock: Any, info: Dict[str, Any]) -> Dict[str, Any]:
        price = info.get("currentPrice") or info.get("regularMarketPrice")
        try:
            dividends = stock.dividends
        except Exception:
            dividends = None
        dividend_yield = compute_trailing_dividend_yield(dividends, price)
        if dividend_yield is None:
            return {
                "dividend_yield": "N/A",
                "source": "unavailable",
            }
        return {
            "dividend_yield": format_ratio_as_percent(dividend_yield, decimals=2),
            "source": "yfinance.dividends+market_price",
            "value": dividend_yield,
        }

    def _normalize_ratio(self, value: Any) -> float:
        if value is None:
            return 0.0
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return 0.0
        if 0 < abs(numeric) <= 0.1:
            return numeric / 100.0
        return numeric / 100.0 if numeric > 1 else numeric

    def _analyze_trends(self, financials: Dict) -> Dict:
        """分析趋势"""
        trends = {}

        # 尝试从 income statement 获取历史数据
        try:
            income = financials.get("quarterly_income")
            if income is None or income.empty:
                income = financials.get("income")

            if income is not None and not income.empty:

                # 获取最近几年的数据
                revenue_row = self._find_row_name(
                    income, ["Total Revenue", "Operating Revenue"]
                )
                if revenue_row is not None:
                    revenues = income.loc[revenue_row].head(5)
                    trends["revenue_history"] = [
                        {
                            "year": str(col)[:4],
                            "value": val / 1e9 if val else 0,
                        }
                        for col, val in revenues.items()
                    ]

                net_income_row = self._find_row_name(
                    income,
                    ["Net Income", "Net Income Common Stockholders"],
                )
                if net_income_row is not None:
                    net_incomes = income.loc[net_income_row].head(5)
                    trends["net_income_history"] = [
                        {
                            "year": str(col)[:4],
                            "value": val / 1e9 if val else 0,
                        }
                        for col, val in net_incomes.items()
                    ]
        except Exception:
            pass

        return trends

    def _find_row_name(
        self, frame: pd.DataFrame, candidates: List[str]
    ) -> Optional[Any]:
        normalized = {self._normalize_label(idx): idx for idx in frame.index}
        for candidate in candidates:
            row_name = normalized.get(self._normalize_label(candidate))
            if row_name is not None:
                return row_name
        return None

    def _collect_sources(
        self,
        symbol: str,
        quarter: Optional[str],
        fiscal_year: Optional[int],
        report_date: Optional[str],
    ) -> List[str]:
        """收集数据来源"""
        sources = [
            f"yfinance - {symbol} quarterly financial statements",
            f"Company investor relations - {quarter} {fiscal_year or 'latest'} earnings ({report_date or 'date unavailable'})",
            "SEC EDGAR - Company filings",
        ]

        return sources
