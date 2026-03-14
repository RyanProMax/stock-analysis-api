# CLAUDE.md

Stock Analysis API 后端项目，支持 HTTP REST API 和 MCP 协议。

## 技术栈

- Python 3.12+
- FastAPI + Uvicorn
- uv 依赖管理
- MCP (Model Context Protocol)

## 开发命令

```bash
# 安装 uv (如果没有)
curl -LsSf https://astral.sh/uv/install.sh | sh

# 创建虚拟环境并安装依赖
uv venv
source .venv/bin/activate
uv pip install -e .

# 运行 HTTP 服务
PYTHONPATH=. python main.py

# 运行 MCP 服务 (供 AI Agent 调用)
uv run mcp

# 代码格式化
black --line-length 100 .
```

## 项目结构

```
src/
├── analyzer/         # 因子计算 (DCF, Comps, 技术/基本面)
├── api/              # FastAPI 路由
├── config.py         # 配置
├── core/             # 核心功能 (StockService)
├── data_provider/    # 数据源 (A股/美股)
├── mcp_server/       # MCP Server (AI Agent 接口)
├── model/            # 数据模型
├── storage/          # 缓存存储
└── utils/            # 工具函数
```

## API 能力

### HTTP API (`/stock/*`, `/valuation/*`)

| 端点 | 方法 | 描述 |
|------|------|------|
| `/stock/analyze` | POST | 批量分析股票 |
| `/stock/list` | GET | 获取股票列表 |
| `/stock/search` | POST | 搜索股票 |
| `/valuation/dcf` | GET | DCF 估值分析 |
| `/valuation/comps` | GET | 可比公司分析 |

### MCP Tools (5个，与 HTTP API 一一对应)

| 工具 | 对应 HTTP API | 描述 |
|------|---------------|------|
| `analyze_stock` | `/stock/analyze` | 综合分析股票 |
| `get_stock_list` | `/stock/list` | 获取股票列表 |
| `search_stocks` | `/stock/search` | 搜索股票 |
| `analyze_dcf` | `/valuation/dcf` | DCF 估值分析 (仅美股) |
| `analyze_comps` | `/valuation/comps` | 可比公司分析 (仅美股) |

**MCP 和 HTTP API 能力对齐原则：**
- MCP 工具与 HTTP API 必须一一对应，提供相同的分析能力
- MCP 使用 stdio 传输，适合同服务器 Agent 调用
- HTTP API 使用 REST，适合跨服务调用

## 环境变量

| 变量 | 必填 | 说明 |
|------|------|------|
| TUSHARE_TOKEN | 可选 | Tushare Token |
| PORT | 否 | HTTP 端口 (默认 8080) |
| ENV | 否 | development/production |

## 部署

### Docker

```bash
docker build -t stock-analysis-api .
docker run -p 8080:8080 stock-analysis-api
```

### MCP Agent 连接

```json
{
  "mcpServers": {
    "stock-analysis": {
      "command": "python",
      "args": ["-m", "src.mcp_server.server"],
      "cwd": "/path/to/stock-analysis-api"
    }
  }
}
```

## 代码规范

- 新增 API 能力时，需同时更新 HTTP API 和 MCP Tools，保持能力对齐
- 业务逻辑放在 `src/core/` 或 `src/analyzer/`，API 层只做调用转发
- DCF 和 Comps 分析仅支持美股
