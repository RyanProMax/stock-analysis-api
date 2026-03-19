# AGENTS.md

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
uv run start

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

### HTTP API

| 端点 | 方法 | 描述 |
|------|------|------|
| `/stock/analyze` | POST | 批量分析股票 |
| `/stock/list` | GET | 获取股票列表，可显式传 `limit` |
| `/stock/search` | POST | 搜索股票 |
| `/valuation/dcf` | GET | DCF 快速估值模型 (仅美股，模型型接口) |
| `/valuation/comps` | GET | 可比公司分析 (仅美股，混合型接口) |
| `/model/lbo` | GET | LBO 情景模型 |
| `/model/three-statement` | GET | 三表预测模型 |
| `/model/three-statement/scenarios` | GET | 三表情景对比 |
| `/analysis/competitive/competitive` | GET | 竞争格局分析 (含估算字段) |
| `/analysis/earnings/earnings` | GET | 季报分析 |

### MCP Tools

| 工具 | 对应 HTTP API | 描述 |
|------|---------------|------|
| `analyze_stock` | `/stock/analyze` | 综合分析股票 |
| `get_stock_list` | `/stock/list` | 获取股票列表，可显式传 `limit` |
| `search_stocks` | `/stock/search` | 搜索股票 |
| `analyze_dcf` | `/valuation/dcf` | DCF 快速估值模型 (仅美股) |
| `analyze_comps` | `/valuation/comps` | 可比公司分析 (仅美股) |
| `analyze_lbo` | `/model/lbo` | LBO 情景模型 |
| `analyze_three_statement` | `/model/three-statement` | 三表预测模型 |
| `analyze_competitive` | `/analysis/competitive/competitive` | 竞争格局分析 |
| `analyze_earnings` | `/analysis/earnings/earnings` | 季报分析 |

**事实型 / 模型型 / 混合型接口原则：**
- `/stock/list`、`/stock/search` 属于事实型接口
- `/valuation/dcf`、`/model/lbo`、`/model/three-statement` 属于模型型接口
- `/stock/analyze`、`/valuation/comps`、`/analysis/competitive/competitive`、`/analysis/earnings/earnings` 属于混合型接口
- 模型型和混合型接口必须显式暴露 `as_of`、假设来源或限制说明，不得把推导结果写成事实数据
- MCP 和 HTTP 应提供相同能力，但分页、截断等行为必须显式参数化，禁止静默不一致

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
- 对模型型接口，优先返回“数据完整性 + 假设来源 + 限制说明”，缺少可靠原始数据时宁可降级，也不要伪造历史或共识数据
