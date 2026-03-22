"""
Repository 层。

统一封装本地 SQLite 持久化访问。
"""

from .market_data_repository import MarketDataRepository, market_data_repository

__all__ = ["MarketDataRepository", "market_data_repository"]
