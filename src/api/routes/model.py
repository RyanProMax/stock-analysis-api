# -*- coding: utf-8 -*-
"""
模型分析控制器 - LBO 和 3-Statement Model 接口
"""

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse
from typing import Optional

from ...analyzer.lbo_model import LBOModel
from ...analyzer.normalizers import lbo_contract, three_statement_contract
from ...analyzer.three_statement_model import ThreeStatementModel
from ..schemas import StandardResponse, StructuredInterfaceResponse

router = APIRouter()


@router.get(
    "/lbo",
    response_model=StandardResponse[StructuredInterfaceResponse],
    summary="LBO 情景模型",
)
def analyze_lbo(
    symbol: str = Query(
        ...,
        description="股票代码 (仅支持美股)",
        examples=[{"description": "股票代码示例", "value": "NVDA"}],
    ),
    holding_period: Optional[int] = Query(
        5,
        description="持有年限 (默认 5 年)",
        ge=3,
        le=10,
    ),
    entry_multiple: Optional[float] = Query(
        10.0,
        description="入场 EV/EBITDA 倍数 (默认 10x)",
        ge=5.0,
        le=20.0,
    ),
    exit_multiple: Optional[float] = Query(
        10.0,
        description="出场 EV/EBITDA 倍数 (默认 10x)",
        ge=5.0,
        le=20.0,
    ),
    leverage: Optional[float] = Query(
        0.65,
        description="债务占比 (默认 65%)",
        ge=0.3,
        le=0.9,
    ),
):
    """
    LBO (Leveraged Buyout) 情景模型

    基于杠杆收购模型计算投资回报，包括：

    - **Sources & Uses**: 资金来源与用途分析
    - **运营预测**: 收入、EBITDA 预测
    - **债务时间表**: 优先债务、中层债务还款计划
    - **现金流分析**: 自由现金流、偿债能力
    - **回报分析**: IRR、MOIC (退出倍数)

    仅支持美股，数据来源为 yfinance。
    返回结果属于参数化情景测算，不应视为市场观测值。
    """
    try:
        symbol = symbol.upper()

        # 债务结构参数
        leverage_val = leverage if leverage is not None else 0.65
        senior_pct = leverage_val * 0.8  # 优先债务占债务的80%
        mezz_pct = leverage_val * 0.2  # 中层债务占债务的20%

        # 创建 LBO 模型
        model = LBOModel(
            holding_period=holding_period if holding_period is not None else 5,
            entry_multiple=entry_multiple if entry_multiple is not None else 10.0,
            exit_multiple=exit_multiple if exit_multiple is not None else 10.0,
            senior_debt_pct=senior_pct,
            mezz_debt_pct=mezz_pct,
        )

        # 执行 LBO 分析
        result = model.analyze(symbol)

        # 转换为字典格式
        response_data = lbo_contract(result.to_dict())

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
            err_msg=f"LBO 分析失败: {str(e)}",
        )


@router.get(
    "/three-statement",
    response_model=StandardResponse[StructuredInterfaceResponse],
    summary="3-Statement 预测模型",
)
def analyze_three_statement(
    symbol: str = Query(
        ...,
        description="股票代码 (仅支持美股)",
        examples=[{"description": "股票代码示例", "value": "NVDA"}],
    ),
    scenario: str = Query(
        "base",
        description="情景 (bull/base/bear)",
        pattern="^(bull|base|bear)$",
    ),
    projection_years: Optional[int] = Query(
        5,
        description="预测年限 (默认 5 年)",
        ge=3,
        le=10,
    ),
):
    """
    3-Statement Model (三表预测模型)

    预测公司未来财务状况，包括：

    - **Income Statement**: 损益表预测
    - **Balance Sheet**: 资产负债表预测
    - **Cash Flow Statement**: 现金流量表预测
    - **勾稽验证**: 三大表平衡检查
    - **关键指标**: 盈利能力、杠杆率、流动性指标
    - **情景分析**: Bull / Base / Bear 三种情景

    仅支持美股，数据来源为 yfinance。
    返回结果属于预测模型，不应解释为公司已披露的事实报表。
    """
    try:
        symbol = symbol.upper()

        # 创建 3-Statement 模型
        model = ThreeStatementModel(
            projection_years=projection_years if projection_years is not None else 5
        )

        # 执行分析
        result = model.analyze(symbol, scenario)

        # 转换为字典格式
        response_data = three_statement_contract(result.to_dict())

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
            err_msg=f"三表模型分析失败: {str(e)}",
        )


@router.get(
    "/three-statement/scenarios",
    response_model=StandardResponse[StructuredInterfaceResponse],
    summary="3-Statement 情景预测对比",
)
def compare_three_statement_scenarios(
    symbol: str = Query(
        ...,
        description="股票代码 (仅支持美股)",
        examples=[{"description": "股票代码示例", "value": "NVDA"}],
    ),
    projection_years: Optional[int] = Query(
        5,
        description="预测年限 (默认 5 年)",
        ge=3,
        le=10,
    ),
):
    """
    对比三种情景 (Bull / Base / Bear) 的 3-Statement Model 结果

    返回每个情景的:
    - Revenue, EBITDA, Net Income 预测
    - 关键财务指标对比
    - 估值区间
    """
    try:
        symbol = symbol.upper()
        model = ThreeStatementModel(
            projection_years=projection_years if projection_years is not None else 5
        )

        scenarios_result = {}
        for scenario in ["bull", "base", "bear"]:
            result = model.analyze(symbol, scenario)
            scenarios_result[scenario] = {
                "revenue_growth": result.revenue_growth_rate,
                "key_metrics": result.key_metrics,
                "assumptions": result.assumptions,
            }

        return StandardResponse(
            status_code=200,
            data=three_statement_contract(
                {
                    "symbol": symbol,
                    "company_name": symbol,
                    "historical_source": "scenario_comparison",
                    "as_of": None,
                    "limitations": ["Scenario comparison derived from model outputs"],
                    "scenarios": scenarios_result,
                }
            ),
            err_msg=None,
        )

    except Exception as e:
        return StandardResponse(
            status_code=500,
            data=None,
            err_msg=f"情景分析失败: {str(e)}",
        )
