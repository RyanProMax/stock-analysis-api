# -*- coding: utf-8 -*-
"""
报告数据类型定义

注意：此模块只包含数据类型定义，不引用项目其他模块，避免循环依赖
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional

from .trend import TrendAnalysisResult


@dataclass
class FactorDetail:
    """因子详情"""

    key: str  # 因子类型标识：trend/volatility/momentum/volume/fundamental
    name: str  # 因子名称
    status: str  # 因子状态描述
    bullish_signals: List[str] = field(default_factory=list)
    bearish_signals: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "key": self.key,
            "name": self.name,
            "status": self.status,
            "bullish_signals": self.bullish_signals,
            "bearish_signals": self.bearish_signals,
        }


@dataclass
class FactorAnalysis:
    """因子分析结果（技术面/基本面/Qlib）"""

    factors: List[FactorDetail] = field(default_factory=list)
    data_source: str = ""
    raw_data: Dict[str, Any] | None = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "factors": [factor.to_dict() for factor in self.factors],
            "data_source": self.data_source,
            "raw_data": self.raw_data,
        }


@dataclass
class FearGreed:
    """贪恐指数对象"""

    index: float  # 贪恐指数值 (0-100)
    label: str  # 贪恐指数标签

    def to_dict(self) -> Dict[str, Any]:
        return {
            "index": self.index,
            "label": self.label,
        }


@dataclass
class AnalysisReport:
    """封装单次完整的股票分析结果"""

    symbol: str
    stock_name: str
    price: float
    as_of: Optional[str] = None
    # 基础指标
    fear_greed: FearGreed = field(default_factory=lambda: FearGreed(index=50.0, label="中性"))
    # 行业信息（用于基本面分析时的行业对比）
    industry: str = ""
    # 因子分析结果（新结构）
    technical: FactorAnalysis = field(default_factory=FactorAnalysis)
    fundamental: FactorAnalysis = field(default_factory=FactorAnalysis)
    qlib: FactorAnalysis = field(default_factory=FactorAnalysis)
    # 趋势分析结果
    trend_analysis: Optional[TrendAnalysisResult] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "stock_name": self.stock_name,
            "price": self.price,
            "as_of": self.as_of,
            "fear_greed": self.fear_greed.to_dict(),
            "industry": self.industry,
            "technical": self.technical.to_dict(),
            "fundamental": self.fundamental.to_dict(),
            "qlib": self.qlib.to_dict(),
            "trend_analysis": (
                self.trend_analysis.to_dict() if self.trend_analysis is not None else None
            ),
        }


@dataclass
class FactorSignal:
    """因子信号"""

    key: str
    name: str
    signal: str  # bullish/bearish/neutral
    strength: float  # 信号强度 0-1
    reason: str  # 信号原因
