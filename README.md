# Stock Analysis API

股票分析后端服务，当前仅保留 HTTP REST API。

## 架构设计

- 项目为 HTTP-only 服务，不包含 MCP 协议能力
- 复杂接口统一返回 `entity / facts / analysis / meta`
- `facts` 仅放事实值和可靠 consensus
- `analysis` 仅放推导、估算和模型输出
- 共享标准 contract 位于 `src/model/contracts.py`
- HTTP 适配与统一输出位于 `src/analyzer/normalizers.py`
- 共享事实上下文聚合位于 `src/data_provider/fundamental_context.py`

### 返回契约

复杂接口统一返回：

- `entity`
- `facts`
- `analysis`
- `meta`

其中 `meta` 固定包含：

- `schema_version`
- `interface_type`
- `as_of`
- `sources`
- `limitations`

当前 schema 版本：`2.0.0`

## 能力模块

### 股票能力

- `/stock/analyze` 股票综合分析
- `/stock/list` 股票列表
- `/stock/search` 股票搜索

### 估值能力

- `/valuation/dcf` DCF 估值模型
- `/valuation/comps` 可比公司分析

### 模型能力

- `/model/lbo` LBO 情景模型
- `/model/three-statement` 三表预测模型
- `/model/three-statement/scenarios` 三表情景对比

### 专项分析能力

- `/analysis/competitive/competitive` 竞争格局分析
- `/analysis/earnings/earnings` 季报分析

## 使用说明

### 快速开始

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
uv venv
source .venv/bin/activate
uv pip install -e .
uv run start
```

服务启动后访问 `http://localhost:8080/docs`。

### 常用本地验证

```bash
curl http://127.0.0.1:8080/ping
curl 'http://127.0.0.1:8080/stock/list?market=美股&limit=2'
curl 'http://127.0.0.1:8080/analysis/earnings/earnings?symbol=NVDA'
curl 'http://127.0.0.1:8080/analysis/competitive/competitive?symbol=NVDA&industry=technology'
curl 'http://127.0.0.1:8080/valuation/comps?symbol=NVDA&sector=Semiconductors'
```

### 环境变量

| 变量 | 说明 |
|------|------|
| `TUSHARE_TOKEN` | Tushare Token，可选 |
| `PORT` | HTTP 端口，默认 `8080` |
| `ENV` | `development` / `production` |

### Docker

```bash
docker build -t stock-analysis-api .
docker run -p 8080:8080 stock-analysis-api
```

## 开发说明

- 项目为 HTTP-only
- 事实字段和推导字段必须分层返回，禁止将估算或模型结果写入 `facts`
- 缺少可靠原始数据时返回 `unavailable` / `partial`，不要填 0 或伪造历史
- 标准化 contract 位于 `src/model/contracts.py`
- HTTP 适配与统一输出位于 `src/analyzer/normalizers.py`
- 共享事实上下文聚合位于 `src/data_provider/fundamental_context.py`
