from pydantic import BaseModel, ConfigDict
from typing import Any, Dict, Generic, List, Optional, TypeVar

T = TypeVar("T")


class StandardResponse(BaseModel, Generic[T]):
    status_code: int
    data: Optional[T] = None
    err_msg: Optional[str] = None

    model_config = ConfigDict(
        json_schema_extra={
            "example": {"status_code": 200, "data": None, "err_msg": None}
        }
    )


class StockAnalysisRequest(BaseModel):
    symbols: List[str]
    include_qlib_factors: bool = False

    model_config = ConfigDict(
        json_schema_extra={
            "example": {"symbols": ["NVDA", "AAPL", "600519"], "include_qlib_factors": False}
        }
    )


class StructuredInterfaceResponse(BaseModel):
    entity: Dict[str, Any]
    facts: Dict[str, Any]
    analysis: Dict[str, Any]
    meta: Dict[str, Any]


class StockRecordResponse(BaseModel):
    ts_code: str
    symbol: str
    name: str
    area: Optional[str] = None
    industry: Optional[str] = None
    market: Optional[str] = None
    list_date: Optional[str] = None
    meta: Dict[str, Any]


class StockListResponse(BaseModel):
    stocks: List[StockRecordResponse]
    total: int
    meta: Dict[str, Any]


class StockSearchRequest(BaseModel):
    keyword: str
    market: Optional[str] = None

    model_config = ConfigDict(
        json_schema_extra={"example": {"keyword": "NVDA", "market": None}}
    )
