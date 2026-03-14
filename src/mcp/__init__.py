"""
MCP (Model Context Protocol) 模块

提供股票分析能力的 MCP Server，供 AI Agent 调用。
"""

from .server import mcp

__all__ = ["mcp"]
