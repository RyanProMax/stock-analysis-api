"""
路由注册模块 - 统一管理所有API路由
"""

from fastapi import APIRouter
from .stock import router as stock_router
from .research import router as research_router
from .watch import router as watch_router

# 创建主路由器
router = APIRouter()

# 注册股票分析相关路由
# /stock/* - 股票数据和分析接口
router.include_router(stock_router, prefix="/stock", tags=["Stock"])

# 注册统一 research snapshot 路由
# /analysis/research/* - FSP 客观能力统一快照入口
router.include_router(research_router, prefix="/analysis/research", tags=["Analysis"])

# 注册盯盘轮询相关路由
# /watch/* - 外部 Agent 盯盘接口
router.include_router(watch_router, prefix="/watch", tags=["Watch"])
