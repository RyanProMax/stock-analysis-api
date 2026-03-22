"""
路由注册模块 - 统一管理所有API路由
"""

from fastapi import APIRouter
from .stock import router as stock_router
from .valuation import router as valuation_router
from .comps import router as comps_router
from .model import router as model_router
from .competitive import router as competitive_router
from .earnings import router as earnings_router
from .watch import router as watch_router

# 创建主路由器
router = APIRouter()

# 注册股票分析相关路由
# /stock/* - 股票数据和分析接口
router.include_router(stock_router, prefix="/stock", tags=["Stock"])

# 注册估值分析相关路由
# /valuation/* - DCF 和 Comps 估值分析接口
router.include_router(valuation_router, prefix="/valuation", tags=["Valuation"])
router.include_router(comps_router, prefix="/valuation", tags=["Valuation"])

# 注册模型分析相关路由
# /model/* - LBO 和 3-Statement Model 接口
router.include_router(model_router, prefix="/model", tags=["Model"])

# 注册竞争分析相关路由
# /analysis/competitive/* - 竞争格局分析接口
router.include_router(
    competitive_router, prefix="/analysis/competitive", tags=["Analysis"]
)

# 注册季报分析相关路由
# /analysis/earnings/* - 季报分析接口
router.include_router(earnings_router, prefix="/analysis/earnings", tags=["Analysis"])

# 注册盯盘轮询相关路由
# /watch/* - 外部 Agent 盯盘接口
router.include_router(watch_router, prefix="/watch", tags=["Watch"])
