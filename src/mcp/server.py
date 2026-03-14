"""
Stock Analysis MCP Server

启动方式:
    poetry run python -m src.mcp.server

    或使用快捷命令:
    poetry run stock-mcp

Agent 连接配置示例 (Claude Code):
    在 MCP 配置文件中添加:

    {
      "mcpServers": {
        "stock-analysis": {
          "command": "python",
          "args": ["-m", "src.mcp.server"],
          "cwd": "/path/to/stock-analysis-api"
        }
      }
    }
"""

from dataclasses import asdict

from mcp.server import FastMCP

from ..core.pipeline import stock_service
from ..analyzer.dcf_model import DCFModel
from ..analyzer.comps_analyzer import CompsAnalyzer

mcp = FastMCP("stock-analysis")


# ==================== 股票数据工具 ====================


@mcp.tool()
def get_stock_data(symbol: str) -> dict:
    """获取股票行情数据

    Args:
        symbol: 股票代码 (如 AAPL, 000001.SZ)

    Returns:
        包含股票名称、最新价格、30日行情数据的字典
    """
    df, name, source = stock_service.get_stock_data(symbol)
    if df is None or df.empty:
        return {"error": f"无法获取 {symbol} 的数据"}

    return {
        "symbol": symbol,
        "name": name,
        "data_source": source,
        "latest_price": float(df.iloc[-1]["close"]),
        "latest_change_pct": float(df.iloc[-1].get("change_pct", 0)),
        "data": df.tail(30).to_dict("records"),
    }


@mcp.tool()
def get_stock_list(market: str = None, refresh: bool = False) -> dict:
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
def search_stocks(keyword: str, market: str = None) -> dict:
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


@mcp.tool()
def get_technical_factors(symbol: str) -> dict:
    """获取技术面因子

    包括 MA、MACD、RSI、KDJ 等技术指标

    Args:
        symbol: 股票代码

    Returns:
        技术面因子列表
    """
    factors = stock_service.get_technical_factors(symbol)
    if factors is None:
        return {"error": f"无法获取 {symbol} 的技术面因子"}

    return {
        "symbol": symbol,
        "factors": [
            {"key": f.key, "name": f.name, "status": f.status, "signals": f.bullish_signals + f.bearish_signals}
            for f in factors
        ],
    }


@mcp.tool()
def get_fundamental_factors(symbol: str) -> dict:
    """获取基本面因子

    包括 PE、PB、ROE、营收增长率等基本面指标

    Args:
        symbol: 股票代码

    Returns:
        基本面因子列表
    """
    factors = stock_service.get_fundamental_factors(symbol)
    if factors is None:
        return {"error": f"无法获取 {symbol} 的基本面因子"}

    return {
        "symbol": symbol,
        "factors": [
            {"key": f.key, "name": f.name, "status": f.status, "signals": f.bullish_signals + f.bearish_signals}
            for f in factors
        ],
    }


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
def analyze_comps(symbol: str, sector: str = None) -> dict:
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
