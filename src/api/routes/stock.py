"""股票分析控制器 - 处理公共 stock analyze HTTP 接口"""

from typing import Any, Dict

from fastapi import APIRouter

from ...services.stock_analyze_service import stock_analyze_service
from ..schemas import StandardResponse, StockAnalysisRequest

router = APIRouter()


@router.post(
    "/analyze",
    response_model=StandardResponse[Dict[str, Any]],
    summary="批量分析股票列表",
)
def analyze_stocks(payload: StockAnalysisRequest):
    normalized_symbols = [symbol.strip().upper() for symbol in payload.symbols if symbol.strip()]
    if not normalized_symbols:
        return StandardResponse(
            status_code=400,
            data=None,
            err_msg="请至少提供一个有效的股票代码。",
        )

    try:
        response_payload = stock_analyze_service.analyze(
            market=payload.market,
            symbols=normalized_symbols,
            start_date=payload.start_date,
            end_date=payload.end_date,
            mode=payload.mode,
        )
        return StandardResponse(status_code=200, data=response_payload, err_msg=None)
    except ValueError as exc:
        return StandardResponse(
            status_code=400,
            data=None,
            err_msg=str(exc),
        )
    except Exception as exc:
        return StandardResponse(
            status_code=500,
            data=None,
            err_msg=f"Stock analyze 生成失败: {str(exc)}",
        )
