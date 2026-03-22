"""
股票分析流程编排

提供股票分析的统一流程编排，包括：
- 股票列表服务
- 基础数据获取
- 基本面分析
- 技术面分析
- Qlib因子分析
"""

from typing import Any, Dict, List, Optional, Tuple
import pandas as pd

from ..config import is_development
from ..data_provider.manager import data_manager
from ..model import AnalysisReport, FactorDetail
from ..services.daily_data_read_service import daily_data_read_service
from ..services.symbol_catalog_service import symbol_catalog_service


class StockService:
    """统一的股票服务类，封装所有股票相关操作"""

    def __init__(self):
        """初始化服务。"""
        pass

    # ==================== 基础数据获取 ====================

    def get_stock_data(self, symbol: str) -> Tuple[Optional[pd.DataFrame], str, str]:
        """
        获取股票日线数据

        Args:
            symbol: 股票代码

        Returns:
            (DataFrame, stock_name, data_source): 数据、股票名称和数据源，失败时返回 (None, symbol, "")
        """
        return daily_data_read_service.get_stock_daily(symbol)

    def get_financial_data(self, symbol: str) -> Tuple[Optional[Dict[str, Any]], str]:
        """
        获取财务数据

        Args:
            symbol: 股票代码

        Returns:
            (财务数据字典, 数据源): 包含PE、PB、ROE等指标
        """
        return data_manager.get_financial_data(symbol)

    # ==================== 股票列表服务 ====================

    def get_stock_list(
        self, market: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        获取股票列表

        Args:
            market: 市场类型 ('A股', '美股', None表示全部)
        Returns:
            股票列表
        """
        if market == "A股":
            return symbol_catalog_service.get_market_snapshot("cn")
        elif market == "美股":
            return symbol_catalog_service.get_market_snapshot("us")
        else:
            return symbol_catalog_service.list_symbols()

    def search_stocks(self, keyword: str, market: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        搜索股票

        Args:
            keyword: 搜索关键词
            market: 市场类型

        Returns:
            匹配的股票列表
        """
        return symbol_catalog_service.search_symbols(keyword, market)

    # ==================== 分析服务 ====================

    def analyze_symbol(
        self, symbol: str, include_qlib_factors: bool = False
    ) -> Optional[AnalysisReport]:
        """
        分析单只股票

        Args:
            symbol: 股票代码
            include_qlib_factors: 是否包含 Qlib 158 因子，默认 False

        Returns:
            分析报告
        """
        try:
            # 执行分析
            print(f"Update Data: {symbol}")
            df, stock_name, data_source = self.get_stock_data(symbol)

            # 延迟导入避免循环依赖
            from ..analyzer import MultiFactorAnalyzer

            if df is None or df.empty:
                return None

            # 获取财务数据源
            _, financial_data_source = self.get_financial_data(symbol)

            analyzer = MultiFactorAnalyzer(
                df,
                symbol,
                stock_name,
                include_qlib_factors=include_qlib_factors,
                data_source=data_source,
                financial_data_source=financial_data_source,
            )
            report = analyzer.analyze()

            # 开发环境输出控制台报告
            if report is not None and is_development():
                from ..notification.formatters import console_report

                console_report(report)

            return report

        except Exception as e:
            import traceback

            print(f"Error in analysis service for symbol {symbol}: {e}")
            print("完整错误堆栈:")
            traceback.print_exc()
            return None

    def batch_analyze(
        self,
        symbols: List[str],
        include_qlib_factors: bool = False,
    ) -> List[AnalysisReport]:
        """
        批量分析股票

        Args:
            symbols: 股票代码列表
            include_qlib_factors: 是否包含 Qlib 158 因子，默认 False

        Returns:
            成功分析的报告列表
        """
        reports: List[AnalysisReport] = []
        seen: set[str] = set()

        for symbol in symbols:
            normalized = symbol.upper()
            if normalized in seen:
                continue
            seen.add(normalized)
            report = self.analyze_symbol(normalized, include_qlib_factors)
            if report is not None:
                reports.append(report)

        return reports

    # ==================== 因子分析服务 ====================

    def get_fundamental_factors(self, symbol: str) -> Optional[List[FactorDetail]]:
        """
        获取基本面因子

        Args:
            symbol: 股票代码

        Returns:
            基本面因子列表
        """
        report = self.analyze_symbol(symbol)
        return report.fundamental.factors if report else None

    def get_technical_factors(self, symbol: str) -> Optional[List[FactorDetail]]:
        """
        获取技术面因子

        Args:
            symbol: 股票代码

        Returns:
            技术面因子列表
        """
        report = self.analyze_symbol(symbol)
        return report.technical.factors if report else None

    def get_qlib_factors(self, symbol: str) -> Optional[List[FactorDetail]]:
        """
        获取Qlib因子

        Args:
            symbol: 股票代码

        Returns:
            Qlib因子列表
        """
        report = self.analyze_symbol(symbol)
        return report.qlib.factors if report else None

# 创建全局实例
stock_service = StockService()
