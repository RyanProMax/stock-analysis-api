# Skill / Agent CLI Contract

更新时间：2026-05-07

本文件是 `stock-analysis-api` 内部 skill / agent CLI contract 的唯一规格说明，不属于公共 HTTP API 文档。

## 目标

- 让外部 `stock-analysis-skill` 与其他 agent 直接消费本仓库 CLI
- 统一内部脚本的输入、输出、状态语义和降级规则
- 保证 CLI stdout 始终为机器可读 JSON

## CLI 列表

### 1. `scripts/stock_analyze.py`

用途：

- 当前唯一客观分析 CLI
- 能力与 `POST /stock/analyze` 保持同构

参数：

- `--market`
- `--symbols`: 逗号分隔；支持标准代码，也支持中文股票名 / 公司名输入
- `--start-date`
- `--end-date`
- `--mode`
- `--pretty`

输出：

- 顶层固定为 `StandardResponse`
- `data` 内部 payload 固定为：
  - `status`
  - `computed_at`
  - `source`
  - `market`
  - `strategy`
  - `request`
  - `items`

说明：

- 本 CLI 继续作为 skill / agent 的唯一客观分析入口
- `--symbols` 若为明确代码，直接进入分析服务；若为中文股票名 / 公司名，CLI 先查询 `symbol_catalog_service.search_symbols`。
- 股票名解析语义：唯一精确匹配或唯一候选时，传递标准 `symbol` 给分析服务；无匹配返回 `identity_not_found`；多候选返回 `identity_conflict` 并附候选 `symbol / ts_code / name / market / exchange`。
- 解析失败仍输出 `StandardResponse` JSON，`data.items[0].status = failed`，不输出裸异常。
- 不输出自由文本总结、主观 thesis、confidence 或 target price

### 2. `scripts/poll_realtime_quotes.py`

用途：

- 批量查询 A 股 / ETF 最新日内行情
- 为 skill / agent 提供低 token 的 quote polling 结果

参数：

- `--symbols`
- `--pretty`

输出：

- 顶层固定返回：
  - `status`
  - `computed_at`
  - `source`
  - `request`
  - `summary`
  - `items`
- 单个 item 固定返回：
  - `requested_symbol`
  - `status`
  - `error`
  - `info`
  - `quote_data`

`quote_data` 固定字段：

- `price`
- `change_pct`
- `change_amount`
- `open`
- `high`
- `low`
- `pre_close`
- `volume`
- `amount`
- `volume_ratio`
- `turnover_rate`
- `amplitude`
- `as_of`
- `source`
- `mode`

语义约束：

- `change_pct / turnover_rate / amplitude` 一律使用 ratio 机器值
- `mode` 当前仅允许：
  - `realtime`
  - `legacy_realtime`
- `status` 当前仅允许：
  - `ok`
  - `partial`
  - `failed`

### 3. `scripts/trading_run_once.py`

用途：

- 模拟盘自动交易一期的内部单次执行 CLI
- 供 agent / worker / cron / launchd 调用确定性 `run_once` 流程
- 默认只使用 dry-run broker，不连接真实交易环境

参数：

- `--codes`: 逗号分隔，使用 Futu 格式，例如 `HK.00700`
- `--strategy-version`
- `--buy-above`: 逗号分隔阈值，例如 `HK.00700=100`
- `--quantity`
- `--max-order-notional`
- `--ledger-db`: 覆盖 SQLite ledger 路径；未传时读取 `TRADING_LEDGER_DB_PATH` 或 `.cache/trading_ledger.sqlite`
- `--snapshots-json`: 行情快照 JSON 字符串或文件路径；用于测试、回放和离线验证
- `--account-cash`
- `--currency`
- `--pretty`

输出：

- 顶层固定返回：
  - `status`
  - `run_id`
  - `strategy_version`
  - `started_at`
  - `request`
  - `source`
  - `broker_mode`
  - `account`
  - `positions`
  - `snapshots`
  - `signals`
  - `risk_decisions`
  - `orders`
  - `finished_at`

语义约束：

- CLI stdout 必须是纯 JSON。
- `--snapshots-json` 存在时只使用注入行情，不连接 Futu/OpenD。
- 未传 `--snapshots-json` 时允许读取 Futu/OpenD snapshot，但 broker 仍固定为 dry-run。
- 已通过风控并提交过的订单必须写入 SQLite ledger，`idempotency_key` 跨进程生效。
- 重复执行同一策略版本、代码、方向、数量和触发价时，不得重复提交 dry-run broker 订单。

## 数据源与降级规则

### `stock_analyze.py`

- 按既有 `stock_analyze_service` 流程执行
- 来源、partial、permission 等状态语义沿用现有 `meta.modules`

### `poll_realtime_quotes.py`

- 当前固定为 Tushare-only
- 身份信息：
  - `stock_basic`
  - `etf_basic`
- 行情优先级：
  1. `quotation`
  2. 旧版 `get_realtime_quotes`

降级规则：

- 只要 `quotation` 未成功但 legacy realtime 成功：
  - item `status = ok`
  - `quote_data.mode = legacy_realtime`
- 若两条链路都失败：
  - item `status = failed`
  - `quote_data = null`

### `trading_run_once.py`

- 行情来源：
  - `--snapshots-json` 注入的静态行情
  - 或 Futu/OpenD snapshot
- broker 当前固定为 dry-run broker
- 审计与幂等固定写入 SQLite trading ledger
- 不新增公共 HTTP API，不调用外部 `futuapi` skill 脚本

## 输出质量要求

- CLI stdout 必须是纯 JSON，不得混入初始化日志或调试 print
- 失败也应尽量输出结构化 JSON，而不是裸异常堆栈
- 该 contract 仅供内部 skill / agent 消费，不写入 `docs/api.md`
