"""
Tushare 数据源

使用 Tushare API 获取 A 股和美股股票列表、A股日线数据
"""

import logging
import os
from dotenv import load_dotenv
from typing import List, Dict, Any, ClassVar, Optional
import pandas as pd
import tushare as ts

from ..base import BaseStockDataSource
from ..realtime_types import UnifiedRealtimeQuote, RealtimeSource
from ...model.contracts import normalize_percent_to_ratio

load_dotenv()


logger = logging.getLogger(__name__)


class TushareDataSource(BaseStockDataSource):
    """Tushare 数据源"""

    SOURCE_NAME: str = "Tushare"
    priority: int = 0  # 优先级最高
    ETF_SH_PREFIXES: ClassVar[tuple[str, ...]] = ("51", "52", "56", "58")
    ETF_SZ_PREFIXES: ClassVar[tuple[str, ...]] = ("15", "16", "18")
    TOKEN: ClassVar[str] = os.environ.get("TUSHARE_TOKEN", "")
    TUSHARE_HTTP_URL: ClassVar[str] = os.environ.get("TUSHARE_HTTP_URL", "")
    _pro: ClassVar[Optional[Any]] = None

    @classmethod
    def get_pro(cls) -> Optional[Any]:
        """获取 tushare pro 实例（懒加载）"""
        token = os.environ.get("TUSHARE_TOKEN", cls.TOKEN or "")
        url = os.environ.get("TUSHARE_HTTP_URL", cls.TUSHARE_HTTP_URL or "")

        if cls._pro is not None and cls.TOKEN == token and cls.TUSHARE_HTTP_URL == url:
            return cls._pro

        cls.TOKEN = token
        cls.TUSHARE_HTTP_URL = url
        cls._pro = None

        if not token:
            return None

        try:
            cls._pro = ts.pro_api("anything")
            setattr(cls._pro, "_DataApi__token", token)
            if url:
                setattr(cls._pro, "_DataApi__http_url", url)
            print("✓ Tushare 初始化成功")
            return cls._pro
        except Exception as e:
            print(f"⚠️ Tushare 初始化失败: {e}")
            return None

    # ==================== 日线数据实现 ====================

    def get_realtime_quote(self, symbol: str) -> Optional[UnifiedRealtimeQuote]:
        """获取 A 股实时行情，优先 Pro realtime，失败后降级到旧版接口。"""
        normalized = str(symbol).strip().upper()
        if not normalized or any(ch.isalpha() for ch in normalized):
            return None

        pro = self.get_pro()
        if pro is None:
            return None

        ts_symbol = self._build_cn_ts_code(normalized)

        # 优先尝试 Pro 实时接口；若源端未开通或不可用，则继续降级。
        try:
            df = self._safe_query_dataframe(pro, "quotation", ts_code=ts_symbol)
            if df is not None and not df.empty:
                row = df.iloc[0]
                return UnifiedRealtimeQuote(
                    code=normalized,
                    name=str(row.get("name", "") or ""),
                    source=RealtimeSource.TUSHARE,
                    price=self._safe_float(row.get("price")),
                    change_pct=self._safe_float(row.get("pct_chg")),
                    change_amount=self._safe_float(row.get("change")),
                    volume=self._safe_int(row.get("vol")),
                    amount=self._safe_float(row.get("amount")),
                    volume_ratio=self._safe_float(row.get("volume_ratio")),
                    turnover_rate=self._safe_float(
                        row.get("turnover_ratio", row.get("turnover_rate"))
                    ),
                    amplitude=self._safe_float(row.get("amplitude")),
                    open_price=self._safe_float(row.get("open")),
                    high=self._safe_float(row.get("high")),
                    low=self._safe_float(row.get("low")),
                    pre_close=self._safe_float(row.get("pre_close")),
                    pe_ratio=self._safe_float(row.get("pe")),
                    pb_ratio=self._safe_float(row.get("pb")),
                    total_mv=self._safe_float(row.get("total_mv")),
                    circ_mv=self._safe_float(row.get("circ_mv")),
                )
        except Exception:
            pass

        try:
            legacy_symbol = self._build_legacy_realtime_symbol(normalized)
            df = ts.get_realtime_quotes(legacy_symbol)
            if df is None or df.empty:
                return None

            row = df.iloc[0]
            price = self._safe_float(row.get("price"))
            pre_close = self._safe_float(row.get("pre_close"))
            change_amount = None
            change_pct = None
            if price is not None and pre_close not in (None, 0):
                change_amount = round(price - float(pre_close), 4)
                change_pct = round((change_amount / float(pre_close)) * 100.0, 4)

            volume = self._safe_int(row.get("volume"))
            if volume is not None:
                volume = volume // 100

            return UnifiedRealtimeQuote(
                code=normalized,
                name=str(row.get("name", "") or ""),
                source=RealtimeSource.TUSHARE,
                price=price,
                change_pct=change_pct,
                change_amount=change_amount,
                volume=volume,
                amount=self._safe_float(row.get("amount")),
                open_price=self._safe_float(row.get("open")),
                high=self._safe_float(row.get("high")),
                low=self._safe_float(row.get("low")),
                pre_close=pre_close,
            )
        except Exception:
            return None

    def _fetch_raw_daily(self, symbol: str) -> Optional[pd.DataFrame]:
        """获取原始日线数据"""
        pro = self.get_pro()
        if pro is None:
            return None

        try:
            # Tushare 需要带交易所前缀的股票代码
            ts_symbol = self._build_cn_ts_code(symbol)
            df = pro.daily(ts_code=ts_symbol, start_date="20100101")
            if df is not None and not df.empty:
                df = df.sort_values("trade_date").reset_index(drop=True)
                return df
        except Exception as e:
            print(f"⚠️ Tushare 获取日线失败 [{symbol}]: {e}")

        return None

    def _normalize_daily(self, df: pd.DataFrame, symbol: str) -> pd.DataFrame:
        """标准化日线数据"""
        df = df.copy()

        # Tushare 列名映射
        df.rename(
            columns={
                "trade_date": "date",
                "vol": "volume",
            },
            inplace=True,
        )

        # 删除不需要的列
        cols_to_drop = ["ts_code", "pre_close", "change", "pct_chg"]
        for col in cols_to_drop:
            if col in df.columns:
                df.drop(columns=[col], inplace=True)

        return df

    # ==================== 股票列表 ====================

    def fetch_a_stocks(self) -> List[Dict[str, Any]]:
        """获取 A 股股票列表"""
        pro = self.get_pro()
        if pro is None:
            return []

        df = pro.stock_basic(exchange="", list_status="L")
        rows = self.normalize_dataframe(df)
        for row in rows:
            ts_code = str(row.get("ts_code") or "").strip().upper()
            row["exchange"] = row.get("exchange") or self._infer_exchange_from_ts_code(ts_code)
        return rows

    def fetch_cn_etfs(self) -> List[Dict[str, Any]]:
        """获取 A 股 ETF 列表。"""
        pro = self.get_pro()
        if pro is None:
            return []

        df = None
        for query_kwargs in ({"list_status": "L"}, {"status": "L"}, {}):
            df = self._safe_query_dataframe(pro, "etf_basic", **query_kwargs)
            if df is not None and not df.empty:
                break
        if df is None or df.empty:
            return []

        etf_rows = self.normalize_dataframe(df)
        expected_symbols = {
            (
                str(row.get("symbol") or "").strip().upper()
                or str(row.get("ts_code") or "").strip().upper().split(".")[0]
            )
            for row in etf_rows
        }
        fund_basic_map = self._fetch_cn_fund_basic_map(pro, expected_symbols=expected_symbols)
        etfs: List[Dict[str, Any]] = []
        for row in etf_rows:
            raw_ts_code = str(row.get("ts_code") or "").strip().upper()
            symbol = str(row.get("symbol") or "").strip().upper()
            if not symbol and raw_ts_code:
                symbol = raw_ts_code.split(".")[0]
            if not symbol:
                continue

            fund_row = dict(fund_basic_map.get(symbol, {}))
            name = self._pick_cn_etf_name(
                symbol,
                raw_ts_code=raw_ts_code,
                row=row,
                fund_row=fund_row,
            )
            if name == symbol:
                fallback_fund_row = self._fetch_cn_fund_basic_row(
                    pro,
                    symbol=symbol,
                    raw_ts_code=raw_ts_code,
                )
                if fallback_fund_row:
                    fund_row.update(fallback_fund_row)
            exchange = self._normalize_cn_exchange(
                fund_row.get("market") or row.get("exchange"),
                ts_code=fund_row.get("ts_code") or raw_ts_code,
                symbol=symbol,
            )
            ts_code = self._build_cn_ts_code(symbol)
            name = self._pick_cn_etf_name(
                symbol,
                raw_ts_code=raw_ts_code,
                row=row,
                fund_row=fund_row,
            )
            fullname = self._pick_nonempty(
                fund_row.get("fullname"),
                fund_row.get("fund_fullname"),
                row.get("fullname"),
                row.get("fund_fullname"),
                name,
            )
            list_date = self._pick_nonempty(
                fund_row.get("list_date"),
                row.get("list_date"),
                fund_row.get("found_date"),
                row.get("found_date"),
                fund_row.get("setup_date"),
                row.get("setup_date"),
            )

            etf_payload = {
                "symbol": symbol,
                "ts_code": ts_code,
                "name": name,
                "area": row.get("area") or fund_row.get("area"),
                "industry": None,
                "market": "ETF",
                "exchange": exchange,
                "list_date": list_date,
                "fullname": fullname,
            }
            for key in ("fund_type", "invest_type", "benchmark", "status", "management", "custodian"):
                value = fund_row.get(key) or row.get(key)
                if value not in (None, ""):
                    etf_payload[key] = value
            etfs.append(etf_payload)

        return etfs

    def _fetch_cn_fund_basic_map(
        self,
        pro: Any,
        *,
        expected_symbols: set[str],
    ) -> Dict[str, Dict[str, Any]]:
        df = None
        for query_kwargs in (
            {"market": "E", "status": "L"},
            {"market": "E"},
            {},
        ):
            df = self._safe_query_dataframe(pro, "fund_basic", **query_kwargs)
            if df is not None and not df.empty:
                break
        if df is None or df.empty:
            return {}

        fund_map: Dict[str, Dict[str, Any]] = {}
        for row in self.normalize_dataframe(df):
            ts_code = str(row.get("ts_code") or "").strip().upper()
            symbol = str(row.get("symbol") or "").strip().upper()
            if not symbol and ts_code:
                symbol = ts_code.split(".")[0]
            if (
                not symbol
                or symbol not in expected_symbols
                or not self._is_cn_etf_symbol(symbol)
            ):
                continue
            normalized_row = dict(row)
            normalized_row["ts_code"] = self._build_cn_ts_code(symbol)
            normalized_row["exchange"] = self._normalize_cn_exchange(
                row.get("market") or row.get("exchange"),
                ts_code=ts_code,
                symbol=symbol,
            )
            fund_map[symbol] = normalized_row
        return fund_map

    def _fetch_cn_fund_basic_row(
        self,
        pro: Any,
        *,
        symbol: str,
        raw_ts_code: str,
    ) -> Dict[str, Any]:
        candidates: list[str] = []
        for candidate in (raw_ts_code, f"{symbol}.OF", self._build_cn_ts_code(symbol)):
            text = str(candidate or "").strip().upper()
            if text and text not in candidates:
                candidates.append(text)

        for ts_code in candidates:
            df = self._safe_query_dataframe(pro, "fund_basic", ts_code=ts_code)
            if df is None or df.empty:
                continue
            row = self.normalize_dataframe(df.iloc[[0]])[0]
            row["ts_code"] = ts_code
            row["exchange"] = self._normalize_cn_exchange(
                row.get("market") or row.get("exchange"),
                ts_code=ts_code,
                symbol=symbol,
            )
            return row
        return {}

    def fetch_us_stocks(self) -> List[Dict[str, Any]]:
        """获取美股股票列表"""
        pro = self.get_pro()
        if pro is None:
            return []

        df = pro.us_basic()
        if df is None or df.empty:
            return []

        stocks = []
        for row in self.normalize_dataframe(df):
            ts_code = str(row.get("ts_code") or "").strip().upper()
            symbol = str(row.get("symbol") or "").strip().upper()
            if not symbol and ts_code:
                symbol = ts_code.split(".")[0]
            if not symbol:
                continue
            row["symbol"] = symbol
            row["ts_code"] = ts_code or f"{symbol}.US"
            row["market"] = row.get("market") or "美股"
            row["exchange"] = row.get("exchange") or "NASDAQ"
            stocks.append(row)
        return stocks

    @classmethod
    def fetch_cn_stock_basic(cls, symbol: str) -> Optional[Dict[str, Any]]:
        """按单只股票获取 A 股主数据，用于单股同步时补齐 symbol 元信息。"""
        pro = cls.get_pro()
        if pro is None:
            return None

        ts_symbol = cls._build_cn_ts_code(symbol)
        try:
            df = pro.stock_basic(ts_code=ts_symbol, list_status="L")
            if df is None or df.empty:
                return None
            row = cls.normalize_dataframe(df.iloc[[0]])[0]
            row["symbol"] = str(row.get("symbol") or symbol).strip().upper()
            row["ts_code"] = str(row.get("ts_code") or ts_symbol).strip().upper()
            row["market"] = row.get("market") or "A股"
            row["exchange"] = row.get("exchange") or cls._infer_exchange_from_ts_code(row["ts_code"])
            return row
        except Exception:
            return None

    def is_available(self, market: str) -> bool:
        """检查数据源是否可用"""
        if not self.TOKEN:
            print("⚠️ Tushare Token为空，跳过")
            return False
        pro = self.get_pro()
        return pro is not None

    @classmethod
    def fetch_daily_with_extras(
        cls,
        symbol: str,
        market: str = "cn",
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> Optional[pd.DataFrame]:
        """获取带扩展字段的日线数据，优先服务于 SQLite 落库。"""
        normalized_market = "us" if str(market).lower() == "us" else "cn"
        if normalized_market != "cn":
            return None

        pro = cls.get_pro()
        if pro is None:
            return None

        ts_symbol = cls._build_cn_ts_code(symbol)
        start_text = cls._format_tushare_date(start_date) or "20100101"
        end_text = cls._format_tushare_date(end_date)

        try:
            daily_df = pro.daily(ts_code=ts_symbol, start_date=start_text, end_date=end_text)
            if daily_df is None or daily_df.empty:
                return None
            daily_df = daily_df.sort_values("trade_date").reset_index(drop=True)

            daily_basic_df = cls._safe_query_dataframe(
                pro,
                "daily_basic",
                ts_code=ts_symbol,
                start_date=start_text,
                end_date=end_text,
            )
            adj_df = cls._safe_query_dataframe(
                pro,
                "adj_factor",
                ts_code=ts_symbol,
                start_date=start_text,
                end_date=end_text,
            )
            limit_df = cls._safe_query_dataframe(
                pro,
                "stk_limit",
                ts_code=ts_symbol,
                start_date=start_text,
                end_date=end_text,
            )
            suspend_df = cls._safe_query_dataframe(
                pro,
                "suspend_d",
                ts_code=ts_symbol,
                start_date=start_text,
                end_date=end_text,
            )

            if adj_df is not None and not adj_df.empty and "trade_date" in adj_df.columns:
                daily_df = daily_df.merge(
                    adj_df[["trade_date", "adj_factor"]].drop_duplicates("trade_date"),
                    on="trade_date",
                    how="left",
                )

            if limit_df is not None and not limit_df.empty and "trade_date" in limit_df.columns:
                keep_columns = [col for col in ("trade_date", "up_limit", "down_limit") if col in limit_df.columns]
                daily_df = daily_df.merge(
                    limit_df[keep_columns].drop_duplicates("trade_date"),
                    on="trade_date",
                    how="left",
                )

            if daily_basic_df is not None and not daily_basic_df.empty and "trade_date" in daily_basic_df.columns:
                keep_columns = [
                    col
                    for col in (
                        "trade_date",
                        "turnover_rate",
                        "turnover_rate_f",
                        "volume_ratio",
                        "pe",
                        "pe_ttm",
                        "pb",
                        "ps",
                        "ps_ttm",
                        "dv_ratio",
                        "dv_ttm",
                        "float_share",
                        "free_share",
                        "total_share",
                        "circ_mv",
                        "total_mv",
                    )
                    if col in daily_basic_df.columns
                ]
                daily_df = daily_df.merge(
                    daily_basic_df[keep_columns].drop_duplicates("trade_date"),
                    on="trade_date",
                    how="left",
                )

            daily_df["is_suspended"] = 0
            suspend_dates = cls._extract_suspend_dates(suspend_df)
            if suspend_dates:
                daily_df.loc[daily_df["trade_date"].isin(suspend_dates), "is_suspended"] = 1

            daily_df["ts_code"] = ts_symbol
            return daily_df
        except Exception as e:
            print(f"⚠️ Tushare 获取扩展日线失败 [{symbol}]: {e}")
            return None

    @classmethod
    def get_cn_trade_window(
        cls,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> tuple[Optional[str], Optional[str]]:
        open_dates = cls.list_cn_open_trade_dates(start_date=start_date, end_date=end_date)
        if not open_dates:
            return start_date, None
        return open_dates[0], open_dates[-1]

    @classmethod
    def list_cn_open_trade_dates(
        cls,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> list[str]:
        pro = cls.get_pro()
        if pro is None:
            return []

        today_text = pd.Timestamp.utcnow().strftime("%Y-%m-%d")
        start_text = cls._format_tushare_date(start_date) or cls._format_tushare_date(today_text)
        end_text = cls._format_tushare_date(end_date) or cls._format_tushare_date(today_text)

        try:
            cal_df = pro.trade_cal(exchange="", start_date=start_text, end_date=end_text, is_open="1")
        except Exception:
            return []

        if cal_df is None or cal_df.empty or "cal_date" not in cal_df.columns:
            return []

        cal_dates = cal_df["cal_date"].dropna().astype(str).sort_values()
        if cal_dates.empty:
            return []
        return [pd.Timestamp(value).strftime("%Y-%m-%d") for value in cal_dates.tolist()]

    @classmethod
    def is_cn_market_open_on(cls, trade_date: str) -> Optional[bool]:
        pro = cls.get_pro()
        if pro is None:
            return None

        trade_date_text = cls._format_tushare_date(trade_date)
        if not trade_date_text:
            return None

        try:
            cal_df = pro.trade_cal(exchange="", start_date=trade_date_text, end_date=trade_date_text)
        except Exception:
            return None

        if cal_df is None or cal_df.empty or "is_open" not in cal_df.columns:
            return None
        return str(cal_df.iloc[0].get("is_open") or "0") == "1"

    @classmethod
    def fetch_cn_daily_basic_by_trade_date(cls, trade_date: str) -> Optional[pd.DataFrame]:
        pro = cls.get_pro()
        if pro is None:
            return None

        trade_date_text = cls._format_tushare_date(trade_date)
        if not trade_date_text:
            return None

        daily_basic_df = cls._safe_query_dataframe(
            pro,
            "daily_basic",
            trade_date=trade_date_text,
        )
        if daily_basic_df is None or daily_basic_df.empty:
            return None

        keep_columns = [
            col
            for col in (
                "ts_code",
                "trade_date",
                "turnover_rate",
                "turnover_rate_f",
                "volume_ratio",
                "pe",
                "pe_ttm",
                "pb",
                "ps",
                "ps_ttm",
                "dv_ratio",
                "dv_ttm",
                "float_share",
                "free_share",
                "total_share",
                "circ_mv",
                "total_mv",
            )
            if col in daily_basic_df.columns
        ]
        return daily_basic_df[keep_columns].copy()

    @classmethod
    def fetch_cn_suspend_dates(
        cls,
        symbol: str,
        *,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> set[str]:
        pro = cls.get_pro()
        if pro is None:
            return set()

        ts_symbol = cls._build_cn_ts_code(symbol)
        suspend_df = cls._safe_query_dataframe(
            pro,
            "suspend_d",
            ts_code=ts_symbol,
            start_date=cls._format_tushare_date(start_date),
            end_date=cls._format_tushare_date(end_date),
        )
        return cls._extract_suspend_dates(suspend_df)

    @staticmethod
    def _safe_query_dataframe(pro: Any, method_name: str, **kwargs: Any) -> Optional[pd.DataFrame]:
        try:
            method = getattr(pro, method_name)
            result = method(**kwargs)
            return result if isinstance(result, pd.DataFrame) else None
        except Exception:
            return None

    @staticmethod
    def _extract_suspend_dates(df: Optional[pd.DataFrame]) -> set[str]:
        if df is None or df.empty:
            return set()

        for candidate in ("trade_date", "suspend_date", "date"):
            if candidate in df.columns:
                return {
                    pd.Timestamp(value).strftime("%Y-%m-%d")
                    for value in df[candidate].dropna().tolist()
                }
        return set()

    @staticmethod
    def _format_tushare_date(value: Optional[str]) -> Optional[str]:
        if not value:
            return None
        try:
            return pd.Timestamp(value).strftime("%Y%m%d")
        except Exception:
            return None

    @staticmethod
    def _build_cn_ts_code(symbol: str) -> str:
        normalized = str(symbol).strip().upper()
        if normalized.startswith(TushareDataSource.ETF_SH_PREFIXES):
            return f"{normalized}.SH"
        if normalized.startswith(TushareDataSource.ETF_SZ_PREFIXES):
            return f"{normalized}.SZ"
        if normalized.startswith(("4", "8", "92")):
            return f"{normalized}.BJ"
        return f"{normalized}.SH" if normalized.startswith("6") else f"{normalized}.SZ"

    @staticmethod
    def _infer_exchange_from_ts_code(ts_code: str) -> Optional[str]:
        text = str(ts_code or "").upper()
        if text.endswith(".BJ"):
            return "BSE"
        if text.endswith(".SH"):
            return "SSE"
        if text.endswith(".SZ"):
            return "SZSE"
        return None

    @classmethod
    def _normalize_cn_exchange(
        cls,
        exchange: Any,
        *,
        ts_code: Optional[str] = None,
        symbol: Optional[str] = None,
    ) -> Optional[str]:
        text = str(exchange or "").strip().upper()
        if text in {"SSE", "SH", "SHSE"}:
            return "SSE"
        if text in {"SZSE", "SZ"}:
            return "SZSE"
        if text in {"BSE", "BJ"}:
            return "BSE"
        inferred = cls._infer_exchange_from_ts_code(ts_code or "")
        if inferred:
            return inferred
        if symbol:
            return cls._infer_cn_exchange_from_symbol(symbol)
        return None

    @classmethod
    def _infer_cn_exchange_from_symbol(cls, symbol: str) -> Optional[str]:
        normalized = str(symbol or "").strip().upper()
        if normalized.startswith(cls.ETF_SH_PREFIXES):
            return "SSE"
        if normalized.startswith(cls.ETF_SZ_PREFIXES):
            return "SZSE"
        if normalized.startswith(("4", "8", "92")):
            return "BSE"
        if normalized.startswith("6"):
            return "SSE"
        if normalized.startswith(("0", "2", "3")):
            return "SZSE"
        return None

    @classmethod
    def _is_cn_etf_symbol(cls, symbol: str) -> bool:
        normalized = str(symbol or "").strip().upper()
        return (
            len(normalized) == 6
            and normalized.isdigit()
            and (
                normalized.startswith(cls.ETF_SH_PREFIXES)
                or normalized.startswith(cls.ETF_SZ_PREFIXES)
            )
        )

    @classmethod
    def _pick_cn_etf_name(
        cls,
        symbol: str,
        *,
        raw_ts_code: str,
        row: Dict[str, Any],
        fund_row: Dict[str, Any],
    ) -> str:
        candidates = (
            fund_row.get("name"),
            row.get("name"),
            row.get("fund_name"),
            fund_row.get("fund_name"),
            fund_row.get("fullname"),
            fund_row.get("fund_fullname"),
            row.get("fullname"),
            row.get("fund_fullname"),
        )
        invalid_names = {str(symbol).strip().upper()}
        if raw_ts_code:
            invalid_names.add(raw_ts_code.strip().upper())
            invalid_names.add(raw_ts_code.strip().upper().split(".")[0])
        for candidate in candidates:
            text = str(candidate or "").strip()
            if text and text.upper() not in invalid_names:
                return text
        return str(symbol).strip().upper()

    @staticmethod
    def _pick_nonempty(*values: Any) -> Optional[str]:
        for value in values:
            text = str(value or "").strip()
            if text:
                return text
        return None

    @staticmethod
    def _build_legacy_realtime_symbol(symbol: str) -> str:
        normalized = str(symbol).strip().upper()
        if normalized == "000001":
            return "sh000001"
        if normalized in {"399001", "399006"}:
            return f"sz{normalized}"
        if normalized == "000300":
            return "sh000300"
        if normalized.startswith(("4", "8", "92")):
            return f"bj{normalized.lower()}"
        return normalized.lower()

    @staticmethod
    def _safe_float(value: Any) -> Optional[float]:
        try:
            if value is None or pd.isna(value):
                return None
            text = str(value).strip().replace(",", "")
            if not text:
                return None
            return float(text)
        except Exception:
            return None

    @staticmethod
    def _safe_int(value: Any) -> Optional[int]:
        try:
            if value is None or pd.isna(value):
                return None
            text = str(value).strip().replace(",", "")
            if not text:
                return None
            return int(float(text))
        except Exception:
            return None

    # ==================== 财务数据 ====================

    @classmethod
    def get_daily_data(cls, symbol: str) -> Optional[pd.DataFrame]:
        """
        获取 A 股日线数据（兼容旧接口）

        Args:
            symbol: 股票代码（6位，如 600519）

        Returns:
            包含日线数据的 DataFrame，失败返回 None
        """
        instance = cls()
        return BaseStockDataSource.get_daily_data(instance, symbol)

    @classmethod
    def get_cn_financial_data(cls, symbol: str) -> tuple[Optional[dict], dict]:
        """
        使用 Tushare Pro 获取A股财务数据

        Args:
            symbol: A股代码（6位，如 600519）

        Returns:
            (财务数据字典, 原始数据字典)
        """
        financial_data = {}
        raw_data = {}

        pro = cls.get_pro()
        if pro is None:
            return None, raw_data

        try:
            # Tushare 需要带交易所前缀的股票代码
            ts_symbol = cls._build_cn_ts_code(symbol)

            # 获取估值指标 (PE/PB)
            try:
                df_basic = pro.daily_basic(
                    ts_code=ts_symbol, fields="ts_code,trade_date,pe,pe_ttm,pb"
                )
                if df_basic is not None and not df_basic.empty:
                    raw_data["daily_basic"] = df_basic.iloc[0].to_dict()
                    latest = df_basic.iloc[0]
                    # 优先使用市盈率TTM
                    if pd.notna(latest.get("pe_ttm")) and latest["pe_ttm"] > 0:
                        financial_data["pe_ratio"] = float(latest["pe_ttm"])
                    elif pd.notna(latest.get("pe")) and latest["pe"] > 0:
                        financial_data["pe_ratio"] = float(latest["pe"])
                    # 市净率
                    if pd.notna(latest.get("pb")) and latest["pb"] > 0:
                        financial_data["pb_ratio"] = float(latest["pb"])
            except Exception as e:
                cls._log_financial_issue(symbol, "daily_basic", e)

            # 获取财务指标 (ROE/资产负债率)
            try:
                df_indicator = pro.fina_indicator(
                    ts_code=ts_symbol,
                    fields="ts_code,ann_date,end_date,roe,debt_to_assets",
                )
                if df_indicator is not None and not df_indicator.empty:
                    raw_data["fina_indicator"] = df_indicator.iloc[0].to_dict()
                    latest = df_indicator.iloc[0]
                    # ROE（净资产收益率）
                    if pd.notna(latest.get("roe")):
                        financial_data["roe"] = float(latest["roe"])
                    # 资产负债率
                    if pd.notna(latest.get("debt_to_assets")):
                        financial_data["debt_ratio"] = float(latest["debt_to_assets"])
                    raw_data["fina_indicator_meta"] = {
                        "ann_date": latest.get("ann_date"),
                        "end_date": latest.get("end_date"),
                        "roe_ratio": normalize_percent_to_ratio(latest.get("roe")),
                        "debt_to_assets_ratio": normalize_percent_to_ratio(
                            latest.get("debt_to_assets")
                        ),
                    }
            except Exception as e:
                cls._log_financial_issue(symbol, "fina_indicator", e)

            # 获取利润表用于计算营收增长率
            try:
                df_income = pro.income(
                    ts_code=ts_symbol, fields="ts_code,ann_date,end_date,revenue"
                )
                if df_income is not None and not df_income.empty:
                    raw_data["income"] = df_income.head(2).to_dict("records")
                    revenue_growth = cls._compute_same_period_revenue_growth(df_income)
                    if revenue_growth is not None:
                        financial_data["revenue_growth"] = float(revenue_growth * 100.0)
                    raw_data["income_meta"] = cls._extract_income_meta(df_income, revenue_growth)
            except Exception as e:
                cls._log_financial_issue(symbol, "income", e)

        except Exception as e:
            cls._log_financial_issue(symbol, "financial_data", e)

        return financial_data if financial_data else None, raw_data

    @staticmethod
    def _compute_same_period_revenue_growth(df_income: pd.DataFrame) -> Optional[float]:
        if df_income is None or df_income.empty:
            return None
        df = df_income.copy()
        df["end_date"] = df["end_date"].astype(str)
        latest = df.iloc[0]
        latest_end = latest.get("end_date")
        latest_revenue = latest.get("revenue")
        if pd.isna(latest_end) or pd.isna(latest_revenue):
            return None
        latest_end_str = str(latest_end)
        if len(latest_end_str) != 8:
            return None
        latest_md = latest_end_str[4:]
        latest_year = int(latest_end_str[:4])

        comparable = df[df["end_date"].astype(str).str.endswith(latest_md)]
        comparable = comparable[comparable["end_date"].astype(str) != latest_end_str]
        if comparable.empty:
            return None

        def _distance(end_date: str) -> int:
            try:
                return abs(int(str(end_date)[:4]) - (latest_year - 1))
            except Exception:
                return 9999

        comparable = comparable.assign(_distance=comparable["end_date"].astype(str).map(_distance))
        comparable = comparable.sort_values(["_distance", "end_date"])
        previous = comparable.iloc[0]
        prev_revenue = previous.get("revenue")
        if pd.isna(prev_revenue) or float(prev_revenue) <= 0:
            return None
        return (float(latest_revenue) - float(prev_revenue)) / float(prev_revenue)

    @staticmethod
    def _extract_income_meta(
        df_income: pd.DataFrame, revenue_growth_ratio: Optional[float]
    ) -> Dict[str, Any]:
        if df_income is None or df_income.empty:
            return {"status": "unavailable"}
        latest = df_income.iloc[0]
        meta = {
            "latest_ann_date": latest.get("ann_date"),
            "latest_end_date": latest.get("end_date"),
            "revenue_growth_status": "available" if revenue_growth_ratio is not None else "unavailable",
        }
        if revenue_growth_ratio is not None:
            meta["revenue_growth_ratio"] = revenue_growth_ratio
        return meta

    @staticmethod
    def _log_financial_issue(symbol: str, stage: str, exc: Exception) -> None:
        logger.warning(
            "Tushare A股财务数据不可用 symbol=%s stage=%s error_type=%s error=%s",
            symbol,
            stage,
            type(exc).__name__,
            str(exc),
        )
