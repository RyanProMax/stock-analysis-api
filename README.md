# Stock Analysis API

股票分析系统后端 API 服务，支持 HTTP REST API 和 MCP 协议。

## 功能

- 股票技术分析 (MA, MACD, RSI, KDJ 等)
- 股票基本面分析 (PE, PB, ROE, 营收增长等)
- DCF 估值模型
- Comps 可比公司分析
- LBO 情景模型
- 3-Statement 预测模型
- Competitive / Earnings 分析接口
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
uv run start
```

服务启动后访问 [http://localhost:8080/docs](http://localhost:8080/docs) 查看 API 文档。

## 环境变量

| 变量 | 说明 |
|------|------|
| `TUSHARE_TOKEN` | Tushare Token (可选) |
| `PORT` | 服务端口，默认 8080 |
| `MODE` | 运行模式: `http` 或 `mcp` (Docker 部署用) |

## 部署

### Docker 本地部署

#### 构建镜像

```bash
docker build -t stock-analysis-api .
```

#### 运行 HTTP 服务

```bash
docker run -d -p 8080:8080 \
  --name stock-analysis-api \
  -e MODE=http \
  -e TUSHARE_TOKEN=your_token_here \
  stock-analysis-api
```

#### 运行 MCP 服务

```bash
# 启动 MCP 容器 (stdio 模式)
docker run -d \
  --name stock-analysis-mcp \
  -e MODE=mcp \
  stock-analysis-api

# Agent 连接方式1: docker exec
docker exec -i stock-analysis-mcp python -m src.mcp_server.server
```

#### 使用 Docker Hub 镜像

```bash
# 拉取镜像
docker pull ryanpro1024/stock-analysis-api:latest

# 运行 HTTP 服务
docker run -d -p 8080:8080 \
  --name stock-analysis-api \
  -e MODE=http \
  ryanpro1024/stock-analysis-api:latest

# 运行 MCP 服务
docker run -d \
  --name stock-analysis-mcp \
  -e MODE=mcp \
  ryanpro1024/stock-analysis-api:latest
```

### MCP 服务 (供 AI Agent 调用)

本项目支持 MCP 协议，可被 Claude、OpenClaw 等 AI Agent 直接调用。

**本地启动 MCP 服务:**

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

**MCP 工具列表 (当前实际暴露能力):**

| 工具 | 描述 |
|------|------|
| `analyze_stock` | 综合分析股票 |
| `get_stock_list` | 获取股票列表 |
| `search_stocks` | 搜索股票 |
| `analyze_dcf` | DCF 估值分析 (仅美股) |
| `analyze_comps` | 可比公司分析 (仅美股) |
| `analyze_lbo` | LBO 情景模型 |
| `analyze_three_statement` | 三表预测模型 |
| `analyze_competitive` | 竞争格局分析 |
| `analyze_earnings` | 季报分析 |
