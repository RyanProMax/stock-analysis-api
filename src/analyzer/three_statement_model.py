# -*- coding: utf-8 -*-
"""
3-Statement Model 分析器

完整的财务三表模型，包含:
- Income Statement 预测
- Balance Sheet 预测
- Cash Flow Statement 预测
- 三大表勾稽验证
- 情景分析 (Bull/Base/Bear)

勾稽关系:
1. BS 平衡: Assets = Liabilities + Equity
2. 现金勾稽: CF Ending Cash = BS Cash
3. RE 滚动: Ending RE = Prior RE + Net Income - Dividends
4. NI 勾稽: CF Net Income = IS Net Income
"""

import yfinance as yf
from typing import List, Dict, Any, Tuple

from ..model.lbo import ThreeStatementResult


class ThreeStatementModel:
    """
    三表财务模型

    基于公司历史财务数据，预测未来5年的三表联动模型
    严格遵循三表勾稽关系
    """

    DEFAULT_PROJECTION_YEARS = 5
    DEFAULT_TAX_RATE = 0.25
    DEFAULT_DIVIDEND_PAYOUT_RATIO = 0.30  # 股息支付率

    # 情景参数
    SCENARIOS = {
        "bull": {
            "revenue_growth": 0.15,
            "ebitda_margin": 0.25,
            "capex_pct": 0.03,
        },
        "base": {
            "revenue_growth": 0.08,
            "ebitda_margin": 0.20,
            "capex_pct": 0.04,
        },
        "bear": {
            "revenue_growth": 0.02,
            "ebitda_margin": 0.15,
            "capex_pct": 0.05,
        },
    }

    # 资产负债表假设 (占收入比例)
    WORKING_CAPITAL_ASSUMPTIONS = {
        "ar_pct": 0.15,  # 应收账款
        "inventory_pct": 0.10,  # 存货
        "ap_pct": 0.10,  # 应付账款
        "ppe_pct": 0.30,  # 固定资产
        "debt_to_assets": 0.20,  # 债务/总资产
    }

    def __init__(self, projection_years: int = DEFAULT_PROJECTION_YEARS):
        self.projection_years = projection_years

    def analyze(
        self,
        symbol: str,
        scenario: str = "base",
    ) -> ThreeStatementResult:
        """
        执行三表模型分析

        Args:
            symbol: 股票代码
            scenario: 情景 (bull/base/bear)

        Returns:
            ThreeStatementResult: 三表模型结果
        """
        try:
            # 获取股票数据
            stock = yf.Ticker(symbol)
            info = stock.info

            if not info:
                return ThreeStatementResult(
                    symbol=symbol,
                    error="无法获取股票数据",
                )

            # 基本信息
            company_name = info.get("longName", info.get("shortName", symbol))

            # 获取财务数据
            revenue = info.get("totalRevenue", 0) or 0
            total_assets = info.get("totalAssets", 0) or 0
            total_debt = info.get("totalDebt", 0) or 0
            total_equity = info.get("bookValue", 0) or 0
            cash = info.get("totalCash", 0) or 0

            if revenue <= 0:
                return ThreeStatementResult(
                    symbol=symbol,
                    company_name=company_name,
                    error="无法获取有效的财务数据",
                )

            # 转换单位 (百万)
            revenue = revenue / 1e6
            total_assets = total_assets / 1e6
            total_debt = total_debt / 1e6
            total_equity = total_equity / 1e6
            cash = cash / 1e6

            # 获取情景参数
            params = self.SCENARIOS.get(scenario, self.SCENARIOS["base"])

            # 生成三表预测 (按照正确的勾稽顺序)
            # 1. 先生成 IS
            income_statements = self._project_income_statement(revenue, params)

            # 2. 生成 CF 和 BS (需要联动确保勾稽)
            balance_sheets, cash_flows = self._project_bs_and_cf(
                income_statements,
                total_equity,
                cash,
                params,
            )

            # 验证勾稽
            checks = self._validate_linkages(
                income_statements, balance_sheets, cash_flows
            )

            # 关键指标
            key_metrics = self._calculate_key_metrics(income_statements, balance_sheets)

            return ThreeStatementResult(
                symbol=symbol,
                company_name=company_name,
                revenue_base=revenue,
                revenue_growth_rate=params["revenue_growth"],
                income_statements=income_statements,
                balance_sheets=balance_sheets,
                cash_flow_statements=cash_flows,
                key_metrics=key_metrics,
                assumptions={
                    "scenario": scenario,
                    "projection_years": self.projection_years,
                    "tax_rate": self.DEFAULT_TAX_RATE,
                    "dividend_payout_ratio": self.DEFAULT_DIVIDEND_PAYOUT_RATIO,
                    **params,
                    **self.WORKING_CAPITAL_ASSUMPTIONS,
                },
            )

        except Exception as e:
            return ThreeStatementResult(
                symbol=symbol, error=f"三表模型分析异常: {str(e)}"
            )

    def _project_income_statement(
        self,
        base_revenue: float,
        params: Dict,
    ) -> List[Dict[str, Any]]:
        """
        预测损益表

        收入增长驱动盈利预测
        """
        statements = []
        revenue = base_revenue

        for year in range(1, self.projection_years + 1):
            # 收入增长 (逐年递减，更现实)
            growth = params["revenue_growth"] * (1 - 0.1 * (year - 1))
            revenue = revenue * (1 + growth)

            # EBITDA
            ebitda_margin = params["ebitda_margin"]
            ebitda = revenue * ebitda_margin

            # D&A (占EBITDA 20%)
            da = ebitda * 0.20

            # EBIT
            ebit = ebitda - da

            # 利息 (将在债务计算后更新，这里先用占位)
            interest = 0

            # 税前利润
            ebt = ebit - interest

            # 税金 (注意：亏损时为0)
            taxes = max(ebt * self.DEFAULT_TAX_RATE, 0)

            # 净利润
            net_income = ebt - taxes

            # 利润率
            net_margin = net_income / revenue if revenue > 0 else 0

            statements.append(
                {
                    "year": year,
                    "revenue": round(revenue, 2),
                    "revenue_growth": round(growth * 100, 2),
                    "ebitda": round(ebitda, 2),
                    "ebitda_margin": round(ebitda_margin * 100, 2),
                    "ebit": round(ebit, 2),
                    "depreciation": round(da * 0.7, 2),
                    "amortization": round(da * 0.3, 2),
                    "da_total": round(da, 2),  # 保存完整的D&A用于CF计算
                    "interest": round(interest, 2),
                    "ebt": round(ebt, 2),
                    "taxes": round(taxes, 2),
                    "net_income": round(net_income, 2),
                    "net_margin": round(net_margin * 100, 2),
                }
            )

        return statements

    def _project_bs_and_cf(
        self,
        income_statements: List[Dict],
        initial_equity: float,
        initial_cash: float,
        params: Dict,
    ) -> Tuple[List[Dict], List[Dict]]:
        """
        联动预测资产负债表和现金流量表

        确保勾稽关系:
        1. BS Cash = CF Ending Cash
        2. RE (Equity) = Prior RE + NI - Dividends
        3. Assets = Liabilities + Equity
        """
        balance_sheets = []
        cash_flows = []

        # 期初值
        beginning_cash = initial_cash
        beginning_equity = initial_equity  # = Retained Earnings
        prev_ar = 0
        prev_inventory = 0
        prev_ap = 0
        prev_debt = initial_equity * self.WORKING_CAPITAL_ASSUMPTIONS["debt_to_assets"]

        for i, income in enumerate(income_statements):
            year = income["year"]
            revenue = income["revenue"]
            net_income = income["net_income"]
            da = income["da_total"]

            # ========== 资产负债表项目 (基于收入比例) ==========
            wc = self.WORKING_CAPITAL_ASSUMPTIONS

            # 流动资产
            ar = revenue * wc["ar_pct"]
            inventory = revenue * wc["inventory_pct"]

            # 非流动资产 (固定资产)
            ppe = revenue * wc["ppe_pct"]

            # 流动负债
            ap = revenue * wc["ap_pct"]

            # ========== 现金流量表 ==========
            # CFO: 净利润 + D&A - 营运资本变化
            cfo = net_income + da

            # 营运资本变化
            ar_change = ar - prev_ar
            inventory_change = inventory - prev_inventory
            ap_change = ap - prev_ap

            # NWC变化对现金流的影响
            # AR增加 = 现金减少 (负)
            # Inventory增加 = 现金减少 (负)
            # AP增加 = 现金增加 (正)
            nwc_impact = -ar_change - inventory_change + ap_change

            net_cfo = cfo + nwc_impact

            # CFI: CapEx (负现金流)
            capex = revenue * params["capex_pct"]
            net_cfi = -capex

            # CFF: 股息 (负现金流)
            dividend = net_income * self.DEFAULT_DIVIDEND_PAYOUT_RATIO
            net_cff = -dividend

            # 现金变化
            cash_change = net_cfo + net_cfi + net_cff

            # 期末现金 (这是BS的现金!)
            ending_cash = beginning_cash + cash_change

            # ========== 资产负债表 (确保平衡) ==========
            # 现金使用CF计算出的期末现金
            cash = ending_cash

            # 总资产 = 流动资产 + 固定资产
            current_assets = cash + ar + inventory
            total_assets = current_assets + ppe

            # 负债
            # 债务水平 - 简化假设：保持与资产的比例
            debt = total_assets * wc["debt_to_assets"]
            total_liabilities = ap + debt

            # 股东权益 (RE滚动)
            # Ending RE = Beginning RE + Net Income - Dividends
            ending_equity = beginning_equity + net_income - dividend

            # 验证 BS 平衡: Assets = Liabilities + Equity
            # 如果不平衡，使用 debt 作为 plug (债务调整)
            calculated_liabilities_plus_equity = total_liabilities + ending_equity
            balance_diff = total_assets - calculated_liabilities_plus_equity

            # 使用债务调整来平衡
            debt = debt + balance_diff
            total_liabilities = ap + debt

            # 重新验证
            final_balance_check = total_assets - (total_liabilities + ending_equity)

            # ========== 构建输出 ==========
            balance_sheets.append(
                {
                    "year": year,
                    "cash": round(cash, 2),
                    "accounts_receivable": round(ar, 2),
                    "inventory": round(inventory, 2),
                    "current_assets": round(current_assets, 2),
                    "ppe": round(ppe, 2),
                    "total_assets": round(total_assets, 2),
                    "accounts_payable": round(ap, 2),
                    "total_debt": round(debt, 2),
                    "total_liabilities": round(total_liabilities, 2),
                    "total_equity": round(ending_equity, 2),
                    "retained_earnings": round(ending_equity, 2),  # 简化：Equity = RE
                    "balance_check": round(final_balance_check, 4),
                }
            )

            cash_flows.append(
                {
                    "year": year,
                    "net_income": income["net_income"],
                    "add_depreciation": da,
                    "less_ar_increase": -ar_change,
                    "less_inventory_increase": -inventory_change,
                    "add_ap_increase": ap_change,
                    "nwc_change": round(nwc_impact, 2),
                    "operating_cash_flow": round(net_cfo, 2),
                    "capex": round(capex, 2),
                    "investing_cash_flow": round(net_cfi, 2),
                    "dividend": round(dividend, 2),
                    "financing_cash_flow": round(net_cff, 2),
                    "cash_change": round(cash_change, 2),
                    "beginning_cash": round(beginning_cash, 2),
                    "ending_cash": round(ending_cash, 2),
                }
            )

            # 更新期初值
            beginning_cash = ending_cash
            beginning_equity = ending_equity
            prev_ar = ar
            prev_inventory = inventory
            prev_ap = ap
            prev_debt = debt

        return balance_sheets, cash_flows

    def _validate_linkages(
        self,
        income_statements: List[Dict],
        balance_sheets: List[Dict],
        cash_flows: List[Dict],
    ) -> Dict[str, Any]:
        """
        验证三表勾稽关系

        检查项:
        1. BS 平衡: Assets = Liabilities + Equity
        2. 现金勾稽: CF Ending Cash = BS Cash
        3. RE 滚动: Ending RE = Prior RE + NI - Dividends
        4. NI 勾稽: CF Net Income = IS Net Income
        """
        checks = {
            "bs_balanced": True,
            "cash_ties": True,
            "ni_ties": True,
            "re_roll": True,
        }

        details = {
            "bs_check_values": [],
            "cash_diff_values": [],
            "ni_diff_values": [],
            "re_diff_values": [],
        }

        # 第一期的期初权益从 BS 第一期的权益回推
        if balance_sheets and income_statements and cash_flows:
            first_cf = cash_flows[0]
            first_income = income_statements[0]
            first_bs = balance_sheets[0]
            dividend = abs(first_cf["dividend"])
            # ending_equity = beginning_equity + NI - Div
            # => beginning_equity = ending_equity - NI + Div
            prev_equity = max(
                first_bs["total_equity"] - first_income["net_income"] + dividend, 0
            )
        else:
            prev_equity = 0

        for i, (income, bs, cf) in enumerate(
            zip(income_statements, balance_sheets, cash_flows)
        ):
            # 1. 资产负债表平衡检查
            bs_diff = abs(bs["balance_check"])
            details["bs_check_values"].append(round(bs_diff, 4))
            if bs_diff > 0.01:
                checks["bs_balanced"] = False

            # 2. 现金勾稽: CF ending cash = BS cash
            cash_diff = abs(cf["ending_cash"] - bs["cash"])
            details["cash_diff_values"].append(round(cash_diff, 4))
            if cash_diff > 0.01:
                checks["cash_ties"] = False

            # 3. 净利润勾稽: CF NI = IS NI
            ni_diff = abs(cf["net_income"] - income["net_income"])
            details["ni_diff_values"].append(round(ni_diff, 4))
            if ni_diff > 0.01:
                checks["ni_ties"] = False

            # 4. RE 滚动验证
            dividend = abs(cf["dividend"])  # CF 中 dividend 是负数
            expected_re = prev_equity + income["net_income"] - dividend
            re_diff = abs(bs["total_equity"] - expected_re)
            details["re_diff_values"].append(round(re_diff, 4))
            if re_diff > 0.01:
                checks["re_roll"] = False

            prev_equity = bs["total_equity"]

        return {
            "all_passed": all(checks.values()),
            **checks,
            "details": details,
        }

    def _calculate_key_metrics(
        self,
        income_statements: List[Dict],
        balance_sheets: List[Dict],
    ) -> Dict[str, Any]:
        """计算关键财务指标"""
        if not income_statements:
            return {}

        latest_income = income_statements[-1]
        latest_bs = balance_sheets[-1]

        # 盈利能力
        revenue = latest_income["revenue"]
        net_income = latest_income["net_income"]
        ebitda = latest_income["ebitda"]

        # 利润率
        net_margin = net_income / revenue if revenue > 0 else 0
        ebitda_margin = latest_income["ebitda_margin"] / 100

        # 杠杆
        debt = latest_bs["total_debt"]
        equity = latest_bs["total_equity"]
        assets = latest_bs["total_assets"]

        debt_to_equity = debt / equity if equity > 0 else 0
        debt_to_assets = debt / assets if assets > 0 else 0

        # 流动性
        cash = latest_bs["cash"]
        current_assets = latest_bs.get(
            "current_assets",
            cash + latest_bs["accounts_receivable"] + latest_bs["inventory"],
        )
        current_liabilities = latest_bs["accounts_payable"] + debt * 0.3
        current_ratio = (
            current_assets / current_liabilities if current_liabilities > 0 else 0
        )

        return {
            "revenue": round(revenue, 2),
            "net_income": round(net_income, 2),
            "ebitda": round(ebitda, 2),
            "net_margin": round(net_margin * 100, 2),
            "ebitda_margin": round(ebitda_margin * 100, 2),
            "debt_to_equity": round(debt_to_equity, 2),
            "debt_to_assets": round(debt_to_assets, 2),
            "current_ratio": round(current_ratio, 2),
        }
