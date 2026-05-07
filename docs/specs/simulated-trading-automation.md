# 模拟盘自动交易一期规格

更新时间：2026-05-07

## 目标

在 `stock-analysis-api` 内建设一个可审计、可回测、可迭代的模拟盘自动交易基础闭环：

1. 定时 worker 按固定流程轮询行情、执行当前策略、通过风控、写入模拟盘订单和运行结果。
2. 每日收盘后产出行情与操作总结，后续接入回测评估。
3. Agent 只参与盘后分析和策略迭代方向生成，不参与轮询链路的即时下单判断。
4. Futu/OpenD 作为 API 内部正式 data provider / broker adapter 接入，不直接调用外部 `futuskill` 脚本。

## 边界

- 第一期不新增公共 HTTP API。
- 第一期只提供内部 service / script 能力，后续如需外部控制面再补 HTTP contract。
- Futu 交易环境固定为 `SIMULATE`。
- 不实现真实交易、不调用或封装 `unlock_trade`、不写 OpenD 配置、不做订阅推送。
- 不把 `stock-analysis-skill` 或 `futuskill` 变成 API 的运行时依赖；skill 侧经验只作为 adapter 设计参考。
- 订单执行必须由确定性 service 完成，不能把实时下单决策交给 Agent 文案输出。

## 一期模块

### 行情 provider

- 新增 `src/data_provider/sources/futu.py`
- `FutuMarketDataProvider` 从 Futu OpenD snapshot 读取行情。
- 输入代码统一为 Futu 格式：
  - `HK.00700`
  - `US.AAPL`
  - `SH.600000`
  - `SZ.000001`
- 输出统一为 `MarketSnapshot`，保留 `source="futu_opend"` 和原始 `raw`。

### 交易执行 service

- 新增统一交易 contract：账户、持仓、行情、信号、订单请求。
- 新增 `TradingAutomationService.run_once(codes)`，单次执行流程固定为：
  1. 读取市场 snapshot
  2. 读取账户和持仓
  3. 用当前策略版本生成机器可解释 signal
  4. 风控检查
  5. 生成带 idempotency key 的 `SIMULATE` 订单
  6. 调用 broker adapter 下单
  7. 返回结构化执行结果
- 首个策略实现只用于建立 contract，不代表正式交易策略。

### 持久化 ledger 与 dry-run CLI

- 新增 SQLite trading ledger，用于保存：
  - 每次 `run_once` 的请求、状态和完整结果。
  - 每条风险决策的结构化 payload。
  - 每条已提交模拟订单的 `idempotency_key`、请求和 broker 返回结果。
- ledger 默认路径读取 `TRADING_LEDGER_DB_PATH`，未设置时使用 `.cache/trading_ledger.sqlite`。
- `idempotency_key` 必须跨进程、跨服务实例生效；同一个策略版本、代码、方向、数量和触发价重复执行时，不得重复提交 broker 订单。
- SQLite ledger 同时维护调度锁；内部 CLI 默认使用 `trading_run_once` 锁，避免 cron / launchd / Agent 并发触发同一轮 dry-run。
- 拿不到调度锁时必须返回结构化 `status=skipped` 和 `reason=lock_unavailable`，不得进入行情、策略和 broker 提交流程。
- 新增内部 CLI `scripts/trading_run_once.py`：
  - 仅属于内部 Agent / worker 入口，不新增公共 HTTP API。
  - 默认 broker 为 dry-run broker，只返回模拟提交结果，不连接真实交易环境。
  - 可通过 `--snapshots-json` 注入行情快照，供测试、回放和离线验证使用。
  - 未传 `--snapshots-json` 时允许读取 Futu/OpenD snapshot，但仍只走 dry-run broker。
  - stdout 必须保持纯 JSON。

### 调度 tick

- 新增内部 CLI `scripts/trading_scheduler_tick.py`，用于 cron / launchd / Agent 高频调用。
- 调度 tick 只负责：
  - 判断当前时间是否处于 active window。
  - 判断距离上次执行是否达到 `--interval-seconds`。
  - 生成或读取 `state_key`，记录本轮调度状态。
  - 到点后调用 `trading_run_once.py` 同一套单轮执行逻辑。
- 调度 tick 不实现策略、风控、broker 或交易逻辑。
- 未到时间窗返回 `status=skipped / reason=outside_active_window`。
- 未到执行间隔返回 `status=skipped / reason=not_due`。
- 单轮执行拿不到调度锁时透传 `status=skipped / reason=lock_unavailable`。

### 盘后总结与策略评审

- 新增内部 CLI `scripts/trading_daily_summary.py`，只读 SQLite trading ledger，按交易日和时区汇总：
  - `run_once` 执行次数、状态与请求。
  - 当日 snapshot 的首末价格、变化比例和来源。
  - dry-run order、broker result、risk decision 与拒绝原因计数。
- 新增内部 CLI `scripts/trading_strategy_review.py`，只读 daily summary 并生成 ledger replay 指标：
  - 当前 MVP 的回测口径为 `ledger_snapshot_replay`，即用 ledger 中已有 snapshot 和 dry-run order 做当日回放式评估。
  - 后续接入历史 K 线或分钟线回测时，必须在输出中显式区分方法名，不能把 replay 指标伪装成完整历史回测。
- `trading_strategy_review.py` 只输出结构化 `strategy_proposal`：
  - `approval_required=true`
  - `effective_status=candidate_only` 或 `not_applied`
  - 不写策略配置、不改调度 state、不触发 broker。
- 评审 gate 第一阶段至少包含：
  - `--min-runs`
  - `--max-rejection-rate`
  - 是否具备可回放 snapshot

### Agent 参与点

Agent 只在盘后或离线任务中消费：

- 当日行情和订单摘要
- 策略版本表现
- 回测指标
- 风控拒绝原因

Agent 输出只能是结构化 `strategy_proposal`，必须经过：

1. schema 校验
2. 回测门槛
3. 人工批准

才能进入候选或生效策略版本。

## 测试要求

- 单元测试必须用 fake Futu gateway / fake broker，不依赖真实 OpenD。
- 覆盖 Futu code normalization。
- 覆盖 Futu snapshot 到 `MarketSnapshot` 的字段映射。
- 覆盖 `run_once` 默认 `SIMULATE` 下单。
- 覆盖 idempotency key 去重，重复轮询不能重复下单。
- 覆盖最大订单金额风控拒绝。
- SDK 缺失或 OpenD 不可用时，模块 import 不能失败，只有真实调用时返回明确错误。
