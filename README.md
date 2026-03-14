# Stock Analysis API

股票分析系统后端 API 服务，支持 HTTP REST API 和 MCP 协议。

## 功能

- 股票技术分析 (MA, MACD, RSI, KDJ 等)
- 股票基本面分析 (PE, PB, ROE, 营收增长等)
- DCF 估值模型
- Comps 可比公司分析
- MCP 协议支持 (供 AI Agent 调用)

## 快速开始

```bash
# 安装 uv (如果没有)
curl -LsSf https://astral.sh/uv/install.sh | sh

# 创建虚拟环境并安装依赖
uv venv
source .venv/bin/activate
uv pip install -e .

# 或使用 uv sync (自动安装依赖)
uv sync

# 运行 HTTP 服务
PYTHONPATH=. python main.py
```

服务启动后访问 [http://localhost:8080/docs](http://localhost:8080/docs) 查看 API 文档。

## 环境变量

| 变量 | 说明 |
|------|------|
| `TUSHARE_TOKEN` | Tushare Token (可选) |
| `PORT` | 服务端口，默认 8080 |

## 部署

### Docker 本地部署

```bash
# 构建镜像
docker build -t stock-analysis-api .

# 运行容器
docker run -d -p 8080:8080 \
  --name stock-analysis-api \
  -e TUSHARE_TOKEN=your_token_here \
  stock-analysis-api
```

### MCP 服务 (供 AI Agent 调用)

本项目支持 MCP 协议，可被 Claude、OpenClaw 等 AI Agent 直接调用。

**启动 MCP 服务:**

```bash
# 方式1: 使用 uv run
uv run mcp

# 方式2: 激活环境后运行
source .venv/bin/activate
python -m src.mcp_server.server
```

**Agent 连接配置:**

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

**MCP 工具列表 (与 HTTP API 对齐):**

| 工具 | 描述 |
|------|------|
| `analyze_stock` | 综合分析股票 |
| `get_stock_list` | 获取股票列表 |
| `search_stocks` | 搜索股票 |
| `analyze_dcf` | DCF 估值分析 (仅美股) |
| `analyze_comps` | 可比公司分析 (仅美股) |
