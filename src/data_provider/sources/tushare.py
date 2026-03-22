"""
Tushare 数据源

使用 Tushare API 获取 A 股和美股股票列表、A股日线数据
"""

import os
from dotenv import load_dotenv
from typing import List, Dict, Any, ClassVar, Optional
import pandas as pd
import tushare as ts

from ..base import BaseStockDataSource
from ...model.contracts import normalize_percent_to_ratio

load_dotenv()


class TushareDataSource(BaseStockDataSource):
    """Tushare 数据源"""

    SOURCE_NAME: str = "Tushare"
    priority: int = 0  # 优先级最高
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
                print(f"⚠️ 获取估值指标失败: {e}")

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
                print(f"⚠️ 获取财务指标失败: {e}")

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
                print(f"⚠️ 获取利润表失败: {e}")

        except Exception as e:
            import traceback

            print(f"❌ Tushare获取A股财务数据失败: {e}")
            traceback.print_exc()

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
