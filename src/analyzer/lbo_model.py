# -*- coding: utf-8 -*-
"""
LBO (Leveraged Buyout) Model 分析器

基于机构级标准的 LBO 模型实现，包含:
- Sources & Uses 分析
- 运营模型
- 债务时间表
- 现金流分析
- IRR/MOIC 计算
"""

import yfinance as yf
from typing import List

from ..data_provider.fundamental_context import build_us_fundamental_context_from_info
from ..data_provider.sources.yfinance import YfinanceDataSource
from ..model.lbo import (
    LBOResult,
    SourcesAndUses,
    DebtScheduleRow,
    OperatingProjections,
    CashFlowItem,
    ReturnsAnalysis,
)


def _irr(cash_flows: List[float]) -> float:
    """
    计算内部收益率 (IRR)
    使用牛顿迭代法实现
    """
    max_iter = 1000
    tol = 1e-6
    guess = 0.1

    for _ in range(max_iter):
        npv = 0.0
        d_npv = 0.0
        for i, cf in enumerate(cash_flows):
            factor = (1 + guess) ** i
            npv += cf / factor
            d_npv -= i * cf / (factor * (1 + guess))

        if abs(d_npv) < tol:
            break
        new_guess = guess - npv / d_npv
        if abs(new_guess - guess) < tol:
            return new_guess
        guess = new_guess

    return guess


class LBOModel:
    """
    LBO 估值模型

    使用 yfinance 获取数据，构建完整的 LBO 模型
    """

    # 默认参数
    DEFAULT_HOLDING_PERIOD = 5  # 持有年限
    DEFAULT_ENTRY_MULTIPLE = 10.0  # 入场 EV/EBITDA 倍数
    DEFAULT_EXIT_MULTIPLE = 10.0  # 出场 EV/EBITDA 倍数
    DEFAULT_SENIOR_DEBT_PCT = 0.50  # 优先债务占比
    DEFAULT_SENIOR_DEBT_RATE = 0.08  # 优先债务利率
    DEFAULT_MEZZ_DEBT_PCT = 0.15  # 中层债务占比
    DEFAULT_MEZZ_DEBT_RATE = 0.12  # 中层债务利率
    DEFAULT_MIN_CASH = 10.0  # 最低现金余额 (百万)
    DEFAULT_REVENUE_GROWTH = 0.05  # 收入增长率
    DEFAULT_EBITDA_MARGIN = 0.20  # EBITDA 利润率
    DEFAULT_CAPEX_PCT = 0.03  # CapEx 占收入比

    def __init__(
        self,
        holding_period: int = DEFAULT_HOLDING_PERIOD,
        entry_multiple: float = DEFAULT_ENTRY_MULTIPLE,
        exit_multiple: float = DEFAULT_EXIT_MULTIPLE,
        senior_debt_pct: float = DEFAULT_SENIOR_DEBT_PCT,
        senior_debt_rate: float = DEFAULT_SENIOR_DEBT_RATE,
        mezz_debt_pct: float = DEFAULT_MEZZ_DEBT_PCT,
        mezz_debt_rate: float = DEFAULT_MEZZ_DEBT_RATE,
    ):
        self.holding_period = holding_period
        self.entry_multiple = entry_multiple
        self.exit_multiple = exit_multiple
        self.senior_debt_pct = senior_debt_pct
        self.senior_debt_rate = senior_debt_rate
        self.mezz_debt_pct = mezz_debt_pct
        self.mezz_debt_rate = mezz_debt_rate

    def analyze(self, symbol: str) -> LBOResult:
        """
        执行 LBO 分析

        Args:
            symbol: 股票代码

        Returns:
            LBOResult: LBO 分析结果
        """
        try:
            # 获取股票数据
            stock = yf.Ticker(symbol)
            info = stock.info

            if not info:
                return LBOResult(symbol=symbol, error="无法获取股票数据")

            # 基本信息
            company_name = info.get("longName", info.get("shortName", symbol))
            current_price = info.get("currentPrice", 0)
            normalized_fields = YfinanceDataSource._build_normalized_fields(stock, info)
            fundamental_context = build_us_fundamental_context_from_info(
                symbol=symbol,
                info=info,
                latest_price=current_price,
                as_of=None,
                normalized_fields=normalized_fields,
            )

            # 获取财务数据
            revenue = info.get("totalRevenue", 0) or 0
            ebitda = info.get("ebitda", 0) or 0

            if revenue <= 0 or ebitda <= 0:
                return LBOResult(
                    symbol=symbol,
                    company_name=company_name,
                    current_price=current_price,
                    error="无法获取有效的财务数据",
                )

            revenue = revenue / 1e6  # 转换为百万
            ebitda = ebitda / 1e6

            # 1. Sources & Uses
            sources_uses = self._calculate_sources_and_uses(ebitda)

            # 2. 运营预测
            operating = self._project_operating(revenue, ebitda)

            # 3. 债务时间表
            debt_schedule = self._calculate_debt_schedule(
                sources_uses.senior_debt,
                sources_uses.mezzanine_debt,
                operating,
            )

            # 4. 现金流
            cash_flows = self._calculate_cash_flows(operating, debt_schedule)

            # 5. 回报分析
            returns = self._calculate_returns(
                sources_uses.equity,
                operating,
                debt_schedule,
            )

            # 构建结果
            result = LBOResult(
                symbol=symbol,
                company_name=company_name,
                current_price=current_price,
                entry_enterprise_value=ebitda * self.entry_multiple,
                purchase_price=sources_uses.total_uses,
                equity_check=sources_uses.equity,
                leverage_multiple=(
                    sources_uses.total_debt / sources_uses.equity
                    if sources_uses.equity > 0
                    else 0
                ),
                sources_and_uses=sources_uses,
                operating_projections=operating,
                debt_schedule=debt_schedule,
                cash_flows=cash_flows,
                returns=returns,
                assumptions={
                    "holding_period": self.holding_period,
                    "entry_multiple": self.entry_multiple,
                    "exit_multiple": self.exit_multiple,
                    "senior_debt_pct": self.senior_debt_pct,
                    "senior_debt_rate": self.senior_debt_rate,
                    "mezz_debt_pct": self.mezz_debt_pct,
                    "mezz_debt_rate": self.mezz_debt_rate,
                },
                model_type="scenario",
                derived_from_assumptions=True,
                assumptions_source="entry_exit_multiples_leverage_and_margin_assumptions",
                fundamental_context=fundamental_context,
            )

            return result

        except Exception as e:
            return LBOResult(symbol=symbol, error=f"LBO 分析异常: {str(e)}")

    def _calculate_sources_and_uses(self, ltm_ebitda: float) -> SourcesAndUses:
        """计算资金来源与用途"""
        # 收购价格 = Entry Multiple × EBITDA
        purchase_price = ltm_ebitda * self.entry_multiple

        # 交易费用 (2%)
        transaction_fees = purchase_price * 0.02

        # 融资费用 (1%)
        financing_fees = purchase_price * 0.01

        # 总用途
        total_uses = purchase_price + transaction_fees + financing_fees

        # 债务融资
        total_debt = total_uses * (self.senior_debt_pct + self.mezz_debt_pct)
        senior_debt = total_uses * self.senior_debt_pct
        mezzanine_debt = total_uses * self.mezz_debt_pct

        # 股权融资 (剩余)
        equity = total_uses - total_debt

        return SourcesAndUses(
            purchase_price=purchase_price,
            financing_fees=financing_fees,
            transaction_fees=transaction_fees,
            total_uses=total_uses,
            senior_debt=senior_debt,
            subordinated_debt=0,
            mezzanine_debt=mezzanine_debt,
            total_debt=total_debt,
            equity=equity,
            total_sources=total_uses,
        )

    def _project_operating(
        self,
        base_revenue: float,
        base_ebitda: float,
    ) -> List[OperatingProjections]:
        """预测运营数据"""
        projections = []
        revenue = base_revenue
        ebitda_margin = (
            base_ebitda / base_revenue
            if base_revenue > 0
            else self.DEFAULT_EBITDA_MARGIN
        )

        # 增长率递减
        growth_rates = [
            self.DEFAULT_REVENUE_GROWTH * 1.2,
            self.DEFAULT_REVENUE_GROWTH * 1.0,
            self.DEFAULT_REVENUE_GROWTH * 0.8,
            self.DEFAULT_REVENUE_GROWTH * 0.6,
            self.DEFAULT_REVENUE_GROWTH * 0.4,
        ][: self.holding_period]

        for year in range(1, self.holding_period + 1):
            # 收入增长
            revenue_growth = growth_rates[year - 1]
            revenue = revenue * (1 + revenue_growth)

            # EBITDA (利润率逐步改善)
            margin = min(ebitda_margin * 1.05, 0.30)  # 最高30%
            ebitda = revenue * margin

            # EBIT (假设D&A占EBITDA的15%)
            da = ebitda * 0.15
            ebit = ebitda - da

            # 利息 (后续会由债务表更新)
            interest = 0

            # 税前利润
            ebt = ebit - interest

            # 税金 (25%税率)
            taxes = max(ebt * 0.25, 0)

            # 净利润
            net_income = ebt - taxes

            projections.append(
                OperatingProjections(
                    year=year,
                    revenue=revenue,
                    revenue_growth=revenue_growth,
                    ebitda=ebitda,
                    ebitda_margin=margin,
                    ebit=ebit,
                    depreciation=da * 0.7,  # 折旧占70%
                    amortization=da * 0.3,  # 摊销占30%
                    interest=interest,
                    ebt=ebt,
                    taxes=taxes,
                    net_income=net_income,
                )
            )

        return projections

    def _calculate_debt_schedule(
        self,
        initial_senior: float,
        initial_mezz: float,
        operating: List[OperatingProjections],
    ) -> List[DebtScheduleRow]:
        """计算债务时间表"""
        schedule = []

        senior_balance = initial_senior
        mezz_balance = initial_mezz

        for i, op in enumerate(operating):
            year = op.year

            # 期初余额
            beg_senior = senior_balance
            beg_mezz = mezz_balance

            # 利息
            senior_interest = beg_senior * self.senior_debt_rate
            mezz_interest = beg_mezz * self.mezz_debt_rate
            total_interest = senior_interest + mezz_interest

            # 可用于还款的现金流 (FCF)
            fcf = op.net_income + op.depreciation + op.amortization

            # 优先债务还款 (50% 的 FCF)
            senior_repayment = min(fcf * 0.5, beg_senior)
            senior_balance = max(beg_senior - senior_repayment, 0)

            # 中层债务还款 (剩余的 FCF)
            mezz_repayment = min((fcf - senior_repayment) * 0.5, beg_mezz)
            mezz_balance = max(beg_mezz - mezz_repayment, 0)

            # 期末余额
            end_senior = senior_balance
            end_mezz = mezz_balance

            # 更新运营数据的利息
            op.interest = total_interest

            # 重新计算 EBT 和 Net Income
            op.ebt = op.ebit - total_interest
            op.taxes = max(op.ebt * 0.25, 0)
            op.net_income = op.ebt - op.taxes

            schedule.append(
                DebtScheduleRow(
                    year=year,
                    beginning_balance=beg_senior + beg_mezz,
                    borrowing=0,
                    repayment=senior_repayment + mezz_repayment,
                    interest_rate=(
                        (senior_interest + mezz_interest) / (beg_senior + beg_mezz)
                        if (beg_senior + beg_mezz) > 0
                        else 0
                    ),
                    interest_expense=total_interest,
                    ending_balance=end_senior + end_mezz,
                )
            )

        return schedule

    def _calculate_cash_flows(
        self,
        operating: List[OperatingProjections],
        debt_schedule: List[DebtScheduleRow],
    ) -> List[CashFlowItem]:
        """计算现金流"""
        cash_flows = []
        cumulative = 0

        for i, (op, debt) in enumerate(zip(operating, debt_schedule)):
            # 可用现金流
            cfa = op.ebitda - op.depreciation - op.amortization - op.interest - op.taxes

            # CapEx
            capex = op.revenue * self.DEFAULT_CAPEX_PCT

            # 可用现金流
            fcfa = cfa - capex

            # 债务还款
            debt_repayment = debt.repayment

            # 自由现金流
            fcf = fcfa - debt_repayment
            cumulative += fcf

            cash_flows.append(
                CashFlowItem(
                    year=op.year,
                    ebitda=op.ebitda,
                    less_depreciation=op.depreciation,
                    less_amortization=op.amortization,
                    less_interest=op.interest,
                    less_taxes=op.taxes,
                    plus_other=0,
                    cash_flow_available=cfa,
                    less_capex=capex,
                    less_debt_repayment=debt_repayment,
                    free_cash_flow=fcf,
                    cumulative_free_cash_flow=cumulative,
                )
            )

        return cash_flows

    def _calculate_returns(
        self,
        equity_investment: float,
        operating: List[OperatingProjections],
        debt_schedule: List[DebtScheduleRow],
    ) -> ReturnsAnalysis:
        """计算回报分析"""
        # 最后一年 EBITDA
        final_ebitda = operating[-1].ebitda if operating else 0

        # 退出企业价值
        exit_ev = final_ebitda * self.exit_multiple

        # 退出时债务
        exit_debt = debt_schedule[-1].ending_balance if debt_schedule else 0

        # 假设退出时现金 = 最低现金余额
        exit_cash = self.DEFAULT_MIN_CASH

        # 退出股权价值
        exit_equity = exit_ev - exit_debt + exit_cash

        # 退出倍数 (MOIC)
        moic = exit_equity / equity_investment if equity_investment > 0 else 0

        # IRR 计算
        cash_flows = [-equity_investment]  # 初始投资
        for cf in operating:
            cash_flows.append(0)  # 持有期间无分配
        cash_flows.append(exit_equity)  # 退出时分配

        try:
            irr = _irr(cash_flows)
        except:
            irr = (moic ** (1 / self.holding_period)) - 1

        # Cash on Cash
        coc = (
            (exit_equity - equity_investment) / equity_investment
            if equity_investment > 0
            else 0
        )

        return ReturnsAnalysis(
            total_investment=equity_investment,
            exit_enterprise_value=exit_ev,
            exit_debt=exit_debt,
            exit_cash=exit_cash,
            exit_equity_value=exit_equity,
            exit_multiple=moic,
            irr=irr,
            cash_on_cash=coc,
        )
