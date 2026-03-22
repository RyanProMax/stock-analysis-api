"""兼容层：旧 core 路径转发到 services。"""

from ..data_provider.manager import data_manager
from ..services.daily_data_read_service import daily_data_read_service as daily_market_data_service
from ..services.watch_polling_service import WatchPollingService, watch_polling_service

__all__ = [
    "WatchPollingService",
    "watch_polling_service",
    "data_manager",
    "daily_market_data_service",
]
