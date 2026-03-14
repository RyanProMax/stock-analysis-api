"""
Stock Analysis MCP Server

启动方式:
    poetry run mcp

    或:
    poetry run python -m src.mcp_server.server

Agent 连接配置示例 (Claude Code):
    在 MCP 配置文件中添加:

    {
      "mcpServers": {
        "stock-analysis": {
          "command": "python",
          "args": ["-m", "src.mcp_server.server"],
          "cwd": "/path/to/stock-analysis-api"
        }
      }
    }
"""

from dataclasses import asdict
from typing import Optional

from mcp.server import FastMCP

from ..core.pipeline import stock_service
from ..analyzer.dcf_model import DCFModel
from ..analyzer.comps_analyzer import CompsAnalyzer

mcp = FastMCP("stock-analysis")


# ==================== 股票数据工具 ====================


@mcp.tool()
def get_stock_list(market: Optional[str] = None, refresh: bool = False) -> dict:
    """获取股票列表

    Args:
        market: 市场类型 'A股' 或 '美股'，None 返回全部
        refresh: 是否刷新缓存

    Returns:
        包含股票列表的字典 (限制返回前100条)
    """
    stocks = stock_service.get_stock_list(market, refresh)
    return {"total": len(stocks), "stocks": stocks[:100]}


@mcp.tool()
def search_stocks(keyword: str, market: Optional[str] = None) -> dict:
    """搜索股票

    Args:
        keyword: 搜索关键词（股票代码或名称）
        market: 市场类型 'A股' 或 '美股'

    Returns:
        匹配的股票列表
    """
    stocks = stock_service.search_stocks(keyword, market)
    return {"total": len(stocks), "stocks": stocks}


# ==================== 股票分析工具 ====================


@mcp.tool()
def analyze_stock(symbol: str, include_qlib: bool = False) -> dict:
    """综合分析股票（技术面+基本面）

    Args:
        symbol: 股票代码
        include_qlib: 是否包含 Qlib 158 因子

    Returns:
        完整的分析报告，包含技术面、基本面因子
    """
    report = stock_service.analyze_symbol(symbol, include_qlib_factors=include_qlib)
    if report is None:
        return {"error": f"无法分析 {symbol}"}

    result = asdict(report)

    # 处理 trend_analysis 的枚举类型
    if result.get("trend_analysis") and hasattr(result["trend_analysis"], "__dict__"):
        ta = result["trend_analysis"]
        ta_dict = {}
        for key, value in ta.__dict__.items():
            if hasattr(value, "value"):
                ta_dict[key] = value.value
            else:
                ta_dict[key] = value
        result["trend_analysis"] = ta_dict

    return result


# ==================== 估值分析工具 ====================


@mcp.tool()
def analyze_dcf(symbol: str) -> dict:
    """DCF 估值分析 (仅支持美股)

    基于自由现金流折现法计算股票内在价值

    Args:
        symbol: 美股代码

    Returns:
        DCF 估值结果，包含 WACC、FCF预测、敏感性分析、估值区间
    """
    model = DCFModel()
    result = model.analyze(symbol.upper())

    if result.error:
        return {"error": result.error}

    return result.to_dict()


@mcp.tool()
def analyze_comps(symbol: str, sector: Optional[str] = None) -> dict:
    """可比公司分析 (仅支持美股)

    基于行业筛选可比公司，计算相对估值

    Args:
        symbol: 美股代码
        sector: 行业分类 (可选，如 Technology, Semiconductors)

    Returns:
        可比公司分析结果，包含估值倍数、分位数、隐含估值
    """
    analyzer = CompsAnalyzer()
    result = analyzer.analyze(symbol.upper(), sector)

    if result.error:
        return {"error": result.error}

    return result.to_dict()


if __name__ == "__main__":
    mcp.run()
