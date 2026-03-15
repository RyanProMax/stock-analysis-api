"""
路由注册模块 - 统一管理所有API路由
"""

from fastapi import APIRouter
from .stock import router as stock_router
from .valuation import router as valuation_router
from .comps import router as comps_router
from .model import router as model_router

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
