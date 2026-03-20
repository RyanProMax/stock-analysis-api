# -*- coding: utf-8 -*-
"""
LBO (Leveraged Buyout) Model 数据类型定义

包含 LBO 分析相关的所有数据类
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any


@dataclass
class SourcesAndUses:
    """资金来源与用途"""

    # 用途 (Uses)
    purchase_price: float = 0.0  # 收购价格
    financing_fees: float = 0.0  # 融资费用
    transaction_fees: float = 0.0  # 交易费用
    total_uses: float = 0.0  # 总用途

    # 来源 (Sources)
    senior_debt: float = 0.0  # 优先债务
    subordinated_debt: float = 0.0  # 次级债务
    mezzanine_debt: float = 0.0  # 中层债务
    total_debt: float = 0.0  # 总债务
    equity: float = 0.0  # 股权
    total_sources: float = 0.0  # 总来源


@dataclass
class DebtScheduleRow:
    """单年度债务明细"""

    year: int
    beginning_balance: float  # 期初余额
    borrowing: float  # 新增借款
    repayment: float  # 还款
    interest_rate: float  # 利率
    interest_expense: float  # 利息支出
    ending_balance: float  # 期末余额


@dataclass
class OperatingProjections:
    """运营预测"""

    year: int
    revenue: float  # 收入
    revenue_growth: float  # 收入增长率
    ebitda: float  # EBITDA
    ebitda_margin: float  # EBITDA利润率
    ebit: float  # EBIT
    depreciation: float  # 折旧
    amortization: float  # 摊销
    interest: float  # 利息
    ebt: float  # 税前利润
    taxes: float  # 税金
    net_income: float  # 净利润


@dataclass
class CashFlowItem:
    """现金流明细"""

    year: int
    ebitda: float
    less_depreciation: float
    less_amortization: float
    less_interest: float
    less_taxes: float
    plus_other: float
    cash_flow_available: float
    less_capex: float
    less_debt_repayment: float
    free_cash_flow: float
    cumulative_free_cash_flow: float


@dataclass
class ReturnsAnalysis:
    """回报分析"""

    total_investment: float = 0.0  # 总投资
    exit_enterprise_value: float = 0.0  # 退出企业价值
    exit_debt: float = 0.0  # 退出时债务
    exit_cash: float = 0.0  # 退出时现金
    exit_equity_value: float = 0.0  # 退出股权价值
    exit_multiple: float = 0.0  # 退出倍数 (MOIC)
    irr: float = 0.0  # 内部收益率
    cash_on_cash: float = 0.0  # 现金回报率


@dataclass
class LBOResult:
    """LBO 分析结果"""

    symbol: str
    company_name: str = ""
    current_price: float = 0.0

    # 交易参数
    entry_enterprise_value: float = 0.0  # 入场企业价值 (百万)
    purchase_price: float = 0.0  # 收购价格 (百万)
    equity_check: float = 0.0  # 股权投入 (百万)
    leverage_multiple: float = 0.0  # 杠杆倍数 (Debt/Equity)

    # 资金来源与用途
    sources_and_uses: SourcesAndUses = field(default_factory=SourcesAndUses)

    # 运营预测
    operating_projections: List[OperatingProjections] = field(default_factory=list)

    # 债务时间表
    debt_schedule: List[DebtScheduleRow] = field(default_factory=list)

    # 现金流
    cash_flows: List[CashFlowItem] = field(default_factory=list)

    # 回报分析
    returns: ReturnsAnalysis = field(default_factory=ReturnsAnalysis)

    # 假设参数
    assumptions: Dict[str, Any] = field(default_factory=dict)

    # 元数据
    model_type: str = "scenario"
    derived_from_assumptions: bool = True
    assumptions_source: str = "user_parameters_and_heuristics"
    fundamental_context: Dict[str, Any] = field(default_factory=dict)

    # 错误信息
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            "symbol": self.symbol,
            "company_name": self.company_name,
            "current_price": self.current_price,
            "transaction": {
                "entry_enterprise_value": round(self.entry_enterprise_value, 2),
                "purchase_price": round(self.purchase_price, 2),
                "equity_check": round(self.equity_check, 2),
                "leverage_multiple": round(self.leverage_multiple, 2),
            },
            "sources_and_uses": {
                "uses": {
                    "purchase_price": round(self.sources_and_uses.purchase_price, 2),
                    "financing_fees": round(self.sources_and_uses.financing_fees, 2),
                    "transaction_fees": round(
                        self.sources_and_uses.transaction_fees, 2
                    ),
                    "total_uses": round(self.sources_and_uses.total_uses, 2),
                },
                "sources": {
                    "senior_debt": round(self.sources_and_uses.senior_debt, 2),
                    "subordinated_debt": round(
                        self.sources_and_uses.subordinated_debt, 2
                    ),
                    "mezzanine_debt": round(self.sources_and_uses.mezzanine_debt, 2),
                    "total_debt": round(self.sources_and_uses.total_debt, 2),
                    "equity": round(self.sources_and_uses.equity, 2),
                    "total_sources": round(self.sources_and_uses.total_sources, 2),
                },
            },
            "operating_projections": [
                {
                    "year": p.year,
                    "revenue": round(p.revenue, 2),
                    "revenue_growth": round(p.revenue_growth * 100, 2),
                    "ebitda": round(p.ebitda, 2),
                    "ebitda_margin": round(p.ebitda_margin * 100, 2),
                    "net_income": round(p.net_income, 2),
                }
                for p in self.operating_projections
            ],
            "returns": {
                "total_investment": round(self.returns.total_investment, 2),
                "exit_enterprise_value": round(self.returns.exit_enterprise_value, 2),
                "exit_debt": round(self.returns.exit_debt, 2),
                "exit_cash": round(self.returns.exit_cash, 2),
                "exit_equity_value": round(self.returns.exit_equity_value, 2),
                "exit_multiple": round(self.returns.exit_multiple, 2),
                "irr": round(self.returns.irr * 100, 2),
                "cash_on_cash": round(self.returns.cash_on_cash * 100, 2),
            },
            "assumptions": self.assumptions,
            "model_type": self.model_type,
            "derived_from_assumptions": self.derived_from_assumptions,
            "assumptions_source": self.assumptions_source,
            "fundamental_context": self.fundamental_context,
            "error": self.error,
        }


@dataclass
class ThreeStatementResult:
    """三表模型结果"""

    symbol: str
    company_name: str = ""

    # 收入模型
    revenue_base: float = 0.0
    revenue_growth_rate: float = 0.0

    # Income Statement 预测
    income_statements: List[Dict[str, Any]] = field(default_factory=list)

    # Balance Sheet 预测
    balance_sheets: List[Dict[str, Any]] = field(default_factory=list)

    # Cash Flow Statement 预测
    cash_flow_statements: List[Dict[str, Any]] = field(default_factory=list)

    # 关键指标
    key_metrics: Dict[str, Any] = field(default_factory=dict)

    # 假设
    assumptions: Dict[str, Any] = field(default_factory=dict)

    # 元数据
    model_type: str = "forecast"
    historical_source: str = ""
    as_of: Optional[str] = None
    limitations: List[str] = field(default_factory=list)
    fundamental_context: Dict[str, Any] = field(default_factory=dict)

    # 错误信息
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            "symbol": self.symbol,
            "company_name": self.company_name,
            "income_statements": self.income_statements,
            "balance_sheets": self.balance_sheets,
            "cash_flow_statements": self.cash_flow_statements,
            "key_metrics": self.key_metrics,
            "assumptions": self.assumptions,
            "model_type": self.model_type,
            "historical_source": self.historical_source,
            "as_of": self.as_of,
            "limitations": self.limitations,
            "fundamental_context": self.fundamental_context,
            "error": self.error,
        }
