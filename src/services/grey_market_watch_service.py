from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from ..data_provider.sources.futu import FutuMarketDataProvider, FutuOpenDGateway, to_jsonable
from ..model.trading import MarketSnapshot

DEFAULT_PROVIDERS = ("futu", "tiger", "fosun")
SUPPORTED_PROVIDERS = set(DEFAULT_PROVIDERS)
SOURCE = "grey_market_watch"


def parse_providers(raw: str | Iterable[str] | None) -> list[str]:
    if raw is None:
        candidates = DEFAULT_PROVIDERS
    elif isinstance(raw, str):
        candidates = raw.split(",")
    else:
        candidates = list(raw)
    providers: list[str] = []
    for candidate in candidates:
        provider = str(candidate or "").strip().lower()
        if not provider:
            continue
        if provider not in SUPPORTED_PROVIDERS:
            raise ValueError(f"unsupported grey-market provider: {provider}")
        if provider not in providers:
            providers.append(provider)
    return providers or list(DEFAULT_PROVIDERS)


def _safe_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except Exception:
        return None


def _safe_int(value: Any) -> int | None:
    try:
        if value in (None, ""):
            return None
        return int(float(value))
    except Exception:
        return None


def _ratio(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator in (None, 0):
        return None
    return numerator / float(denominator)


def _change_pct(price: float | None, base: float | None) -> float | None:
    if price is None or base in (None, 0):
        return None
    return (price - float(base)) / float(base)


def _normalize_dark_status(value: Any) -> str | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return {0: "NONE", 1: "TRADING", 2: "END"}.get(int(value), str(value))
    text = str(value).strip()
    upper = text.upper()
    if "TRADING" in upper:
        return "TRADING"
    if upper.endswith("END") or upper == "END":
        return "END"
    if upper.endswith("NONE") or upper in {"NONE", "N/A"}:
        return "NONE"
    return text


def _book_side(order_book: dict[str, Any], *keys: str) -> list[Any]:
    for key in keys:
        value = order_book.get(key)
        if isinstance(value, list):
            return value
    return []


def _normalize_book_level(level: Any) -> dict[str, Any]:
    if isinstance(level, dict):
        return {
            "price": _safe_float(level.get("price")),
            "volume": _safe_int(level.get("volume") or level.get("vol")),
            "order_count": _safe_int(level.get("order_count") or level.get("num")),
        }
    if isinstance(level, (list, tuple)):
        return {
            "price": _safe_float(level[0] if len(level) > 0 else None),
            "volume": _safe_int(level[1] if len(level) > 1 else None),
            "order_count": _safe_int(level[2] if len(level) > 2 else None),
        }
    return {"price": None, "volume": None, "order_count": None}


def _summarize_order_book(order_book: Any) -> dict[str, Any] | None:
    if not isinstance(order_book, dict):
        return None
    bids = _book_side(order_book, "bid", "Bid", "bids", "Bids")
    asks = _book_side(order_book, "ask", "Ask", "asks", "Asks")
    best_bid = _normalize_book_level(bids[0]) if bids else None
    best_ask = _normalize_book_level(asks[0]) if asks else None
    return {
        "best_bid": best_bid,
        "best_ask": best_ask,
        "bid_levels": len(bids),
        "ask_levels": len(asks),
    }


def _provider_status(
    *,
    provider: str,
    status: str,
    official_api: bool,
    capability: str,
    reason: str | None = None,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "provider": provider,
        "status": status,
        "official_api": official_api,
        "capability": capability,
    }
    if reason:
        payload["reason"] = reason
    if data:
        payload.update(data)
    return payload


class GreyMarketWatchService:
    def __init__(
        self,
        *,
        futu_market_data: Any | None = None,
        futu_gateway: Any | None = None,
        timezone_name: str = "Asia/Shanghai",
    ) -> None:
        self.timezone = ZoneInfo(timezone_name)
        self.futu_gateway = futu_gateway or FutuOpenDGateway()
        self.futu_market_data = futu_market_data or FutuMarketDataProvider(
            gateway=self.futu_gateway
        )

    def query(
        self,
        *,
        code: str,
        name: str | None = None,
        issue_price: float | None = None,
        providers: Iterable[str] | None = None,
        order_book_depth: int = 5,
    ) -> dict[str, Any]:
        normalized_code = str(code or "").strip().upper()
        provider_names = parse_providers(providers)
        computed_at = datetime.now(self.timezone).isoformat()
        rows = [
            self._query_provider(
                provider=provider,
                code=normalized_code,
                issue_price=issue_price,
                order_book_depth=order_book_depth,
            )
            for provider in provider_names
        ]
        summary = self._summarize(rows)
        status = "ok" if summary["ok_count"] > 0 else "failed"
        return {
            "status": status,
            "source": SOURCE,
            "computed_at": computed_at,
            "request": {
                "code": normalized_code,
                "name": name,
                "issue_price": issue_price,
                "providers": provider_names,
                "order_book_depth": order_book_depth,
            },
            "summary": summary,
            "providers": rows,
        }

    def _query_provider(
        self,
        *,
        provider: str,
        code: str,
        issue_price: float | None,
        order_book_depth: int,
    ) -> dict[str, Any]:
        if provider == "futu":
            return self._query_futu(
                code=code,
                issue_price=issue_price,
                order_book_depth=order_book_depth,
            )
        return _provider_status(
            provider=provider,
            status="unsupported",
            official_api=False,
            capability="pending_official_api_adapter",
            reason="该券商暗盘 OTC 报价尚未接入正式授权 API；不会用网页抓取伪造报价",
        )

    def _query_futu(
        self,
        *,
        code: str,
        issue_price: float | None,
        order_book_depth: int,
    ) -> dict[str, Any]:
        try:
            snapshots = self.futu_market_data.get_market_snapshots([code])
            snapshot = snapshots[0] if snapshots else None
            if snapshot is None:
                return _provider_status(
                    provider="futu",
                    status="failed",
                    official_api=True,
                    capability="snapshot",
                    reason="empty_snapshot",
                )
            order_book = None
            order_book_error = None
            if order_book_depth > 0 and hasattr(self.futu_gateway, "get_order_book"):
                try:
                    order_book = self.futu_gateway.get_order_book(code, num=order_book_depth)
                except Exception as exc:
                    order_book_error = str(exc)
            return _provider_status(
                provider="futu",
                status="ok",
                official_api=True,
                capability="snapshot_order_book",
                data=self._snapshot_payload(
                    snapshot,
                    issue_price=issue_price,
                    order_book=order_book,
                    order_book_error=order_book_error,
                ),
            )
        except Exception as exc:
            return _provider_status(
                provider="futu",
                status="failed",
                official_api=True,
                capability="snapshot_order_book",
                reason=str(exc),
            )

    def _snapshot_payload(
        self,
        snapshot: MarketSnapshot,
        *,
        issue_price: float | None,
        order_book: Any,
        order_book_error: str | None,
    ) -> dict[str, Any]:
        raw = snapshot.raw if isinstance(snapshot.raw, dict) else {}
        price = snapshot.price
        quote = {
            "code": snapshot.code,
            "name": snapshot.name,
            "price": price,
            "bid_price": _safe_float(raw.get("bid_price")),
            "ask_price": _safe_float(raw.get("ask_price")),
            "bid_volume": _safe_int(raw.get("bid_vol")),
            "ask_volume": _safe_int(raw.get("ask_vol")),
            "volume": snapshot.volume,
            "turnover": snapshot.turnover,
            "as_of": snapshot.as_of,
            "dark_status": _normalize_dark_status(raw.get("dark_status")),
            "change_vs_issue_pct": _change_pct(price, issue_price),
            "change_vs_prev_close_pct": _change_pct(price, snapshot.prev_close),
            "bid_ask_spread_pct": _ratio(
                (
                    _safe_float(raw.get("ask_price")) - _safe_float(raw.get("bid_price"))
                    if _safe_float(raw.get("ask_price")) is not None
                    and _safe_float(raw.get("bid_price")) is not None
                    else None
                ),
                price,
            ),
        }
        order_book_summary = _summarize_order_book(order_book)
        payload = {"quote": to_jsonable(quote), "raw": to_jsonable(raw)}
        if order_book_summary:
            payload["order_book"] = to_jsonable(order_book_summary)
        if order_book_error:
            payload["order_book_error"] = order_book_error
        return payload

    def _summarize(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        ok_rows = [row for row in rows if row.get("status") == "ok"]
        prices = []
        for row in ok_rows:
            quote = row.get("quote") if isinstance(row.get("quote"), dict) else {}
            price = _safe_float(quote.get("price"))
            if price is not None:
                prices.append((str(row.get("provider")), price))
        price_spread: dict[str, Any] | None = None
        if prices:
            high_provider, high_price = max(prices, key=lambda item: item[1])
            low_provider, low_price = min(prices, key=lambda item: item[1])
            price_spread = {
                "highest_provider": high_provider,
                "highest_price": high_price,
                "lowest_provider": low_provider,
                "lowest_price": low_price,
                "absolute": high_price - low_price,
                "pct": _ratio(high_price - low_price, low_price),
            }
        return {
            "requested_provider_count": len(rows),
            "ok_count": len(ok_rows),
            "unsupported_count": sum(1 for row in rows if row.get("status") == "unsupported"),
            "failed_count": sum(1 for row in rows if row.get("status") == "failed"),
            "price_spread": to_jsonable(price_spread),
        }
