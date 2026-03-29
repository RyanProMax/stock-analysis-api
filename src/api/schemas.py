from pydantic import BaseModel, ConfigDict
from typing import Any, Dict, Generic, List, Optional, TypeVar

T = TypeVar("T")


class StandardResponse(BaseModel, Generic[T]):
    status_code: int
    data: Optional[T] = None
    err_msg: Optional[str] = None

    model_config = ConfigDict(
        json_schema_extra={"example": {"status_code": 200, "data": None, "err_msg": None}}
    )


class StockAnalysisRequest(BaseModel):
    market: str
    symbols: List[str]
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    mode: str = "base"

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "market": "cn",
                "symbols": ["300827"],
                "start_date": "20260227",
                "end_date": "20260329",
                "mode": "base",
            }
        },
    )


class StructuredInterfaceResponse(BaseModel):
    entity: Dict[str, Any]
    facts: Dict[str, Any]
    analysis: Dict[str, Any]
    meta: Dict[str, Any]


class WatchPollRequest(BaseModel):
    symbols: List[str]

    model_config = ConfigDict(
        json_schema_extra={"example": {"symbols": ["NVDA", "AAPL", "600519"]}}
    )
