from __future__ import annotations

import math
import os
from collections.abc import Mapping
from datetime import date, datetime
from typing import Any, Iterable

from ...model.trading import MarketSnapshot, OrderRequest

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


def infer_futu_trade_market(raw_code: str) -> str:
    normalized = normalize_futu_code(raw_code)
    prefix = normalized.split(".", 1)[0]
    if prefix in {"SH", "SZ"}:
        return "CN"
    return prefix


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


def to_jsonable(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [to_jsonable(item) for item in value]
    if hasattr(value, "item"):
        try:
            return to_jsonable(value.item())
        except Exception:
            pass
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            pass
    return str(value)


def df_to_records(data: Any) -> list[dict[str, Any]]:
    if data is None:
        return []
    if hasattr(data, "empty") and data.empty:
        return []
    if hasattr(data, "to_dict"):
        records = data.to_dict("records")
    else:
        records = list(data)
    return [to_jsonable(dict(record)) for record in records]


def _as_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


class FutuOpenDGateway:
    def __init__(self, *, host: str | None = None, port: int | None = None) -> None:
        self.host = host or os.environ.get("FUTU_OPEND_HOST", "127.0.0.1")
        self.port = int(port or os.environ.get("FUTU_OPEND_PORT", "11111"))

    @staticmethod
    def _open_quote_context(open_quote_context: Any, *, host: str, port: int) -> Any:
        try:
            return open_quote_context(host=host, port=port, ai_type=1)
        except TypeError:
            return open_quote_context(host=host, port=port)

    def get_market_snapshots(self, codes: Iterable[str]) -> list[dict[str, Any]]:
        normalized_codes = [normalize_futu_code(code) for code in codes]
        try:
            from futu import OpenQuoteContext, RET_OK  # type: ignore
        except ImportError as exc:
            raise FutuProviderError("futu-api is required for FutuOpenDGateway") from exc

        ctx = self._open_quote_context(OpenQuoteContext, host=self.host, port=self.port)
        try:
            ret, data = ctx.get_market_snapshot(normalized_codes)
            if ret != RET_OK:
                raise FutuProviderError(f"Futu get_market_snapshot failed: {data}")
            if hasattr(data, "to_dict"):
                return list(data.to_dict("records"))
            return [dict(item) for item in data]
        finally:
            ctx.close()

    def get_global_state(self) -> dict[str, Any]:
        try:
            from futu import OpenQuoteContext, RET_OK  # type: ignore
        except ImportError as exc:
            raise FutuProviderError("futu-api is required for FutuOpenDGateway") from exc

        ctx = self._open_quote_context(OpenQuoteContext, host=self.host, port=self.port)
        try:
            ret, data = ctx.get_global_state()
            if ret != RET_OK:
                raise FutuProviderError(f"Futu get_global_state failed: {data}")
            return to_jsonable(data)
        finally:
            ctx.close()

    def get_ipo_list(self, market: str) -> list[dict[str, Any]]:
        try:
            from futu import Market, OpenQuoteContext, RET_OK  # type: ignore
        except ImportError as exc:
            raise FutuProviderError("futu-api is required for FutuOpenDGateway") from exc

        market_key = str(market or "").strip().upper()
        market_map = {
            "HK": Market.HK,
            "US": Market.US,
            "SH": Market.SH,
            "SZ": Market.SZ,
        }
        futu_market = market_map.get(market_key)
        if futu_market is None:
            raise ValueError(f"Unsupported Futu IPO market: {market}")

        ctx = self._open_quote_context(OpenQuoteContext, host=self.host, port=self.port)
        try:
            ret, data = ctx.get_ipo_list(futu_market)
            if ret != RET_OK:
                raise FutuProviderError(f"Futu get_ipo_list failed: {data}")
            return df_to_records(data)
        finally:
            ctx.close()

    def request_history_kline(
        self,
        code: str,
        *,
        ktype: str = "1d",
        start: str | None = None,
        end: str | None = None,
        max_count: int = 1000,
        rehab: str = "forward",
        session: str = "NONE",
        max_page: int | None = None,
    ) -> list[dict[str, Any]]:
        normalized_code = normalize_futu_code(code)
        try:
            from futu import AuType, KLType, OpenQuoteContext, RET_OK, Session  # type: ignore
        except ImportError as exc:
            raise FutuProviderError("futu-api is required for FutuOpenDGateway") from exc

        ktype_map = {
            "1m": KLType.K_1M,
            "3m": KLType.K_3M,
            "5m": KLType.K_5M,
            "15m": KLType.K_15M,
            "30m": KLType.K_30M,
            "60m": KLType.K_60M,
            "1d": KLType.K_DAY,
            "1w": KLType.K_WEEK,
            "1M": KLType.K_MON,
            "1Q": KLType.K_QUARTER,
            "1Y": KLType.K_YEAR,
        }
        rehab_map = {
            "none": AuType.NONE,
            "forward": AuType.QFQ,
            "backward": AuType.HFQ,
        }
        session_map = {
            "NONE": Session.NONE,
            "RTH": Session.RTH,
            "ETH": Session.ETH,
            "ALL": Session.ALL,
        }
        futu_ktype = ktype_map.get(ktype, KLType.K_DAY)
        autype = rehab_map.get(str(rehab).lower(), AuType.QFQ)
        futu_session = session_map.get(str(session).upper(), Session.NONE)
        page_size = max(1, min(int(max_count or 1000), 1000))

        ctx = self._open_quote_context(OpenQuoteContext, host=self.host, port=self.port)
        try:
            ret, data, page_req_key = ctx.request_history_kline(
                normalized_code,
                start=start,
                end=end,
                ktype=futu_ktype,
                autype=autype,
                max_count=page_size,
                session=futu_session,
            )
            if ret != RET_OK:
                raise FutuProviderError(f"Futu request_history_kline failed: {data}")
            records = df_to_records(data)
            page_count = 1
            while page_req_key is not None:
                if max_page and page_count >= max_page:
                    break
                ret, data, page_req_key = ctx.request_history_kline(
                    normalized_code,
                    start=start,
                    end=end,
                    ktype=futu_ktype,
                    autype=autype,
                    max_count=page_size,
                    page_req_key=page_req_key,
                    session=futu_session,
                )
                if ret != RET_OK:
                    raise FutuProviderError(f"Futu request_history_kline page failed: {data}")
                records.extend(df_to_records(data))
                page_count += 1
            return records
        finally:
            ctx.close()


class FutuOpenDTradeGateway:
    def __init__(
        self,
        *,
        market: str,
        host: str | None = None,
        port: int | None = None,
        acc_id: int = 0,
        acc_index: int = 0,
    ) -> None:
        self.market = str(market or "").strip().upper()
        self.host = host or os.environ.get("FUTU_OPEND_HOST", "127.0.0.1")
        self.port = int(port or os.environ.get("FUTU_OPEND_PORT", "11111"))
        self.acc_id = int(acc_id or 0)
        self.acc_index = int(acc_index or 0)

    @staticmethod
    def _open_trade_context(
        open_sec_trade_context: Any,
        *,
        host: str,
        port: int,
        market: str,
    ) -> Any:
        try:
            return open_sec_trade_context(filter_trdmarket=market, host=host, port=port, ai_type=1)
        except TypeError:
            return open_sec_trade_context(filter_trdmarket=market, host=host, port=port)

    def _context(self) -> Any:
        try:
            from futu import OpenSecTradeContext  # type: ignore
        except ImportError as exc:
            raise FutuProviderError("futu-api is required for FutuOpenDTradeGateway") from exc
        return self._open_trade_context(
            OpenSecTradeContext,
            host=self.host,
            port=self.port,
            market=self.market,
        )

    def get_account(self, *, currency: str) -> dict[str, Any]:
        try:
            from futu import RET_OK, TrdEnv  # type: ignore
        except ImportError as exc:
            raise FutuProviderError("futu-api is required for FutuOpenDTradeGateway") from exc

        ctx = self._context()
        try:
            ret, data = ctx.accinfo_query(
                trd_env=TrdEnv.SIMULATE,
                acc_id=self.acc_id,
                acc_index=self.acc_index,
                refresh_cache=True,
                currency=currency,
            )
            if ret != RET_OK:
                raise FutuProviderError(f"Futu accinfo_query failed: {data}")
            records = df_to_records(data)
            return records[0] if records else {}
        finally:
            ctx.close()

    def get_positions(self) -> list[dict[str, Any]]:
        try:
            from futu import RET_OK, TrdEnv  # type: ignore
        except ImportError as exc:
            raise FutuProviderError("futu-api is required for FutuOpenDTradeGateway") from exc

        ctx = self._context()
        try:
            ret, data = ctx.position_list_query(
                trd_env=TrdEnv.SIMULATE,
                acc_id=self.acc_id,
                acc_index=self.acc_index,
                refresh_cache=True,
            )
            if ret != RET_OK:
                raise FutuProviderError(f"Futu position_list_query failed: {data}")
            return df_to_records(data)
        finally:
            ctx.close()

    def place_order(self, order: OrderRequest) -> dict[str, Any]:
        try:
            from futu import OrderType, RET_OK, TrdEnv, TrdSide  # type: ignore
        except ImportError as exc:
            raise FutuProviderError("futu-api is required for FutuOpenDTradeGateway") from exc

        order_type = OrderType.MARKET if order.order_type == "MARKET" else OrderType.NORMAL
        trd_side = TrdSide.BUY if order.side.value == "BUY" else TrdSide.SELL
        ctx = self._context()
        try:
            ret, data = ctx.place_order(
                price=float(order.price or 0.0),
                qty=float(order.quantity),
                code=normalize_futu_code(order.code),
                trd_side=trd_side,
                order_type=order_type,
                trd_env=TrdEnv.SIMULATE,
                acc_id=self.acc_id,
                acc_index=self.acc_index,
                remark=order.idempotency_key[:32],
            )
            if ret != RET_OK:
                raise FutuProviderError(f"Futu place_order failed: {data}")
            records = df_to_records(data)
            return records[0] if records else {"raw": to_jsonable(data)}
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
