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
uv run python scripts/trading_run_once.py --broker futu-simulate --codes HK.00700 --buy-above HK.00700=100 --quantity 10 --max-order-notional 2000
uv run python scripts/trading_scheduler_tick.py --codes HK.00700 --buy-above HK.00700=100 --quantity 10 --max-order-notional 2000
uv run python scripts/trading_daily_summary.py --date 2026-05-07 --pretty
uv run python scripts/trading_strategy_review.py --date 2026-05-07 --min-runs 3 --pretty
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
| `FUTU_OPEND_HOST` | Futu OpenD 地址，默认 `127.0.0.1` |
| `FUTU_OPEND_PORT` | Futu OpenD 端口，默认 `11111` |

## 使用级注意事项

- `scripts/stock_analyze.py` 的 stdout 设计为纯 JSON，方便外部 Agent 直接消费
- `scripts/trading_run_once.py` 默认使用 dry-run broker 和 SQLite 调度锁，只做模拟盘单次执行与 ledger 审计；只有显式传 `--broker futu-simulate` 时才连接 Futu `SIMULATE` broker
- `--broker futu-simulate` 固定使用 Futu `TrdEnv.SIMULATE`，不调用 `unlock_trade`，也不允许和 `--snapshots-json` 混用
- `scripts/trading_scheduler_tick.py` 是 cron / launchd / Agent 的调度 tick 入口，只判断时间窗和间隔，到点后调用单次执行；`--broker` 会透传给 `trading_run_once.py`
- `scripts/trading_daily_summary.py` 只读 SQLite trading ledger，生成当日 run / order / 风控 / snapshot 摘要
- `scripts/trading_strategy_review.py` 基于 ledger 摘要生成候选 `strategy_proposal`，不会写入策略配置或触发盘中下单
- `sync-market-data` 会先读取 `sync_runs` 当前状态，再决定补库、补缺口或直接 `skipped`
- 本地行情仓默认写入 SQLite
- A 股 universe 当前按 Tushare `stock_basic(exchange='', list_status='L')` 的 listed 快照同步
- `cn_daily.is_suspended` 只是停复牌事件标记，不表示完整停牌区间

更细的架构、接口与数据约束见 `AGENTS.md` 与 `docs/`。
