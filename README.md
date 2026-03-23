# Stock Analysis API

股票分析后端服务，当前仅保留 HTTP REST API。

## 环境准备

- Python 3.12+
- `uv`
- A 股同步需要 `TUSHARE_TOKEN`

## 安装与启动

```bash
uv venv
source .venv/bin/activate
uv pip install -e .
uv run start
```

服务启动后访问：

- Swagger UI: `http://127.0.0.1:8080/docs`
- 健康检查: `http://127.0.0.1:8080/health`

## 常用命令

启动 HTTP 服务：

```bash
uv run start
```

同步本地行情仓：

```bash
uv run sync-market-data --market cn --scope all --start-date 2026-01-01
uv run sync-market-data --market cn --scope symbol --symbol 300827 --days 30
uv run sync-market-data --market us --scope symbol --symbol NVDA --days 30
```

后台常驻 HTTP 服务：

```bash
scripts/status_http_service.sh
scripts/restart_http_service.sh
```

格式化：

```bash
black --line-length 100 .
```

## HTTP API

主要端点与用途：

- `POST /stock/analyze`: 单股或多股综合分析，返回标准化的 `entity / facts / analysis / meta`
- `GET /stock/list`: 按市场分页获取股票列表
- `POST /stock/search`: 按代码、名称或拼音搜索股票
- `POST /watch/poll`: 多股票轮询盯盘，支持 A 股和美股，返回 snapshot、delta 和 alerts
- `GET /valuation/dcf`: DCF 估值结果
- `GET /valuation/comps`: 可比公司估值结果
- `GET /model/lbo`: LBO 情景测算
- `GET /model/three-statement`: 三表预测结果
- `GET /model/three-statement/scenarios`: 三表多情景对比
- `GET /analysis/competitive/competitive`: 竞争格局分析
- `GET /analysis/earnings/earnings`: 财报与业绩解读

## 环境变量

| 变量 | 说明 |
|------|------|
| `TUSHARE_TOKEN` | Tushare Token，A 股主数据源 |
| `TUSHARE_HTTP_URL` | Tushare HTTP URL，可选覆盖默认地址 |
| `PORT` | HTTP 端口，默认 `8080` |
| `ENV` | `development` / `production` |
| `CACHE_DIR` | 本地 SQLite 仓默认目录，可选 |
| `MARKET_DATA_DB_PATH` | 本地 SQLite 仓文件路径，可选 |

## 使用级注意事项

- `sync-market-data` 会先读取 `sync_runs` 当前状态，再决定补库、补缺口或直接 `skipped`
- 本地行情仓默认写入 SQLite
- A 股 universe 当前按 Tushare `stock_basic(exchange='', list_status='L')` 的 listed 快照同步
- `cn_daily.is_suspended` 只是停复牌事件标记，不表示完整停牌区间

更细的仓表语义、同步状态模型和停牌设计见 `AGENTS.md` 与 `docs/`。
