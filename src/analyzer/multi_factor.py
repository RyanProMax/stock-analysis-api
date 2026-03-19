from stockstats import StockDataFrame
import pandas as pd
from datetime import date, datetime

from ..core import AnalysisReport, FactorAnalysis, FearGreed
from ..data_provider import data_manager
from .technical_factors import TechnicalFactorLibrary
from .fundamental_factors import FundamentalFactorLibrary
from .qlib_158_factors import Qlib158FactorLibrary
from .trend_analyzer import StockTrendAnalyzer


class MultiFactorAnalyzer:
    """
    多因子股票分析器

    核心设计理念：
    1. 加载各个因子库（技术面、基本面、qlib158等）
    2. 统一输出因子列表
    3. 每个因子库独立管理自己的因子计算逻辑

    因子库：
    - TechnicalFactorLibrary: 技术面因子库（MA、EMA、MACD、RSI等）
    - FundamentalFactorLibrary: 基本面因子库（营收增长率、PE、PB等）
    - Qlib158FactorLibrary: Qlib 158 经典因子库
    """

    # 需要计算的技术指标列表（按因子分类）
    INDICATORS_TO_CALCULATE = [
        # 趋势指标
        "macd",  # MACD 主线
        "macdh",  # MACD 柱线（用于趋势判断）
        "macds",  # MACD 信号线
        "close_12_ema",  # 12日指数均线
        "close_26_ema",  # 26日指数均线
        "close_5_sma",  # 5日简单均线
        "close_10_sma",  # 10日简单均线
        "close_20_sma",  # 20日简单均线
        "close_60_sma",  # 60日简单均线
        # 动量指标
        "rsi_14",  # 14日 RSI 相对强弱指标
        "kdjk",  # KDJ 指标 K 值
        "kdjd",  # KDJ 指标 D 值
        "kdjj",  # KDJ 指标 J 值
        "wr_14",  # 14日威廉指标
        # 波动率指标
        "boll",  # 布林带中轨
        "boll_ub",  # 布林带上轨
        "boll_lb",  # 布林带下轨
        "atr",  # 真实波动幅度（用于止损计算）
        # 量能指标
        "vr",  # 成交量比率
        "volume",  # 成交量
    ]

    def __init__(
        self,
        df: pd.DataFrame,
        symbol: str,
        stock_name: str,
        include_qlib_factors: bool = False,
        data_source: str = "",
        financial_data_source: str = "",
    ):
        """
        初始化多因子分析器

        Args:
            df: 股票行情数据 DataFrame
            symbol: 股票代码
            stock_name: 股票名称
            include_qlib_factors: 是否包含 Qlib 158 因子，默认 False
            data_source: 日线数据源标识
            financial_data_source: 财务数据源标识
        """
        if df is None or df.empty:
            raise ValueError("DataFrame cannot be None or empty")
        if not symbol or not symbol.strip():
            raise ValueError("Symbol cannot be empty")

        self.raw_df = df.copy()
        self.symbol = symbol.strip().upper()
        self.stock_name = stock_name or symbol
        self.include_qlib_factors = include_qlib_factors
        self.data_source = data_source
        self.financial_data_source = financial_data_source

        # 初始化技术指标计算引擎
        self.stock = StockDataFrame.retype(self.raw_df.copy())

        # 计算所需的技术指标
        for indicator in self.INDICATORS_TO_CALCULATE:
            self.stock.get(indicator)

        # 初始化因子库
        self.technical_library = TechnicalFactorLibrary()
        self.fundamental_library = FundamentalFactorLibrary()
        self.qlib158_library = Qlib158FactorLibrary()

    def _calculate_fear_greed(self, row, prev_row, close) -> tuple[float, str]:
        """
        计算个股贪恐指数（Fear & Greed Index）

        基于7个技术指标加权合成，参考成熟方案：
        - CNN Fear & Greed Index (7个等权重指标)
        - alternative.me Crypto Fear & Greed Index (6个加权指标)

        指标体系：
        | 指标 | 权重 | 作用 |
        |------|------|------|
        | RSI-14 | 20% | 超买超卖 |
        | 布林带 %B | 20% | 价格位置 |
        | WR-14 | 15% | 超买超卖 |
        | KDJ J值 | 15% | 超买超卖 |
        | MACD 柱 | 15% | 动量方向 |
        | 价格动量 | 10% | 短期趋势 |
        | VR 量比 | 5% | 成交量变化 |
        """
        try:
            # 1. RSI (0-100)
            rsi = float(row.get("rsi_14", 50) or 50)

            # 2. 布林带 %B (0-100)
            lb = float(row.get("boll_lb", close * 0.9))
            ub = float(row.get("boll_ub", close * 1.1))
            if ub != lb:
                pct_b = (close - lb) / (ub - lb) * 100
            else:
                pct_b = 50
            pct_b = max(0, min(100, pct_b))

            # 3. WR (0-100)
            wr = float(row.get("wr_14", -50))
            wr_score = max(0, min(100, wr + 100))

            # 4. KDJ J值 (0-100)
            # J值范围通常是 -50 到 150，映射到 0-100
            kdjj = float(row.get("kdjj", 50))
            kdj_score = max(0, min(100, (kdjj + 50) * 100 / 200))

            # 5. MACD 柱 (0-100)
            # 正值表示多头，负值表示空头
            # 映射到 0-100: 50 为中性，100 为强势多头，0 为强势空头
            macd_h = float(row.get("macdh", 0))
            if macd_h > 0:
                # 正值：50-100，强度取决于绝对值
                # 假设 macd_h 最大约 5（经验值）
                macd_score = 50 + min(macd_h * 10, 50)
            else:
                # 负值：0-50
                macd_score = 50 + max(macd_h * 10, -50)
            macd_score = max(0, min(100, macd_score))

            # 6. 价格动量 - 近5日涨跌幅
            # 使用 close 和前5日收盘价计算
            prev_close_5 = close
            if len(self.stock) >= 5:
                prev_close_5 = float(self.stock.iloc[-5].get("close", close) or close)
            if prev_close_5 > 0:
                change_pct = (close - prev_close_5) / prev_close_5 * 100
            else:
                change_pct = 0
            # 涨跌幅映射到 0-100: -10% => 0, 0 => 50, +10% => 100
            momentum_score = 50 + (change_pct * 5)
            momentum_score = max(0, min(100, momentum_score))

            # 7. VR 量比 (0-100)
            # VR 正常范围 100-200，映射到 0-100
            vr = float(row.get("vr", 100) or 100)
            # VR=100 => 50 分, VR=200 => 100 分, VR=0 => 0 分
            volume_score = max(0, min(100, vr * 0.5))
            volume_score = max(0, min(100, volume_score))

            # 加权合成
            fg_index = (
                rsi * 0.20
                + pct_b * 0.20
                + wr_score * 0.15
                + kdj_score * 0.15
                + macd_score * 0.15
                + momentum_score * 0.10
                + volume_score * 0.05
            )

            # 生成标签
            if fg_index < 20:
                label = "🥶 极度恐慌"
            elif fg_index < 40:
                label = "😨 恐慌"
            elif fg_index < 60:
                label = "😐 中性"
            elif fg_index < 80:
                label = "🤤 贪婪"
            else:
                label = "🔥 极度贪婪"

            return fg_index, label
        except Exception as e:
            # 如果计算失败，返回默认值
            print(f"⚠️ 计算贪恐指数失败: {e}")
            return 50.0, "😐 中性"

    def analyze(self) -> AnalysisReport | None:
        """
        执行完整的股票技术分析流程

        核心流程：
        1. 提取最新行情数据和技术指标
        2. 获取财务数据（营收、负债、市盈率等）
        3. 计算贪恐指数（用于波动率因子）
        4. 从各个因子库加载因子
        5. 汇总所有因子
        """
        last_row = self.stock.iloc[-1]
        prev_row = self.stock.iloc[-2] if len(self.stock) > 1 else last_row

        close = float(last_row.get("close", 0.0))
        if close == 0.0:
            return None

        # 计算贪恐指数（用于波动率因子）
        fg_index, fg_label = self._calculate_fear_greed(last_row, prev_row, close)

        # 计算成交量均线（用于量能因子）
        volume_series = (
            self.raw_df["volume"]
            if "volume" in self.raw_df.columns
            else pd.Series([last_row.get("volume", 0)])
        )
        # 使用 ffill() 替代已弃用的 fillna(method="ffill")
        volume_series = volume_series.ffill().fillna(0)
        volume_ma5 = float(volume_series.tail(5).mean())
        volume_ma20 = (
            float(volume_series.tail(20).mean())
            if len(volume_series) >= 20
            else volume_ma5
        )

        # --- 获取财务数据（基本面因子）---
        financial_data = None
        financial_data_source = self.financial_data_source
        financial_raw_data = None
        try:
            financial_data, source = data_manager.get_financial_data(self.symbol)
            if source:
                financial_data_source = source
            # 提取原始数据
            if financial_data and "raw_data" in financial_data:
                financial_raw_data = financial_data.get("raw_data")
        except Exception as e:
            import traceback

            print(f"⚠️ 获���财务数据失败: {e}")
            print("财务数据获取错误堆栈:")
            traceback.print_exc()

        # --- 获取股票信息（行业等）---
        stock_info = {}
        try:
            stock_info = data_manager.get_stock_info(self.symbol)
        except Exception as e:
            print(f"⚠️ 获取股票信息失败: {e}")

        # --- 准备技术面原始数据 ---
        technical_raw_data = {
            "latest": last_row.to_dict(),
            "data_source": self.data_source,
        }

        # --- 从各个因子库加载因子 ---
        technical_factors = []
        fundamental_factors = []
        qlib_factors = []

        # 1. 技术面因子库
        try:
            technical_factors = self.technical_library.get_factors(
                self.stock,
                self.raw_df,
                fg_index=fg_index,
                volume_ma5=volume_ma5,
                volume_ma20=volume_ma20,
                data_source=self.data_source,
                raw_data=technical_raw_data,
            )
        except Exception as e:
            import traceback

            print(f"⚠️ 计算技术面因子失败: {e}")
            traceback.print_exc()

        # 2. 基本面因子库
        try:
            fundamental_factors = self.fundamental_library.get_factors(
                self.stock,
                self.raw_df,
                financial_data=financial_data,
                data_source=financial_data_source,
                raw_data=financial_raw_data,
            )
        except Exception as e:
            import traceback

            print(f"⚠️ 计算基本面因子失败: {e}")
            traceback.print_exc()

        # 3. Qlib 158 因子库（根据参数决定是否计算）
        try:
            if self.include_qlib_factors:
                qlib_factors = self.qlib158_library.get_factors(
                    self.stock,
                    self.raw_df,
                    symbol=self.symbol,
                    data_source=self.data_source,
                    raw_data=technical_raw_data,
                )
            else:
                qlib_factors = []
        except Exception as e:
            import traceback

            print(f"⚠️ 计算 Qlib 158 因子失败: {e}")
            traceback.print_exc()
            qlib_factors = []

        # 创建贪恐指数对象
        fear_greed = FearGreed(index=fg_index, label=fg_label)

        as_of = self._extract_as_of(last_row)

        # --- 趋势分析 ---
        trend_analysis = None
        try:
            trend_analyzer = StockTrendAnalyzer()
            trend_analysis = trend_analyzer.analyze(self.raw_df, self.symbol)
        except Exception as e:
            import traceback

            print(f"⚠️ 趋势分析失败: {e}")
            traceback.print_exc()

        report = AnalysisReport(
            symbol=self.symbol,
            stock_name=self.stock_name,
            price=close,
            as_of=as_of,
            technical=FactorAnalysis(
                factors=technical_factors,
                data_source=self.data_source,
                raw_data=technical_raw_data,
            ),
            fundamental=FactorAnalysis(
                factors=fundamental_factors,
                data_source=financial_data_source,
                raw_data=financial_raw_data,
            ),
            qlib=FactorAnalysis(
                factors=qlib_factors,
                data_source=self.data_source,
                raw_data=None,
            ),
            fear_greed=fear_greed,
            industry=stock_info.get("industry", ""),
            trend_analysis=trend_analysis,
        )

        return report

    def _extract_as_of(self, row) -> str | None:
        """从最新行情行中提取数据日期，避免缓存结果被误认为实时。"""
        raw_value = row.get("date")
        if raw_value is None and hasattr(row, "name"):
            raw_value = row.name

        if isinstance(raw_value, pd.Timestamp):
            return raw_value.date().isoformat()
        if isinstance(raw_value, datetime):
            return raw_value.date().isoformat()
        if isinstance(raw_value, date):
            return raw_value.isoformat()
        if raw_value:
            return str(raw_value)
        return None
