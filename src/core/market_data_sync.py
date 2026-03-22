"""兼容层：旧 core 路径转发到 services。"""

from ..services.daily_data_write_service import (
    DailyDataWriteService as DailyWarehouseSyncService,
    daily_data_write_service as daily_warehouse_sync_service,
)

__all__ = ["DailyWarehouseSyncService", "daily_warehouse_sync_service"]
