# Stock Analysis API

股票分析后端服务，当前仅保留 HTTP REST API。

## 当前状态

- 项目已收敛为 HTTP-only，不再包含 MCP 服务或相关依赖
- 复杂接口统一返回 `entity / facts / analysis / meta`
- 主分析链路已围绕共享 `fundamental_context` 中间层收敛：
  - `/stock/analyze`
  - `/analysis/earnings/earnings`
  - `/analysis/competitive/competitive`
  - `/valuation/dcf`
  - `/valuation/comps`
  - `/model/lbo`
  - `/model/three-statement`
- `facts` 仅放事实值和可靠 consensus，`analysis` 仅放推导、估算、模型输出

## 功能

- `/stock/analyze` 股票综合分析
- `/stock/list` 股票列表
- `/stock/search` 股票搜索
- `/valuation/dcf` DCF 估值模型
- `/valuation/comps` 可比公司分析
- `/model/lbo` LBO 情景模型
- `/model/three-statement` 三表预测模型
- `/model/three-statement/scenarios` 三表情景对比
- `/analysis/competitive/competitive` 竞争格局分析
- `/analysis/earnings/earnings` 季报分析

复杂接口统一返回：

- `entity`
- `facts`
- `analysis`
- `meta`

其中 `meta` 固定包含 `schema_version`、`interface_type`、`as_of`、`sources`、`limitations` 等字段。

当前 schema 版本：`2.0.0`

## 快速开始

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
uv venv
source .venv/bin/activate
uv pip install -e .
uv run start
```

服务启动后访问 `http://localhost:8080/docs`。

常用本地验证：

```bash
curl http://127.0.0.1:8080/ping
curl 'http://127.0.0.1:8080/stock/list?market=美股&limit=2'
curl 'http://127.0.0.1:8080/analysis/earnings/earnings?symbol=NVDA'
curl 'http://127.0.0.1:8080/analysis/competitive/competitive?symbol=NVDA&industry=technology'
curl 'http://127.0.0.1:8080/valuation/comps?symbol=NVDA&sector=Semiconductors'
```

## 环境变量

| 变量 | 说明 |
|------|------|
| `TUSHARE_TOKEN` | Tushare Token，可选 |
| `PORT` | HTTP 端口，默认 `8080` |
| `ENV` | `development` / `production` |

## Docker

```bash
docker build -t stock-analysis-api .
docker run -p 8080:8080 stock-analysis-api
```

## 开发说明

- 项目为 HTTP-only
- 事实字段和推导字段必须分层返回，禁止将估算或模型结果写入 `facts`
- 缺少可靠原始数据时返回 `unavailable` / `partial`，不要填 0 或伪造历史
- 共享标准 contract 位于 `src/model/contracts.py`
- HTTP 适配与统一输出位于 `src/analyzer/normalizers.py`
- 共享事实上下文聚合位于 `src/data_provider/fundamental_context.py`
- 当前有效的核心文档位于 `docs/`
  - `docs/plan.md`
  - `docs/http-api-online-audit.md`
  - `docs/data-source-field-spec-audit.md`
  - `docs/architecture-benchmark-notes.md`
- 每次迭代都要更新 `docs/plan.md`，作为唯一任务进展文档
