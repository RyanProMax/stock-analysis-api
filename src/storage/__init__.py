"""兼容层：旧 storage 导入路径转发到 repositories。"""

from ..repositories import MarketDataRepository as MarketDataStorage, market_data_repository as market_data_storage

__all__ = ["MarketDataStorage", "market_data_storage"]
