# Stock Analysis API

股票分析后端服务，当前对外只保留 HTTP REST API。

## 环境准备

- Python 3.12+
- `uv`
- A 股同步与研究能力需要 `TUSHARE_TOKEN`

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

Agent / skill CLI 入口：

```bash
uv run python scripts/stock_analyze.py --market cn --symbols 300827 --mode base --pretty
uv run python scripts/stock_analyze.py --market us --symbols NVDA,MSFT --mode full --pretty
uv run python scripts/trading_run_once.py --codes HK.00700 --buy-above HK.00700=100 --quantity 10 --max-order-notional 2000 --pretty
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

- `POST /stock/analyze`: 唯一公共分析入口，返回统一 stock-analyze snapshot payload
- `POST /watch/poll`: 多股票轮询盯盘，返回 compact snapshot、delta 和 alerts
- `GET /health`: 健康检查，同时触发后台 symbols preflight

## 环境变量

| 变量 | 说明 |
|------|------|
| `TUSHARE_TOKEN` | Tushare Token，A 股主数据源 |
| `TUSHARE_HTTP_URL` | Tushare HTTP URL，可选覆盖默认地址 |
| `PORT` | HTTP 端口，默认 `8080` |
| `ENV` | `development` / `production` |
| `CACHE_DIR` | 本地 SQLite 仓默认目录，可选 |
| `MARKET_DATA_DB_PATH` | 本地 SQLite 仓文件路径，可选 |
| `TRADING_LEDGER_DB_PATH` | 模拟盘 trading ledger SQLite 文件路径，可选 |

## 使用级注意事项

- `scripts/stock_analyze.py` 的 stdout 设计为纯 JSON，方便外部 Agent 直接消费
- `scripts/trading_run_once.py` 默认使用 dry-run broker，只做模拟盘单次执行与 ledger 审计，不连接真实交易环境
- `sync-market-data` 会先读取 `sync_runs` 当前状态，再决定补库、补缺口或直接 `skipped`
- 本地行情仓默认写入 SQLite
- A 股 universe 当前按 Tushare `stock_basic(exchange='', list_status='L')` 的 listed 快照同步
- `cn_daily.is_suspended` 只是停复牌事件标记，不表示完整停牌区间

更细的架构、接口与数据约束见 `AGENTS.md` 与 `docs/`。
