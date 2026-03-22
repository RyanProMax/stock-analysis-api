"""
数据提供层 - 数据获取、格式处理

包含:
- sources: 数据源（Efinance, Tushare, AkShare, Pytdx, Baostock, yfinance, NASDAQ）
- manager: 数据源管理器（统一调度 + 熔断）
- models: 日线数据模型（DailyData）
- realtime_types: 实时行情/筹码分布模型（预留）
"""

from .manager import DataManager, data_manager
from ..model.data_provider import DailyData, DailyDataCollection
from .realtime_types import UnifiedRealtimeQuote, ChipDistribution, RealtimeSource
__all__ = [
    "DataManager",
    "data_manager",
    "DailyData",
    "DailyDataCollection",
    "UnifiedRealtimeQuote",
    "ChipDistribution",
    "RealtimeSource",
]
