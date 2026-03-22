"""API 依赖装配。"""

from ..services import (
    daily_data_read_service,
    daily_data_write_service,
    symbol_catalog_service,
    watch_polling_service,
)


def get_symbol_catalog_service():
    return symbol_catalog_service


def get_daily_data_read_service():
    return daily_data_read_service


def get_daily_data_write_service():
    return daily_data_write_service


def get_watch_polling_service():
    return watch_polling_service
