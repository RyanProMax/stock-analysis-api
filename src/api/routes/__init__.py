"""
HTTP路由模块
"""

from .stock import router as stock_router
from .index import router as index_router
from .watch import router as watch_router

__all__ = [
    "stock_router",
    "index_router",
    "watch_router",
]
