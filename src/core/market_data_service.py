"""兼容层：旧 core 路径转发到 services。"""

from ..services.daily_data_read_service import (
    DailyDataReadService as DailyMarketDataService,
    daily_data_read_service as daily_market_data_service,
)

__all__ = ["DailyMarketDataService", "daily_market_data_service"]
