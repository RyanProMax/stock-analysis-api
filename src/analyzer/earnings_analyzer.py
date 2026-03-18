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


class EarningsAnalysisResult:
    """季报分析结果"""

    def __init__(
        self,
        symbol: str,
        company_name: str = "",
        quarter: Optional[str] = "",
        fiscal_year: Optional[int] = None,
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

            # 获取历史财务数据
            financials = self._get_financials(stock)

            # 确定分析的季度
            if not quarter or not fiscal_year:
                quarter, fiscal_year = self._get_latest_quarter()

            # 确保 fiscal_year 是 int 类型
            fiscal_year = fiscal_year or 0

            # 构建分析结果
            return EarningsAnalysisResult(
                symbol=symbol,
                company_name=company_name,
                quarter=quarter,
                fiscal_year=fiscal_year,
                earnings_summary=self._build_earnings_summary(info, financials),
                beat_miss_analysis=self._analyze_beat_miss(info, financials),
                segment_performance=self._analyze_segments(info, financials),
                guidance=self._analyze_guidance(info),
                key_metrics=self._extract_key_metrics(info),
                trends=self._analyze_trends(financials),
                sources=self._collect_sources(symbol, quarter, fiscal_year),
            )

        except Exception as e:
            return EarningsAnalysisResult(
                symbol=symbol, error=f"季报分析异常: {str(e)}"
            )

    def _get_financials(self, stock) -> Dict:
        """获取历史财务数据"""
        financials = {
            "income": None,
            "balance_sheet": None,
            "cashflow": None,
        }

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

        return financials

    def _get_latest_quarter(self) -> tuple:
        """获取最新季度

        假设公司财年与日历年一致:
        - Q1: Jan-Mar ( earnings in Apr )
        - Q2: Apr-Jun ( earnings in Jul )
        - Q3: Jul-Sep ( earnings in Oct )
        - Q4: Oct-Dec ( earnings in Jan )
        """
        now = datetime.now()
        month = now.month

        # 当前季度判断 (基于财报发布时间)
        if month <= 4:  # Jan-Apr: Q4 上一年财报发布
            return "Q4", now.year - 1
        elif month <= 7:  # May-Jul: Q1 本年财报发布
            return "Q1", now.year
        elif month <= 10:  # Aug-Oct: Q2 本年财报发布
            return "Q2", now.year
        else:  # Nov-Dec: Q3 本年财报发布
            return "Q3", now.year

    def _build_earnings_summary(self, info: Dict, financials: Dict) -> Dict:
        """构建财报摘要"""
        # 从 info 获取最新数据
        revenue = info.get("totalRevenue", 0) / 1e9  # 转为十亿
        net_income = info.get("netIncomeToCommon", 0) / 1e9
        ebitda = info.get("ebitda", 0) / 1e9

        return {
            "revenue": {
                "actual": f"${revenue:.2f}B" if revenue > 0 else "N/A",
                "yoy_change": self._calculate_yoy_change(info.get("revenueGrowth", 0)),
            },
            "net_income": {
                "actual": f"${net_income:.2f}B" if net_income > 0 else "N/A",
                "margin": (
                    f"{info.get('profitMargins', 0) * 100:.1f}%"
                    if info.get("profitMargins")
                    else "N/A"
                ),
            },
            "ebitda": {
                "actual": f"${ebitda:.2f}B" if ebitda > 0 else "N/A",
                "margin": (
                    f"{info.get('ebitdaMargins', 0) * 100:.1f}%"
                    if info.get("ebitdaMargins")
                    else "N/A"
                ),
            },
            "earnings_per_share": {
                "eps": (
                    f"${info.get('trailingEPS', 0):.2f}"
                    if info.get("trailingEPS")
                    else "N/A"
                ),
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

    def _analyze_beat_miss(self, info: Dict, financials: Dict) -> Dict:
        """
        分析 Beat/Miss

        使用 yfinance 的 consensus estimates 与 actuals 进行比较
        - EPS: 使用 forwardEPS (共识预期) vs trailingEPS (实际)
        - Revenue: 使用 revenueEstimate (共识预期) vs totalRevenue (实际)
        """
        # EPS Beat/Miss: forwardEPS = consensus estimate, trailingEPS = actual
        consensus_eps = info.get("forwardEPS", 0) or info.get("epsForward", 0)
        actual_eps = info.get("trailingEPS", 0)

        if consensus_eps and actual_eps and actual_eps > 0:
            eps_variance = (consensus_eps - actual_eps) / abs(actual_eps)
            if eps_variance < -0.02:
                eps_status = "Beat"
                variance_str = f"+{abs(eps_variance) * 100:.1f}%"
            elif eps_variance > 0.02:
                eps_status = "Miss"
                variance_str = f"-{eps_variance * 100:.1f}%"
            else:
                eps_status = "In-Line"
                variance_str = "0.0%"
        else:
            eps_status = "N/A"
            variance_str = "N/A"

        # Revenue Beat/Miss: revenueEstimate = consensus, totalRevenue = actual
        revenue_estimate = info.get("revenueEstimate", 0) or info.get("revenueAvg", 0)
        revenue_actual = info.get("totalRevenue", 0)

        if revenue_estimate and revenue_actual and revenue_actual > 0:
            revenue_variance = (revenue_actual - revenue_estimate) / revenue_estimate
            if revenue_variance > 0.02:
                revenue_status = "Beat"
            elif revenue_variance < -0.02:
                revenue_status = "Miss"
            else:
                revenue_status = "In-Line"
            revenue_variance_str = f"{revenue_variance * 100:+.1f}%"
        else:
            revenue_status = "N/A"
            revenue_variance_str = "N/A"

        return {
            "earnings": {
                "status": eps_status,
                "variance": variance_str,
                "consensus": f"${consensus_eps:.2f}" if consensus_eps else "N/A",
                "actual": f"${actual_eps:.2f}" if actual_eps else "N/A",
            },
            "revenue": {
                "status": revenue_status,
                "variance": revenue_variance_str,
                "consensus": (
                    f"${revenue_estimate / 1e9:.2f}B" if revenue_estimate else "N/A"
                ),
                "actual": f"${revenue_actual / 1e9:.2f}B" if revenue_actual else "N/A",
            },
            "summary": self._generate_beat_miss_summary(eps_status, revenue_status),
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

    def _analyze_segments(self, info: Dict, financials: Dict) -> List[Dict]:
        """分析各业务板块表现

        优先从 quarterly financials 获取真实 segment 数据，
        fallback 到 info 中的 sector/industry 信息
        """
        segments = []

        # 尝试从 quarterly financials 获取真实 segment 数据
        try:
            if financials.get("income") is not None and not financials["income"].empty:
                income = financials["income"]
                # 查找 segment/revenue by segment 行
                for idx in income.index:
                    idx_lower = str(idx).lower()
                    if any(kw in idx_lower for kw in ["segment", "revenue by", "by segment", "geographic"]):
                        row = income.loc[idx]
                        for col, val in row.items():
                            if val and val > 0:
                                seg_name = str(idx).replace(" ", "_")[:30]
                                segments.append({
                                    "segment": seg_name,
                                    "revenue": round(val / 1e9, 2),
                                    "note": "From quarterly filing",
                                })
                        break
        except Exception:
            pass

        # 如果没有 quarterly segment 数据，使用总营收 + sector 信息
        if not segments and info.get("totalRevenue"):
            segments.append({
                "segment": "Total Revenue",
                "revenue": info.get("totalRevenue", 0) / 1e9,
                "growth": (info.get("revenueGrowth") or 0) * 100,
            })

        if info.get("sector"):
            segments.append({
                "segment": info.get("sector"),
                "revenue": info.get("totalRevenue", 0) / 1e9,
                "note": "Primary segment (sector-level)",
            })

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

    def _extract_key_metrics(self, info: Dict) -> Dict:
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
                "dividend_yield": f"{(info.get('dividendYield') or 0) * 100:.2f}%",
                "payout_ratio": f"{(info.get('payoutRatio') or 0) * 100:.1f}%",
            },
        }

    def _analyze_trends(self, financials: Dict) -> Dict:
        """分析趋势"""
        trends = {}

        # 尝试从 income statement 获取历史数据
        try:
            if financials.get("income") is not None and not financials["income"].empty:
                income = financials["income"]

                # 获取最近几年的数据
                if "totalRevenue" in income.index:
                    revenues = income.loc["totalRevenue"].head(5)
                    trends["revenue_history"] = [
                        {
                            "year": str(col)[:4],
                            "value": val / 1e9 if val else 0,
                        }
                        for col, val in revenues.items()
                    ]

                if "netIncome" in income.index:
                    net_incomes = income.loc["netIncome"].head(5)
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

    def _collect_sources(
        self,
        symbol: str,
        quarter: Optional[str],
        fiscal_year: Optional[int],
    ) -> List[str]:
        """收集数据来源"""
        sources = [
            f"yfinance - {symbol} financial data",
            f"Company investor relations - {quarter} {fiscal_year or 'latest'} earnings",
            "SEC EDGAR - Company filings",
        ]

        return sources
