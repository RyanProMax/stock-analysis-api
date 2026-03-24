"""
股票数据源基类

定义所有数据源的统一接口和返回格式
"""

import logging
import random
import time
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional, cast
import pandas as pd
from .realtime_types import UnifiedRealtimeQuote


logger = logging.getLogger(__name__)


class BaseStockDataSource(ABC):
    """股票数据源基类"""

    # 缓存实例
    _instances: Dict[str, "BaseStockDataSource"] = {}

    # 数据源名称
    SOURCE_NAME: str = "base"

    # 标准列名常量
    STANDARD_DAILY_COLUMNS: List[str] = [
        "date",
        "open",
        "high",
        "low",
        "close",
        "volume",
    ]

    # User-Agent 池（用于防封禁）
    USER_AGENTS: List[str] = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    ]

    def __init__(self):
        # 内存缓存：{market: [stocks]}
        self._cache: Dict[str, List[Dict[str, Any]]] = {}

    @classmethod
    def get_instance(cls) -> "BaseStockDataSource":
        """获取单例实例"""
        if cls.SOURCE_NAME not in cls._instances:
            cls._instances[cls.SOURCE_NAME] = cls()
        return cls._instances[cls.SOURCE_NAME]

    def is_cache_valid(self, market: str) -> bool:
        """检查进程内缓存是否有效"""
        return market in self._cache and len(self._cache[market]) > 0

    def update_cache(self, market: str, stocks: List[Dict[str, Any]]) -> None:
        """更新进程内缓存"""
        if len(stocks) > 0:
            self._cache[market] = stocks

    def get_cached(self, market: str) -> Optional[List[Dict[str, Any]]]:
        """获取进程内缓存数据"""
        if self.is_cache_valid(market):
            return self._cache[market]
        return None

    def clear_cache(self, market: str) -> None:
        """清除缓存"""
        if market in self._cache:
            del self._cache[market]

    @staticmethod
    def normalize_dataframe(df: pd.DataFrame) -> List[Dict[str, Any]]:
        """
        将 DataFrame 标准化为字典列表

        Args:
            df: pandas DataFrame

        Returns:
            标准化的字典列表
        """
        stocks: List[Dict[str, Any]] = cast(List[Dict[str, Any]], df.to_dict("records"))
        for stock in stocks:
            for key, value in stock.items():
                if pd.isna(value):
                    stock[key] = None
                elif not isinstance(value, (int, float, bool)):
                    stock[key] = str(value)
        return stocks

    # ==================== 抽象方法：股票列表 ====================

    @abstractmethod
    def fetch_a_stocks(self) -> List[Dict[str, Any]]:
        """
        获取 A 股股票列表

        Returns:
            标准格式的股票列表，包含以下字段：
            - ts_code: 股票代码（如 000001.SZ）
            - symbol: 股票代码（如 000001）
            - name: 股票名称
            - area: 地区
            - industry: 行业
            - market: 市场类型
            - list_date: 上市日期
        """
        pass

    @abstractmethod
    def fetch_us_stocks(self) -> List[Dict[str, Any]]:
        """
        获取美股股票列表

        Returns:
            标准格式的股票列表
        """
        pass

    def fetch_cn_etfs(self) -> List[Dict[str, Any]]:
        """获取 A 股 ETF 列表，默认不支持。"""
        return []

    # ==================== 抽象方法：日线数据 ====================

    @abstractmethod
    def _fetch_raw_daily(self, symbol: str) -> Optional[pd.DataFrame]:
        """
        从数据源获取原始日线数据（子类实现）

        Args:
            symbol: 股票代码

        Returns:
            原始 DataFrame，失败返回 None
        """
        pass

    @abstractmethod
    def _normalize_daily(self, df: pd.DataFrame, symbol: str) -> pd.DataFrame:
        """
        将原始日线数据标准化（子类实现）

        Args:
            df: 原始 DataFrame
            symbol: 股票代码

        Returns:
            标准化后的 DataFrame
        """
        pass

    def get_daily_data(self, symbol: str) -> Optional[pd.DataFrame]:
        """
        获取日线数据（统一入口）

        流程：
        1. _fetch_raw_daily() - 获取原始数据
        2. _normalize_daily() - 标准化列名
        3. _clean_daily() - 数据清洗
        4. _calculate_indicators() - 计算技术指标

        Args:
            symbol: 股票代码

        Returns:
            标准化后的 DataFrame，失败返回 None
        """
        try:
            # Step 1: 获取原始数据
            df = self._fetch_raw_daily(symbol)
            if df is None or df.empty:
                return None

            # Step 2: 标准化列名
            df = self._normalize_daily(df, symbol)

            # Step 3: 数据清洗
            df = self._clean_daily(df)

            # Step 4: 计算技术指标
            df = self._calculate_indicators(df)

            return df

        except Exception as e:
            print(f"⚠️ {self.SOURCE_NAME} 获取日线失败 [{symbol}]: {e}")
            return None

    @staticmethod
    def _clean_daily(df: pd.DataFrame) -> pd.DataFrame:
        """
        数据清洗

        处理：
        1. 确保日期列格式正确
        2. 数值类型转换
        3. 去除空值行
        4. 按日期排序
        """
        df = df.copy()

        # 确保日期列为 datetime 类型
        if "date" in df.columns:
            df["date"] = BaseStockDataSource._normalize_datetime_series(df["date"])

        # 数值列类型转换
        numeric_cols = ["open", "high", "low", "close", "volume"]
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        # 去除关键列为空的行
        if "close" in df.columns and "volume" in df.columns:
            df = df.dropna(subset=["close", "volume"])

        # 按日期升序排序
        if "date" in df.columns:
            df = df.sort_values("date", ascending=True).reset_index(drop=True)

        return df

    @staticmethod
    def _normalize_datetime_series(series: pd.Series) -> pd.Series:
        parsed = pd.to_datetime(series, errors="coerce")
        if getattr(parsed.dt, "tz", None) is not None:
            parsed = parsed.dt.tz_localize(None)
        return parsed

    @staticmethod
    def _calculate_indicators(df: pd.DataFrame) -> pd.DataFrame:
        """
        计算技术指标

        计算指标：
        - ma5, ma10, ma20: 移动平均线
        """
        if df is None or df.empty:
            return df

        df = df.copy()

        if "close" in df.columns:
            df["ma5"] = df["close"].rolling(window=5, min_periods=1).mean()
            df["ma10"] = df["close"].rolling(window=10, min_periods=1).mean()
            df["ma20"] = df["close"].rolling(window=20, min_periods=1).mean()

            # 保留2位小数
            for col in ["ma5", "ma10", "ma20"]:
                if col in df.columns:
                    df[col] = df[col].round(2)

        return df

    # ==================== 抽象方法：可用性检查 ====================

    @abstractmethod
    def is_available(self, market: str) -> bool:
        """
        检查数据源是否可用于指定市场

        Args:
            market: 市场类型（"A股" 或 "美股"）

        Returns:
            是否可用
        """
        pass

    # ==================== 具体方法：股票列表（进程内缓存）====================

    def get_a_stocks(self) -> List[Dict[str, Any]]:
        """
        获取 A 股股票列表（带进程内缓存）

        Returns:
            标准格式的股票列表
        """
        return self._get_symbol_rows(
            cache_key="A股",
            list_type="cn_equity",
            fetcher=self.fetch_a_stocks,
        )

    def get_us_stocks(self) -> List[Dict[str, Any]]:
        """
        获取美股股票列表（带进程内缓存）

        Returns:
            标准格式的股票列表
        """
        return self._get_symbol_rows(
            cache_key="美股",
            list_type="us_equity",
            fetcher=self.fetch_us_stocks,
        )

    def get_cn_etfs(self) -> List[Dict[str, Any]]:
        """获取 A 股 ETF 列表（带进程内缓存）。"""
        return self._get_symbol_rows(
            cache_key="A股ETF",
            list_type="cn_etf",
            fetcher=self.fetch_cn_etfs,
        )

    def _get_symbol_rows(
        self,
        *,
        cache_key: str,
        list_type: str,
        fetcher,
    ) -> List[Dict[str, Any]]:
        cached = self.get_cached(cache_key)
        if cached is not None:
            logger.debug(
                "symbol source cache hit provider=%s list_type=%s count=%s",
                self.SOURCE_NAME,
                list_type,
                len(cached),
            )
            return cached

        try:
            rows = fetcher()
            if rows:
                self.update_cache(cache_key, rows)
                logger.info(
                    "symbol source fetch success provider=%s list_type=%s count=%s",
                    self.SOURCE_NAME,
                    list_type,
                    len(rows),
                )
                return rows
        except Exception as e:
            logger.warning(
                "symbol source fetch failed provider=%s list_type=%s error_type=%s error=%s",
                self.SOURCE_NAME,
                list_type,
                type(e).__name__,
                e,
            )
            self.clear_cache(cache_key)

        return []

    # ==================== 防封禁工具方法 ====================

    @staticmethod
    def random_sleep(min_seconds: float = 1.0, max_seconds: float = 3.0) -> None:
        """
        随机休眠（Jitter）

        防封禁策略：每次请求前随机休眠，避免请求频率固定被识别为爬虫

        Args:
            min_seconds: 最小休眠时间（秒）
            max_seconds: 最大休眠时间（秒）
        """
        sleep_time = random.uniform(min_seconds, max_seconds)
        time.sleep(sleep_time)

    def _set_random_user_agent(self) -> None:
        """
        设置随机 User-Agent

        从 USER_AGENTS 池中随机选择一个 UA，并设置到 requests
        子类可以覆盖此方法来定制 UA 策略
        """
        try:
            import requests

            ua = random.choice(self.USER_AGENTS)
            headers = requests.utils.default_headers()
            headers["User-Agent"] = ua
            # 更新默认 headers
            requests.utils.default_headers = lambda: headers
        except Exception:
            pass

    # ==================== 实时行情接口 ====================

    def get_realtime_quote(self, symbol: str) -> Optional[UnifiedRealtimeQuote]:
        """
        获取实时行情（可选实现）

        子类可以覆盖此方法来支持实时行情。
        默认实现返回 None，表示不支持实时行情。

        Args:
            symbol: 股票代码

        Returns:
            UnifiedRealtimeQuote 对象，不支持则返回 None
        """
        # 默认不支持实时行情
        return None
