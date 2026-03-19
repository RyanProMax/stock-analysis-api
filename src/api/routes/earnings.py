# -*- coding: utf-8 -*-
"""
季报分析控制器
"""

from fastapi import APIRouter, Query
from typing import Optional

from ...analyzer.earnings_analyzer import EarningsAnalyzer
from ...analyzer.normalizers import earnings_contract
from ..schemas import StandardResponse, StructuredInterfaceResponse

router = APIRouter()


@router.get(
    "/earnings",
    response_model=StandardResponse[StructuredInterfaceResponse],
    summary="季报分析",
)
def analyze_earnings(
    symbol: str = Query(
        ...,
        description="股票代码 (仅支持美股)",
        examples=[{"description": "股票代码示例", "value": "AAPL"}],
    ),
    quarter: Optional[str] = Query(
        None,
        description="季度 (Q1/Q2/Q3/Q4)，默认最新季度",
        pattern="^(Q1|Q2|Q3|Q4)$",
    ),
    fiscal_year: Optional[int] = Query(
        None,
        description="财年，默认当前年份",
        ge=2020,
        le=2030,
    ),
):
    """
    季报分析

    分析公司最新季度财报，包括:

    - **财报摘要**: 收入、净利润、EBITDA、EPS
    - **Beat/Miss 分析**: 预期 vs 实际对比
    - **业务板块**: 各业务线表现
    - **指引更新**: EPS 指引、价格目标
    - **关键指标**: 盈利能力、效率、流动性、增长
    - **趋势分析**: 历史收入和利润趋势
    - **数据来源**: 完整的引用信息

    仅支持美股，数据来源为 yfinance。
    """
    try:
        symbol = symbol.upper()

        # 执行分析
        analyzer = EarningsAnalyzer()
        result = analyzer.analyze(
            symbol=symbol,
            quarter=quarter,
            fiscal_year=fiscal_year,
        )
        response_data = earnings_contract(result.to_dict())

        if result.error:
            return StandardResponse(
                status_code=400,
                data=response_data,
                err_msg=result.error,
            )

        return StandardResponse(
            status_code=200,
            data=response_data,
            err_msg=None,
        )

    except Exception as e:
        return StandardResponse(
            status_code=500,
            data=None,
            err_msg=f"季报分析失败: {str(e)}",
        )
