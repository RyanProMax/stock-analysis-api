from __future__ import annotations

from datetime import datetime
import os
from typing import Any, Callable, Optional

import tushare as ts

from ..data_provider.sources.tushare import TushareDataSource


STOCK_INFO_FIELDS = (
    "ts_code,symbol,name,area,industry,market,exchange,list_status,list_date,delist_date"
)
ETF_PREFIXES = ("51", "52", "56", "58", "15", "16", "18")
SH_PREFIXES = ("60", "68", "51", "52", "56", "58")
SZ_PREFIXES = ("00", "30", "15", "16", "18")


class RealtimeQuotePollingService:
    def __init__(
        self,
        *,
        get_pro: Optional[Callable[[], Any]] = None,
        legacy_quote_fetcher: Optional[Callable[[str], Any]] = None,
    ) -> None:
        self._get_pro = get_pro or self._default_get_pro
        self._legacy_quote_fetcher = legacy_quote_fetcher or ts.get_realtime_quotes

    def poll(self, symbols: list[str]) -> dict[str, Any]:
        requested_symbols = self.parse_symbols(symbols)
        pro = self._get_pro()
        computed_at = self._now_iso()
        items = [self._fetch_item(pro, requested_symbol=symbol, computed_at=computed_at) for symbol in requested_symbols]

        success_count = sum(1 for item in items if item["status"] == "ok")
        failed_count = len(items) - success_count

        return {
            "status": "ok" if failed_count == 0 else "partial",
            "computed_at": computed_at,
            "source": "tushare",
            "request": {
                "symbols": requested_symbols,
                "count": len(requested_symbols),
            },
            "summary": {
                "ok": success_count,
                "failed": failed_count,
            },
            "items": items,
        }

    @classmethod
    def parse_symbols(cls, raw_symbols: Any) -> list[str]:
        seen: set[str] = set()
        normalized_symbols: list[str] = []

        if isinstance(raw_symbols, list):
            candidates = raw_symbols
        else:
            candidates = str(raw_symbols or "").split(",")

        for part in candidates:
            candidate = str(part or "").strip().upper()
            if not candidate:
                continue
            dedupe_key = cls._normalize_symbol(candidate) or candidate
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            normalized_symbols.append(candidate)
        return normalized_symbols

    @staticmethod
    def _default_get_pro() -> Any:
        pro = TushareDataSource.get_pro()
        if pro is not None:
            return pro

        token = os.environ.get("TUSHARE_TOKEN", "").strip()
        if not token:
            raise RuntimeError("缺少 TUSHARE_TOKEN，请先在环境变量中配置。")
        raise RuntimeError("Tushare 初始化失败，请检查 TUSHARE_TOKEN / TUSHARE_HTTP_URL。")

    @staticmethod
    def _normalize_symbol(raw_symbol: str) -> Optional[str]:
        normalized = str(raw_symbol or "").strip().upper()
        if normalized.endswith((".SH", ".SZ")):
            normalized = normalized.rsplit(".", 1)[0]
        if normalized.isdigit() and len(normalized) == 6:
            return normalized
        return None

    @classmethod
    def _infer_exchange(cls, symbol: str) -> str:
        if symbol.startswith(SH_PREFIXES):
            return "SH"
        if symbol.startswith(SZ_PREFIXES):
            return "SZ"
        raise ValueError(f"无法根据代码推断交易所: {symbol}")

    @classmethod
    def _build_ts_code(cls, symbol: str) -> str:
        normalized = cls._normalize_symbol(symbol)
        if not normalized:
            raise ValueError(f"非法证券代码: {symbol}")
        return f"{normalized}.{cls._infer_exchange(normalized)}"

    @classmethod
    def _build_legacy_symbol(cls, symbol: str) -> str:
        normalized = cls._normalize_symbol(symbol)
        if not normalized:
            raise ValueError(f"非法证券代码: {symbol}")
        return f"{cls._infer_exchange(normalized).lower()}{normalized}"

    @classmethod
    def _infer_security_type(cls, symbol: str) -> str:
        normalized = cls._normalize_symbol(symbol)
        if not normalized:
            raise ValueError(f"非法证券代码: {symbol}")
        if normalized.startswith(ETF_PREFIXES):
            return "etf"
        return "stock"

    @staticmethod
    def _percent_to_ratio(value: Any) -> Optional[float]:
        if value in (None, ""):
            return None
        try:
            return float(value) / 100.0
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _safe_float(value: Any) -> Optional[float]:
        if value in (None, ""):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _safe_int(value: Any) -> Optional[int]:
        if value in (None, ""):
            return None
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _as_optional_str(value: Any) -> Optional[str]:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    @staticmethod
    def _now_iso() -> str:
        return datetime.now().astimezone().isoformat(timespec="seconds")

    @staticmethod
    def _normalize_exchange_code(value: Optional[str], fallback: str) -> str:
        normalized = str(value or "").strip().upper()
        mapping = {
            "SSE": "SH",
            "SZSE": "SZ",
            "SH": "SH",
            "SZ": "SZ",
        }
        return mapping.get(normalized, fallback)

    def _build_base_info(self, symbol: str, ts_code: str, security_type: str) -> dict[str, Any]:
        return {
            "symbol": symbol,
            "ts_code": ts_code,
            "security_type": security_type,
            "exchange": self._infer_exchange(symbol),
            "name": None,
            "full_name": None,
            "list_status": None,
            "list_date": None,
            "delist_date": None,
            "area": None,
            "industry": None,
            "market": None,
            "index_code": None,
            "index_name": None,
            "setup_date": None,
            "manager_name": None,
            "custodian_name": None,
            "management_fee": None,
            "etf_type": None,
        }

    def _build_stock_info(self, row: Any, symbol: str, ts_code: str) -> dict[str, Any]:
        info = self._build_base_info(symbol, ts_code, "stock")
        info.update(
            {
                "exchange": self._normalize_exchange_code(row.get("exchange"), info["exchange"]),
                "name": self._as_optional_str(row.get("name")),
                "list_status": self._as_optional_str(row.get("list_status")),
                "list_date": self._as_optional_str(row.get("list_date")),
                "delist_date": self._as_optional_str(row.get("delist_date")),
                "area": self._as_optional_str(row.get("area")),
                "industry": self._as_optional_str(row.get("industry")),
                "market": self._as_optional_str(row.get("market")),
            }
        )
        return info

    def _build_etf_info(self, row: Any, symbol: str, ts_code: str) -> dict[str, Any]:
        info = self._build_base_info(symbol, ts_code, "etf")
        info.update(
            {
                "exchange": self._normalize_exchange_code(row.get("exchange"), info["exchange"]),
                "name": self._as_optional_str(row.get("csname")) or self._as_optional_str(row.get("extname")),
                "full_name": self._as_optional_str(row.get("cname")) or self._as_optional_str(row.get("extname")),
                "list_status": self._as_optional_str(row.get("list_status")),
                "list_date": self._as_optional_str(row.get("list_date")),
                "setup_date": self._as_optional_str(row.get("setup_date")),
                "index_code": self._as_optional_str(row.get("index_code")),
                "index_name": self._as_optional_str(row.get("index_name")),
                "manager_name": self._as_optional_str(row.get("mgr_name")),
                "custodian_name": self._as_optional_str(row.get("custod_name")),
                "management_fee": self._safe_float(row.get("mgt_fee")),
                "etf_type": self._as_optional_str(row.get("etf_type")),
            }
        )
        return info

    def _fetch_security_info(
        self,
        pro: Any,
        *,
        symbol: str,
        ts_code: str,
        security_type: str,
    ) -> tuple[dict[str, Any], Optional[str]]:
        base_info = self._build_base_info(symbol, ts_code, security_type)
        try:
            if security_type == "stock":
                dataframe = pro.stock_basic(ts_code=ts_code, fields=STOCK_INFO_FIELDS)
                if dataframe is not None and not dataframe.empty:
                    return self._build_stock_info(dataframe.iloc[0], symbol, ts_code), None
                return base_info, "stock_basic 返回空结果"

            dataframe = pro.etf_basic(ts_code=ts_code)
            if dataframe is not None and not dataframe.empty:
                return self._build_etf_info(dataframe.iloc[0], symbol, ts_code), None
            return base_info, "etf_basic 返回空结果"
        except Exception as exc:
            return base_info, f"{security_type}_info 查询失败: {exc}"

    @staticmethod
    def _ensure_info_name(
        info: Optional[dict[str, Any]], fallback_name: Optional[str]
    ) -> Optional[dict[str, Any]]:
        if not info or info.get("name"):
            return info
        info["name"] = str(fallback_name or "").strip() or None
        return info

    @staticmethod
    def _build_failed_item(
        requested_symbol: str,
        error: str,
        info: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        return {
            "requested_symbol": requested_symbol,
            "status": "failed",
            "error": error,
            "info": info,
            "quote_data": None,
        }

    def _build_quote_from_quotation(self, row: Any, computed_at: str) -> dict[str, Any]:
        return {
            "price": self._safe_float(row.get("price")),
            "change_pct": self._percent_to_ratio(row.get("pct_chg")),
            "change_amount": self._safe_float(row.get("change")),
            "open": self._safe_float(row.get("open")),
            "high": self._safe_float(row.get("high")),
            "low": self._safe_float(row.get("low")),
            "pre_close": self._safe_float(row.get("pre_close")),
            "volume": self._safe_int(row.get("vol")),
            "amount": self._safe_float(row.get("amount")),
            "volume_ratio": self._safe_float(row.get("volume_ratio")),
            "turnover_rate": self._percent_to_ratio(
                row.get("turnover_ratio", row.get("turnover_rate"))
            ),
            "amplitude": self._percent_to_ratio(row.get("amplitude")),
            "as_of": computed_at,
            "source": "tushare",
            "mode": "realtime",
        }

    def _build_quote_from_legacy(self, row: Any, computed_at: str) -> dict[str, Any]:
        price = self._safe_float(row.get("price"))
        pre_close = self._safe_float(row.get("pre_close"))
        change_amount = None
        change_pct = None
        if price is not None and pre_close not in (None, 0):
            change_amount = round(price - float(pre_close), 4)
            change_pct = round(change_amount / float(pre_close), 6)

        volume = self._safe_int(row.get("volume"))
        if volume is not None:
            volume = volume // 100

        return {
            "price": price,
            "change_pct": change_pct,
            "change_amount": change_amount,
            "open": self._safe_float(row.get("open")),
            "high": self._safe_float(row.get("high")),
            "low": self._safe_float(row.get("low")),
            "pre_close": pre_close,
            "volume": volume,
            "amount": self._safe_float(row.get("amount")),
            "volume_ratio": None,
            "turnover_rate": None,
            "amplitude": None,
            "as_of": computed_at,
            "source": "tushare",
            "mode": "legacy_realtime",
        }

    def _fetch_item(self, pro: Any, *, requested_symbol: str, computed_at: str) -> dict[str, Any]:
        symbol = self._normalize_symbol(requested_symbol)
        if not symbol:
            return self._build_failed_item(requested_symbol, f"非法证券代码: {requested_symbol}")

        try:
            ts_code = self._build_ts_code(symbol)
            security_type = self._infer_security_type(symbol)
        except ValueError as exc:
            return self._build_failed_item(requested_symbol, str(exc))

        info, info_error = self._fetch_security_info(
            pro,
            symbol=symbol,
            ts_code=ts_code,
            security_type=security_type,
        )

        errors: list[str] = []
        quote_data = None
        quote_name = None

        try:
            dataframe = pro.quotation(ts_code=ts_code)
            if dataframe is not None and not dataframe.empty:
                row = dataframe.iloc[0]
                quote_name = str(row.get("name", "") or "")
                quote_data = self._build_quote_from_quotation(row, computed_at)
            else:
                errors.append("quotation 返回空结果")
        except Exception as exc:
            errors.append(f"quotation 查询失败: {exc}")

        if quote_data is None:
            try:
                legacy_symbol = self._build_legacy_symbol(symbol)
                dataframe = self._legacy_quote_fetcher(legacy_symbol)
                if dataframe is not None and not dataframe.empty:
                    row = dataframe.iloc[0]
                    quote_name = str(row.get("name", "") or quote_name or "")
                    quote_data = self._build_quote_from_legacy(row, computed_at)
                else:
                    errors.append("legacy realtime 返回空结果")
            except Exception as exc:
                errors.append(f"legacy realtime 查询失败: {exc}")

        info = self._ensure_info_name(info, quote_name)

        if quote_data is not None:
            return {
                "requested_symbol": requested_symbol,
                "status": "ok",
                "error": None,
                "info": info,
                "quote_data": quote_data,
            }

        if info_error:
            errors.insert(0, info_error)
        return self._build_failed_item(requested_symbol, "；".join(errors), info=info)


realtime_quote_polling_service = RealtimeQuotePollingService()
