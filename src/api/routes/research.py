from typing import Any, Dict

from fastapi import APIRouter

from ...services.research_snapshot_service import research_snapshot_service
from ..schemas import ResearchSnapshotRequest, StandardResponse

router = APIRouter()


@router.post(
    "/snapshot",
    response_model=StandardResponse[Dict[str, Any]],
    summary="统一 Research Snapshot 客观分析入口",
)
def poll_research_snapshot(payload: ResearchSnapshotRequest):
    normalized_symbols = [symbol.strip().upper() for symbol in payload.symbols if symbol.strip()]
    if not normalized_symbols:
        return StandardResponse(
            status_code=400,
            data=None,
            err_msg="请至少提供一个有效的股票代码。",
        )

    try:
        response_payload = research_snapshot_service.poll_snapshot(
            market=payload.market,
            symbols=normalized_symbols,
            start_date=payload.start_date,
            end_date=payload.end_date,
            modules=payload.modules,
            module_options=payload.module_options,
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
            err_msg=f"Research snapshot 生成失败: {str(exc)}",
        )
