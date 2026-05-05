from __future__ import annotations

import math
import os
from typing import Any, Iterable

from ...model.trading import MarketSnapshot

FUTU_CODE_PREFIXES = {"HK", "US", "SH", "SZ", "SG"}


class FutuProviderError(RuntimeError):
    pass


def normalize_futu_code(raw_code: str) -> str:
    text = str(raw_code or "").strip()
    if "." not in text:
        raise ValueError(f"Futu code requires market prefix: {raw_code}")

    prefix, body = text.split(".", 1)
    normalized_prefix = prefix.strip().upper()
    normalized_body = body.strip().upper()
    if normalized_prefix not in FUTU_CODE_PREFIXES or not normalized_body:
        raise ValueError(f"Unsupported Futu code: {raw_code}")
    return f"{normalized_prefix}.{normalized_body}"


def _safe_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(result):
        return None
    return result


def _safe_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(result):
        return None
    return int(result)


def _as_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


class FutuOpenDGateway:
    def __init__(self, *, host: str | None = None, port: int | None = None) -> None:
        self.host = host or os.environ.get("FUTU_OPEND_HOST", "127.0.0.1")
        self.port = int(port or os.environ.get("FUTU_OPEND_PORT", "11111"))

    def get_market_snapshots(self, codes: Iterable[str]) -> list[dict[str, Any]]:
        normalized_codes = [normalize_futu_code(code) for code in codes]
        try:
            from futu import OpenQuoteContext, RET_OK  # type: ignore
        except ImportError as exc:
            raise FutuProviderError("futu-api is required for FutuOpenDGateway") from exc

        ctx = OpenQuoteContext(host=self.host, port=self.port)
        try:
            ret, data = ctx.get_market_snapshot(normalized_codes)
            if ret != RET_OK:
                raise FutuProviderError(f"Futu get_market_snapshot failed: {data}")
            if hasattr(data, "to_dict"):
                return list(data.to_dict("records"))
            return [dict(item) for item in data]
        finally:
            ctx.close()


class FutuMarketDataProvider:
    source = "futu_opend"

    def __init__(self, *, gateway: FutuOpenDGateway | None = None) -> None:
        self._gateway = gateway or FutuOpenDGateway()

    def get_market_snapshots(self, codes: Iterable[str]) -> list[MarketSnapshot]:
        normalized_codes = [normalize_futu_code(code) for code in codes]
        rows = self._gateway.get_market_snapshots(normalized_codes)
        return [self._map_snapshot(row) for row in rows]

    def _map_snapshot(self, row: dict[str, Any]) -> MarketSnapshot:
        raw_code = row.get("code") or row.get("stock_code")
        code = normalize_futu_code(str(raw_code)) if raw_code else ""
        update_time = (
            _as_text(row.get("update_time"))
            or _as_text(row.get("data_time"))
            or _as_text(row.get("time"))
        )
        return MarketSnapshot(
            code=code,
            name=_as_text(row.get("name") or row.get("stock_name")) or "",
            price=_safe_float(row.get("last_price") if "last_price" in row else row.get("price")),
            open_price=_safe_float(
                row.get("open_price") if "open_price" in row else row.get("open")
            ),
            high=_safe_float(row.get("high_price") if "high_price" in row else row.get("high")),
            low=_safe_float(row.get("low_price") if "low_price" in row else row.get("low")),
            prev_close=_safe_float(
                row.get("prev_close_price") if "prev_close_price" in row else row.get("prev_close")
            ),
            volume=_safe_int(row.get("volume")),
            turnover=_safe_float(
                row.get("turnover") if "turnover" in row else row.get("turnover_rate")
            ),
            as_of=update_time,
            source=self.source,
            raw=dict(row),
        )
