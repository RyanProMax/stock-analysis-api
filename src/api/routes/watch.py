from fastapi import APIRouter

from ...analyzer.normalizers import watch_poll_contract
from ...core.watch_polling import watch_polling_service
from ..schemas import StandardResponse, StructuredInterfaceResponse, WatchPollRequest


router = APIRouter()


@router.post(
    "/poll",
    response_model=StandardResponse[list[StructuredInterfaceResponse]],
    summary="盯盘轮询接口",
)
def poll_watchlist(payload: WatchPollRequest):
    try:
        normalized = [symbol.strip().upper() for symbol in payload.symbols if symbol.strip()]
        if not normalized:
            return StandardResponse(
                status_code=400,
                data=None,
                err_msg="请至少提供一个有效的股票代码。",
            )

        items = watch_polling_service.poll(normalized, refresh=payload.refresh)
        response_data = [watch_poll_contract(item) for item in items]
        return StandardResponse(status_code=200, data=response_data, err_msg=None)
    except Exception as e:
        return StandardResponse(
            status_code=500,
            data=None,
            err_msg=f"盯盘轮询失败: {str(e)}",
        )
