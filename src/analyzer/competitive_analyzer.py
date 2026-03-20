# -*- coding: utf-8 -*-
"""
Competitive Analysis 分析器

竞争格局分析，包括:
- 市场概况
- 目标公司画像
- 竞争对手映射
- 定位可视化数据
- 竞品深度分析
- 比较分析
"""

import yfinance as yf
from typing import Dict, List, Any, Optional


class CompetitiveAnalysisResult:
    """竞争分析结果"""

    def __init__(
        self,
        symbol: str,
        company_name: str = "",
        target_metrics: Optional[Dict[str, Any]] = None,
        market_context: Optional[Dict[str, Any]] = None,
        target_profile: Optional[Dict[str, Any]] = None,
        competitors: Optional[List[Dict[str, Any]]] = None,
        positioning: Optional[Dict[str, Any]] = None,
        comparative: Optional[Dict[str, Any]] = None,
        moat_assessment: Optional[Dict[str, Any]] = None,
        industry_metrics: Optional[Dict[str, Any]] = None,
        scenario_analysis: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
    ):
        self.symbol = symbol
        self.company_name = company_name
        self.target_metrics = target_metrics or {}
        self.market_context = market_context or {}
        self.target_profile = target_profile or {}
        self.competitors = competitors or []
        self.positioning = positioning or {}
        self.comparative = comparative or {}
        self.moat_assessment = moat_assessment or {}
        self.industry_metrics = industry_metrics or {}
        self.scenario_analysis = scenario_analysis or {}
        self.error = error

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "company_name": self.company_name,
            "target_metrics": self.target_metrics,
            "market_context": self.market_context,
            "target_profile": self.target_profile,
            "competitors": self.competitors,
            "positioning": self.positioning,
            "comparative": self.comparative,
            "moat_assessment": self.moat_assessment,
            "industry_metrics": self.industry_metrics,
            "scenario_analysis": self.scenario_analysis,
            "error": self.error,
        }


class CompetitiveAnalyzer:
    """
    竞争格局分析器

    基于公司财务数据和市场信息生成竞争分析报告
    """

    # 行业关键指标映射
    INDUSTRY_METRICS = {
        "technology": ["revenue", "growth", "margin", "r_and_d"],
        "saas": ["arr", "nrr", "cac_payback", "ltv_cac", "rule_of_40"],
        "payments": ["gpv", "take_rate", "attach_rate", "margin"],
        "marketplace": ["gmv", "take_rate", "repeat_rate"],
        "retail": ["same_store_sales", "inventory_turns", "sales_per_sqft"],
        "logistics": ["volume", "cost_per_unit", "utilization"],
    }

    def __init__(self):
        pass

    def analyze(
        self,
        symbol: str,
        competitors: Optional[List[str]] = None,
        industry: str = "technology",
    ) -> CompetitiveAnalysisResult:
        """
        执行竞争分析

        Args:
            symbol: 目标公司代码
            competitors: 竞争对手列表 (可选)
            industry: 行业类型

        Returns:
            CompetitiveAnalysisResult: 竞争分析结果
        """
        try:
            # 获取目标公司数据
            target_info = self._get_company_info(symbol)
            if not target_info:
                return CompetitiveAnalysisResult(
                    symbol=symbol,
                    error=f"无法获取 {symbol} 的数据",
                )

            company_name = target_info.get("longName", symbol)

            # 如果没有指定竞争对手，自动识别
            if not competitors:
                competitors = self._find_competitors(symbol, industry)

            # 获取竞争对手数据
            competitor_profiles = []
            competitor_metrics = []
            for comp in competitors:
                comp_info = self._get_company_info(comp)
                if comp_info:
                    competitor_metrics.append(comp_info)
                    competitor_profiles.append(self._format_competitor(comp_info))

            # 构建竞争分析
            return CompetitiveAnalysisResult(
                symbol=symbol,
                company_name=company_name,
                target_metrics=target_info,
                market_context=self._analyze_market_context(target_info, industry),
                target_profile=self._format_target_profile(target_info),
                competitors=competitor_profiles,
                positioning=self._generate_positioning(
                    target_info, competitor_metrics, industry
                ),
                comparative=self._generate_comparative(
                    target_info, competitor_metrics, industry
                ),
                moat_assessment=self._assess_moat(target_info, competitor_metrics),
                industry_metrics=self._calculate_industry_metrics(target_info, competitor_metrics, industry),
                scenario_analysis=self._analyze_scenarios(target_info, competitor_metrics),
            )

        except Exception as e:
            return CompetitiveAnalysisResult(
                symbol=symbol, error=f"竞争分析异常: {str(e)}"
            )

    def _get_company_info(self, symbol: str) -> Optional[Dict[str, Any]]:
        """获取公司信息"""
        try:
            stock = yf.Ticker(symbol)
            info = stock.info

            if not info:
                return None

            return {
                "symbol": symbol,
                "longName": info.get("longName", info.get("shortName", symbol)),
                "sector": info.get("sector", "Unknown"),
                "industry": info.get("industry", "Unknown"),
                "marketCap": info.get("marketCap", 0),
                "revenue": info.get("totalRevenue", 0),
                "revenueGrowth": info.get("revenueGrowth", 0),
                "grossMargins": info.get("grossMargins", 0),
                "ebitdaMargins": info.get("ebitdaMargins", 0),
                "operatingMargins": info.get("operatingMargins", 0),
                "profitMargins": info.get("profitMargins", 0),
                "peRatio": info.get("trailingPE", 0),
                "forwardPE": info.get("forwardPE", 0),
                "pegRatio": info.get("pegRatio", 0),
                "priceToBook": info.get("priceToBook", 0),
                "priceToSales": info.get("priceToSalesTrailing12Months", 0),
                "beta": info.get("beta", 1),
                "52wHigh": info.get("fiftyTwoWeekHigh", 0),
                "52wLow": info.get("fiftyTwoWeekLow", 0),
                "currentPrice": info.get("currentPrice", 0),
                "targetMeanPrice": info.get("targetMeanPrice", 0),
                "recommendationKey": info.get("recommendationKey", "none"),
                "numberOfAnalystOpinions": info.get("numberOfAnalystOpinions", 0),
            }
        except Exception:
            return None

    def _find_competitors(self, symbol: str, industry: str) -> List[str]:  # type: ignore[empty-body]
        """
        查找竞争对手

        基于行业自动识别竞争对手
        """
        # 常见科技公司竞争对手映射
        competitor_map = {
            "NVDA": ["AMD", "INTC", "AVGO", "QCOM"],
            "AAPL": ["GOOGL", "MSFT", "AMZN", "META"],
            "MSFT": ["GOOGL", "AAPL", "AMZN", "META"],
            "GOOGL": ["MSFT", "AAPL", "AMZN", "META"],
            "AMZN": ["WMT", "TGT", "COST", "HD"],
            "TSLA": ["F", "GM", "RIVN", "LCID"],
            "META": ["SNAP", "PINS", "TWTR", "GOOGL"],
            "AMD": ["INTC", "NVDA", "AVGO", "QCOM"],
            "NFLX": ["DIS", "WBD", "PARA", "CMCSA"],
        }

        return competitor_map.get(symbol.upper(), [])

    def _format_target_profile(self, info: Dict[str, Any]) -> Dict[str, Any]:
        """格式化目标公司画像"""
        revenue = info.get("revenue", 0) / 1e9  # 转为十亿

        return {
            "company_name": info.get("longName", info.get("symbol")),
            "sector": info.get("sector"),
            "industry": info.get("industry"),
            "overview": {
                "market_cap": self._format_market_cap(info.get("marketCap", 0)),
                "revenue": f"${revenue:.1f}B" if revenue > 0 else "N/A",
                "growth": (
                    f"{info.get('revenueGrowth', 0) * 100:.1f}% YoY"
                    if info.get("revenueGrowth")
                    else "N/A"
                ),
            },
            "financials": {
                "gross_margin": f"{info.get('grossMargins', 0) * 100:.1f}%",
                "ebitda_margin": f"{info.get('ebitdaMargins', 0) * 100:.1f}%",
                "operating_margin": f"{info.get('operatingMargins', 0) * 100:.1f}%",
                "net_margin": f"{info.get('profitMargins', 0) * 100:.1f}%",
            },
            "valuation": {
                "pe_ratio": f"{info.get('peRatio', 0):.1f}x",
                "forward_pe": f"{info.get('forwardPE', 0):.1f}x",
                "peg_ratio": f"{info.get('pegRatio', 0):.1f}x",
                "price_to_book": f"{info.get('priceToBook', 0):.1f}x",
                "price_to_sales": f"{info.get('priceToSales', 0):.1f}x",
            },
            "analyst_consensus": {
                "rating": info.get("recommendationKey", "none"),
                "price_target": (
                    f"${info.get('targetMeanPrice', 0):.0f}"
                    if info.get("targetMeanPrice")
                    else "N/A"
                ),
                "analyst_count": info.get("numberOfAnalystOpinions", 0),
            },
        }

    def _format_competitor(self, info: Dict[str, Any]) -> Dict[str, Any]:
        """格式化竞争对手数据"""
        revenue = info.get("revenue", 0) / 1e9

        return {
            "symbol": info.get("symbol"),
            "name": info.get("longName", info.get("symbol")),
            "sector": info.get("sector"),
            "overview": {
                "market_cap": self._format_market_cap(info.get("marketCap", 0)),
                "revenue": f"${revenue:.1f}B" if revenue > 0 else "N/A",
                "growth": (
                    f"{info.get('revenueGrowth', 0) * 100:.1f}% YoY"
                    if info.get("revenueGrowth")
                    else "N/A"
                ),
            },
            "financials": {
                "gross_margin": f"{info.get('grossMargins', 0) * 100:.1f}%",
                "operating_margin": f"{info.get('operatingMargins', 0) * 100:.1f}%",
                "net_margin": f"{info.get('profitMargins', 0) * 100:.1f}%",
            },
            "valuation": {
                "pe_ratio": f"{info.get('peRatio', 0):.1f}x",
                "peg_ratio": f"{info.get('pegRatio', 0):.1f}x",
            },
        }

    def _analyze_market_context(self, info: Dict[str, Any], industry: str) -> Dict[str, Any]:
        """分析市场背景"""
        market_cap = info.get("marketCap", 0)

        # 估算市场份额 (简化模型)
        estimated_market_size = market_cap * 5  # 粗略估算

        return {
            "industry": industry,
            "estimated_market_context": {
                "value": f"${estimated_market_size / 1e9:.0f}B",
                "is_estimate": True,
                "methodology": "estimated as market_cap * 5 heuristic",
                "derived_from": "target company marketCap",
            },
            "key_metrics": self.INDUSTRY_METRICS.get(
                industry, ["revenue", "growth", "margin"]
            ),
            "market_position": self._get_market_position(market_cap),
        }

    def _get_market_position(self, market_cap: int) -> str:
        """判断市场地位"""
        if market_cap > 1e12:
            return "Mega Cap"
        elif market_cap > 200e9:
            return "Large Cap"
        elif market_cap > 10e9:
            return "Mid Cap"
        elif market_cap > 2e9:
            return "Small Cap"
        else:
            return "Micro Cap"

    def _generate_positioning(
        self, target: Dict[str, Any], competitors: List[Dict[str, Any]], industry: str
    ) -> Dict[str, Any]:
        """生成定位可视化数据"""
        if not competitors:
            return {}

        # 提取数据用于 2x2 矩阵
        companies = [{"name": target.get("symbol"), **target}] + competitors

        # 按市值和增长排序
        companies_sorted = sorted(
            companies, key=lambda x: x.get("marketCap", 0), reverse=True
        )

        # 生成 quadrant 数据
        quadrants = {
            "leaders": [],  # 高市值高增长
            "challengers": [],  # 低市值高增长
            "niche": [],  # 低市值低增长
            "underperformers": [],  # 高市值低增长
        }

        median_growth = sorted([c.get("revenueGrowth", 0) for c in companies])[
            len(companies) // 2
        ]
        median_mcap = sorted([c.get("marketCap", 0) for c in companies])[
            len(companies) // 2
        ]

        for c in companies_sorted:
            symbol = c.get("symbol")
            growth = c.get("revenueGrowth", 0)
            mcap = c.get("marketCap", 0)

            if mcap >= median_mcap and growth >= median_growth:
                quadrants["leaders"].append(symbol)
            elif mcap < median_mcap and growth >= median_growth:
                quadrants["challengers"].append(symbol)
            elif mcap < median_mcap and growth < median_growth:
                quadrants["niche"].append(symbol)
            else:
                quadrants["underperformers"].append(symbol)

        return {
            "matrix": {
                "x_axis": "Market Cap",
                "y_axis": "Revenue Growth",
                "quadrants": quadrants,
            },
            "data_points": [
                {
                    "symbol": c.get("symbol"),
                    "x": c.get("marketCap", 0) / 1e9,
                    "y": c.get("revenueGrowth", 0) * 100,
                    "size": c.get("revenue", 0) / 1e9,
                }
                for c in companies
            ],
        }

    def _generate_comparative(
        self, target: Dict[str, Any], competitors: List[Dict[str, Any]], industry: str
    ) -> Dict[str, Any]:
        """生成比较分析"""
        all_companies = [{"symbol": target.get("symbol"), **target}] + competitors

        # 构建比较表
        rows = []
        for c in all_companies:
            rows.append(
                {
                    "symbol": c.get("symbol"),
                    "name": c.get("longName", c.get("symbol")),
                    "market_cap": c.get("marketCap", 0) / 1e9,
                    "revenue": c.get("revenue", 0) / 1e9,
                    "growth": c.get("revenueGrowth", 0) * 100,
                    "gross_margin": c.get("grossMargins", 0) * 100,
                    "operating_margin": c.get("operatingMargins", 0) * 100,
                    "pe_ratio": c.get("peRatio", 0),
                }
            )

        # 计算分位数
        if len(rows) > 1:
            metrics = ["market_cap", "revenue", "growth", "gross_margin"]
            for metric in metrics:
                values = [r[metric] for r in rows if r[metric] > 0]
                if values:
                    values_sorted = sorted(values)
                    median = values_sorted[len(values_sorted) // 2]

                    for r in rows:
                        if r[metric] > median:
                            r[f"{metric}_rating"] = "high"
                        elif r[metric] > median * 0.5:
                            r[f"{metric}_rating"] = "medium"
                        else:
                            r[f"{metric}_rating"] = "low"

        return {"comparison_table": rows}

    def _assess_moat(self, target: Dict[str, Any], competitors: List[Dict[str, Any]]) -> Dict[str, Any]:
        """评估护城河"""
        # 基于财务指标简化评估
        gross_margin = target.get("grossMargins", 0)
        operating_margin = target.get("operatingMargins", 0)
        market_cap = target.get("marketCap", 0)
        beta = target.get("beta", 1)

        moat_scores = {
            "network_effects": self._score_network_effects(target),
            "switching_costs": self._score_switching_costs(target),
            "scale_economies": self._score_scale(market_cap, target.get("revenue", 0)),
            "intangible_assets": self._score_intangibles(
                gross_margin, operating_margin
            ),
        }

        # 总体评估
        avg_score = sum(moat_scores.values()) / len(moat_scores)

        return {
            "scores": moat_scores,
            "overall": (
                "Strong"
                if avg_score > 0.7
                else "Moderate" if avg_score > 0.4 else "Weak"
            ),
            "key_strengths": self._identify_strengths(moat_scores),
            "key_weaknesses": self._identify_weaknesses(moat_scores),
            "risk_factors": self._identify_risks(target, competitors),
        }

    def _score_network_effects(self, info: Dict[str, Any]) -> float:
        """评分网络效应"""
        # 简化：科技公司通常有网络效应
        sector = info.get("sector", "").lower()
        if "internet" in sector or "communication" in sector:
            return 0.8
        elif "technology" in sector:
            return 0.6
        return 0.4

    def _score_switching_costs(self, info: Dict[str, Any]) -> float:
        """评分转换成本"""
        # 简化：B2B 软件有高转换成本
        industry = info.get("industry", "").lower()
        if "software" in industry or "semiconductor" in industry:
            return 0.7
        return 0.5

    def _score_scale(self, market_cap: float, revenue: float) -> float:
        """评分规模经济"""
        if market_cap > 100e9:
            return 0.9
        elif market_cap > 10e9:
            return 0.7
        elif market_cap > 1e9:
            return 0.5
        return 0.3

    def _score_intangibles(self, gross_margin: float, operating_margin: float) -> float:
        """评分无形资产"""
        # 高利润率通常表示无形资产优势
        if gross_margin > 0.7:
            return 0.9
        elif gross_margin > 0.5:
            return 0.7
        elif gross_margin > 0.3:
            return 0.5
        return 0.3

    def _identify_strengths(self, scores: Dict[str, float]) -> List[str]:
        """识别优势"""
        strengths = []
        if scores.get("network_effects", 0) > 0.6:
            strengths.append("网络效应")
        if scores.get("switching_costs", 0) > 0.6:
            strengths.append("高转换成本")
        if scores.get("scale_economies", 0) > 0.6:
            strengths.append("规模优势")
        if scores.get("intangible_assets", 0) > 0.6:
            strengths.append("品牌/专利优势")
        return strengths or ["无明显护城河"]

    def _identify_weaknesses(self, scores: Dict[str, float]) -> List[str]:
        """识别劣势"""
        weaknesses = []
        if scores.get("network_effects", 0) < 0.4:
            weaknesses.append("缺乏网络效应")
        if scores.get("switching_costs", 0) < 0.4:
            weaknesses.append("低转换成本")
        if scores.get("scale_economies", 0) < 0.4:
            weaknesses.append("规模不足")
        if scores.get("intangible_assets", 0) < 0.4:
            weaknesses.append("利润率低于同行")
        return weaknesses or ["无明显劣势"]

    def _identify_risks(self, target: Dict[str, Any], competitors: List[Dict[str, Any]]) -> List[str]:
        """识别风险"""
        risks = []

        # 竞争风险
        if len(competitors) > 5:
            risks.append("多竞争对手挤压")

        # 估值风险
        if target.get("peRatio", 0) > 50:
            risks.append("估值偏高")

        # 增长风险
        if target.get("revenueGrowth", 0) < 0:
            risks.append("收入负增长")

        # 市场集中度风险
        if not competitors:
            risks.append("难以识别直接竞争对手")

        return risks or ["市场风险可控"]

    def _format_market_cap(self, market_cap: float) -> str:
        """格式化市值"""
        if market_cap >= 1e12:
            return f"${market_cap / 1e12:.2f}T"
        elif market_cap >= 1e9:
            return f"${market_cap / 1e9:.1f}B"
        elif market_cap >= 1e6:
            return f"${market_cap / 1e6:.1f}M"
        return "N/A"

    def _calculate_industry_metrics(
        self, target: Dict[str, Any], competitors: List[Dict[str, Any]], industry: str
    ) -> Dict[str, Any]:
        """
        计算行业特定指标

        参考 plugins 定义的行业关键指标:
        - SaaS: ARR, NRR, CAC payback, LTV/CAC, Rule of 40
        - Payments: GPV, take rate, attach rate, margin
        - Marketplaces: GMV, take rate, repeat rate
        - Retail: same store sales, inventory turns, sales per sqft
        - Logistics: volume, cost per unit, utilization
        """
        metrics: Dict[str, Any] = {"industry": industry}

        if industry == "saas":
            # SaaS 特有指标
            revenue = target.get("revenue", 0)
            growth = target.get("revenueGrowth", 0)
            margin = target.get("profitMargins", 0)
            rule_of_40 = (growth + margin) if growth and margin else 0
            metrics.update({
                "arr": f"${revenue / 1e9:.1f}B" if revenue > 0 else "N/A",
                "revenue_growth": f"{growth * 100:.1f}%" if growth else "N/A",
                "net_margin": f"{margin * 100:.1f}%" if margin else "N/A",
                "rule_of_40": f"{rule_of_40 * 100:.1f}%" if rule_of_40 else "N/A",
                "note": "ARR estimated as annual revenue; Rule of 40 = growth% + profit margin%",
            })
        elif industry == "payments":
            revenue = target.get("revenue", 0)
            gross_margin = target.get("grossMargins", 0)
            # take rate = revenue / GMV (GPV 需要额外数据源)
            metrics.update({
                "revenue": f"${revenue / 1e9:.1f}B" if revenue > 0 else "N/A",
                "gross_margin": f"{gross_margin * 100:.1f}%" if gross_margin else "N/A",
                "take_rate": "N/A (requires GPV data)",
                "note": "Take rate requires Gross Payment Volume from filings",
            })
        elif industry == "marketplace":
            revenue = target.get("revenue", 0)
            growth = target.get("revenueGrowth", 0)
            metrics.update({
                "revenue": f"${revenue / 1e9:.1f}B" if revenue > 0 else "N/A",
                "revenue_growth": f"{growth * 100:.1f}%" if growth else "N/A",
                "gmv": "N/A (requires GMV data)",
                "take_rate": "N/A",
                "note": "GMV requires marketplace-specific data from filings",
            })
        elif industry == "retail":
            revenue = target.get("revenue", 0)
            margin = target.get("grossMargins", 0)
            metrics.update({
                "revenue": f"${revenue / 1e9:.1f}B" if revenue > 0 else "N/A",
                "gross_margin": f"{margin * 100:.1f}%" if margin else "N/A",
                "same_store_sales": "N/A",
                "note": "Same-store sales requires historical store count data",
            })
        else:
            # technology / 默认
            revenue = target.get("revenue", 0)
            growth = target.get("revenueGrowth", 0)
            margin = target.get("grossMargins", 0)
            rd = target.get("rAndD", 0)
            metrics.update({
                "revenue": f"${revenue / 1e9:.1f}B" if revenue > 0 else "N/A",
                "revenue_growth": f"{growth * 100:.1f}%" if growth else "N/A",
                "gross_margin": f"{margin * 100:.1f}%" if margin else "N/A",
                "rd_spending": f"${rd / 1e9:.1f}B" if rd else "N/A",
            })

        return metrics

    def _analyze_scenarios(
        self, target: Dict[str, Any], competitors: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        场景分析 (Bull / Base / Bear)

        基于市场地位、增长预期和估值进行三场景分析
        """
        market_cap = target.get("marketCap", 0)
        revenue = target.get("revenue", 0)
        growth = target.get("revenueGrowth", 0)
        pe = target.get("peRatio", 0)
        current_price = target.get("currentPrice", 0)

        # 基于当前估值估算各场景目标价
        if current_price > 0 and pe > 0:
            # Bull: 估值扩张 (P/E +30%), 增长加速 (+50%)
            bull_pe = pe * 1.3
            bull_growth_adj = 1.5
            bull_target = (target.get("forwardEPS", current_price / pe) *
                           bull_pe * bull_growth_adj)
            # Base: 估值不变, 增长持平
            base_target = current_price * (1 + (growth or 0))
            # Bear: 估值压缩 (P/E -30%), 增长放缓 (-50%)
            bear_pe = pe * 0.7
            bear_target = (target.get("forwardEPS", current_price / pe) *
                           bear_pe * 0.5)
        else:
            bull_target = base_target = bear_target = 0

        upside = (bull_target / current_price - 1) if current_price > 0 else 0
        downside = (bear_target / current_price - 1) if current_price > 0 else 0

        return {
            "bull": {
                "target_price": f"${bull_target:.0f}" if bull_target > 0 else "N/A",
                "upside": f"+{upside * 100:.0f}%" if upside else "N/A",
                "drivers": "估值扩张 + 增长加速 + 市场份额提升",
                "probability": "20%",
            },
            "base": {
                "target_price": f"${base_target:.0f}" if base_target > 0 else "N/A",
                "upside": f"+{(base_target / current_price - 1) * 100:.0f}%" if current_price > 0 else "N/A",
                "drivers": "按预期增长，估值维持",
                "probability": "55%",
            },
            "bear": {
                "target_price": f"${bear_target:.0f}" if bear_target > 0 else "N/A",
                "downside": f"{downside * 100:.0f}%" if downside else "N/A",
                "drivers": "估值压缩 + 增长放缓 + 竞争加剧",
                "probability": "25%",
            },
        }
