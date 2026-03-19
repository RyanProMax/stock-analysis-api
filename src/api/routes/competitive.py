# -*- coding: utf-8 -*-
"""
竞争分析控制器
"""

from fastapi import APIRouter, Query
from typing import Optional

from ...analyzer.competitive_analyzer import CompetitiveAnalyzer
from ..schemas import StandardResponse

router = APIRouter()


@router.get(
    "/competitive",
    response_model=StandardResponse[dict],
    summary="竞争格局分析（含估算字段）",
)
def analyze_competitive(
    symbol: str = Query(
        ...,
        description="目标公司股票代码 (仅支持美股)",
        examples=[{"description": "公司代码示例", "value": "NVDA"}],
    ),
    competitors: Optional[str] = Query(
        None,
        description="竞争对手代码，逗号分隔 (可选，如 'AMD,INTC,AVGO')",
    ),
    industry: str = Query(
        "technology",
        description="行业类型 (technology/saas/payments/marketplace/retail/logistics)",
    ),
):
    """
    竞争格局分析

    分析目标公司的竞争环境，包括:

    - **市场背景**: 行业概况、估算市场背景
    - **目标公司画像**: 财务指标、估值、分析师预期
    - **竞争对手数据**: 主要竞争对手财务对比
    - **定位可视化**: 2×2 矩阵数据
    - **比较分析**: 多维度对比表格
    - **护城河评估**: 网络效应、转换成本、规模经济等

    仅支持美股，数据来源为 yfinance。
    返回中的市场背景、护城河和场景字段包含启发式估算，不应视为外部已验证事实。
    """
    try:
        symbol = symbol.upper()

        # 解析竞争对手列表
        competitor_list = None
        if competitors:
            competitor_list = [c.strip().upper() for c in competitors.split(",")]

        # 执行分析
        analyzer = CompetitiveAnalyzer()
        result = analyzer.analyze(
            symbol=symbol,
            competitors=competitor_list,
            industry=industry,
        )

        if result.error:
            return StandardResponse(
                status_code=400,
                data=result.to_dict(),
                err_msg=result.error,
            )

        return StandardResponse(
            status_code=200,
            data=result.to_dict(),
            err_msg=None,
        )

    except Exception as e:
        return StandardResponse(
            status_code=500,
            data=None,
            err_msg=f"竞争分析失败: {str(e)}",
        )
