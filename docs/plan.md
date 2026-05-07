# 当前任务计划

更新时间：2026-05-07

## 当前目标

- 优先补齐模拟盘自动交易进入定时轮询前的高 ROI 基础能力：SQLite 持久化 ledger 与内部 dry-run `run_once` CLI
- 补齐模拟盘盘后只读闭环 MVP：从 SQLite ledger 生成每日操作 / 行情摘要，并产出需要人工批准的结构化 `strategy_proposal`
- 补齐显式 opt-in 的 Futu `SIMULATE` broker adapter，默认仍保持 dry-run，禁止真实交易与 `unlock_trade`
- 将 skill / agent 标准化 CLI 能力彻底收口到 `stock-analysis-api`
- 新增内部 `poll_realtime_quotes` CLI，承接原 `stock-analysis-skill` 中的 A 股 / ETF 日内行情轮询逻辑
- 保持 `scripts/stock_analyze.py` 继续作为唯一客观分析 CLI，不改公共 HTTP API
- 启动模拟盘自动交易一期：把 Futu/OpenD 作为 API 内部正式 data provider / broker adapter 接入，先建立确定性 `run_once` 执行闭环
- 迁移 `stock-analysis-skill` `/hkipo` 与 `/research` 已用到的 Futu/OpenD 只读能力到 API 内部 CLI，逐步删除 skill 对 `futuapi` 脚本的运行依赖
- 继续补齐高 ROI Futu/OpenD 只读 provider 能力，优先支持盘口、逐笔、分时、期权链、账户、资金、持仓、订单、成交和流水查询，保持禁止写入、订阅、交易解锁和真实交易

## 最近完成项

- 已保留并稳定运行：
  - `POST /stock/analyze`
  - `POST /watch/poll`
  - `scripts/stock_analyze.py`
- 已确认公共 HTTP API 不需要为本次 skill 对接新增路由
- 已新增内部：
  - `src/services/realtime_quote_polling_service.py`
  - `src/services/realtime_quote_polling_cli.py`
  - `scripts/poll_realtime_quotes.py`
- 已为新 CLI 补充首批 contract 测试，覆盖普通股票、ETF、invalid symbol、legacy realtime 降级与纯 JSON stdout
- `scripts/stock_analyze.py` 已在 CLI 层支持股票名 / 公司名解析；唯一匹配后传标准代码给分析服务，多候选返回 `identity_conflict`。
- 已明确模拟盘自动交易边界：轮询和下单由确定性 worker 执行，Agent 只产出结构化策略迭代建议。
- 已新增 `docs/specs/simulated-trading-automation.md`，约束一期不新增公共 HTTP API、只支持 Futu `SIMULATE`、不直接调用外部 `futuskill` 脚本。
- 已新增 `FutuMarketDataProvider`，通过 Futu OpenD snapshot 标准化输出 `MarketSnapshot`，且 SDK 延迟导入，不影响无 OpenD 环境下的模块 import。
- 已新增交易领域 contract 与 `TradingAutomationService.run_once`，覆盖行情读取、策略信号、最大订单金额风控、`SIMULATE` 订单请求和 idempotency key 去重。
- 已修复全量 pytest 暴露的两个日期漂移问题：日线覆盖晚于目标交易日的 current 判定、yfinance 分红 TTM 使用系统日期导致的不稳定归一化。
- 已新增内部 `scripts/futu_market_data.py`，覆盖 `/hkipo` 与 `/research` 已用到的 Futu/OpenD 只读能力：`global-state`、`ipo-list`、`kline`、`snapshot`。
- 已将 `futu-api>=10.4.6408` 纳入 API 仓库依赖，真实 CLI 调用不再依赖外部 skill 的 Python 环境。
- 已将 `src.services` package import 改为 lazy export，避免 `scripts/futu_market_data.py` 导入 Futu CLI 时初始化无关 SQLite 行情仓。
- 已新增 `SqliteTradingLedger`，持久化 trading run、risk decision、order request/result 和 `idempotency_key`。
- 已新增内部 `scripts/trading_run_once.py`，默认 dry-run broker，支持 `--snapshots-json` 离线行情注入与 SQLite ledger 复用。
- 已补充持久化 ledger 和 dry-run CLI contract 测试，覆盖跨 service 实例重复执行不重复提交订单。
- 已更新 `docs/specs/skill-cli-contract.md`，补齐 `trading_run_once.py` 的输入、输出、降级和幂等语义。
- 已补充真实调用链路验证：`trading_run_once.py` 新增 subprocess 级入口测试，覆盖真实脚本入口、stdout JSON、SQLite ledger 跨进程去重。
- 已修复 Futu/OpenD CLI 真实链路输出污染：SDK stdout 日志和 DeprecationWarning 不再污染 CLI 输出；Futu `NaN` / `Infinity` 原始值统一归一化为 `null`。
- 已用真实 OpenD 验证 `scripts/futu_market_data.py global-state --json` 与 `scripts/trading_run_once.py` 无 `--snapshots-json` 路径，stdout 可被严格 JSON parser 解析且 stderr 为空。
- 已为 `trading_run_once.py` 增加默认 SQLite 调度锁；并发触发时返回 `status=skipped / reason=lock_unavailable`，不会继续读取行情或提交 dry-run broker。
- 已新增 `scripts/trading_scheduler_tick.py`，作为 cron / launchd / Agent 高频调用入口；支持 active window、执行间隔、state key、`--force`，到点后复用 `trading_run_once.py`。
- 已同步 `stock-analysis-skill` 对 dry-run 单轮执行和 scheduler tick 的路由说明；skill 只指向 API CLI，不放开真实交易、交易解锁或订阅能力。
- 已新增 `scripts/trading_daily_summary.py`，只读 SQLite trading ledger 汇总当日 run、order、risk decision 和 snapshot 首末变化。
- 已新增 `scripts/trading_strategy_review.py`，基于 ledger summary 输出 `ledger_snapshot_replay` 指标和需人工批准的结构化 `strategy_proposal`，不自动应用策略。
- 已补充盘后真实脚本链路测试：`trading_run_once.py` 写 ledger 后，`trading_daily_summary.py` 与 `trading_strategy_review.py` 读取同一 ledger 并输出严格 JSON。
- 已将 `scripts/trading_daily_summary.py` 默认输出改为 summary-only：只保留关键信息，`orders` / `risk_decisions` / `runs` 明细必须显式 `--include-details` 才输出。
- 已新增 `FutuSimulateBroker` 与 `FutuOpenDTradeGateway`，`trading_run_once.py --broker futu-simulate` 可显式启用 Futu `SIMULATE` broker；默认仍是 dry-run，且 `futu-simulate` 禁止与 `--snapshots-json` 混用。
- `trading_scheduler_tick.py` 已支持透传 `--broker`，因此显式 opt-in 的 Futu `SIMULATE` 也能接入 cron / launchd / Agent 调度 tick。
- 已新增 `scripts/trading_strategy_backtest.py`，支持注入 K 线 JSON 或 Futu 历史 K 线，对固定 threshold 策略做离线回测；该入口不读写 ledger、不触发 broker。
- 已扩展 `scripts/futu_market_data.py` Futu/OpenD 只读查询能力，新增 `order-book`、`ticker`、`rt-data`、`option-expirations`、`option-chain`、`account`、`positions`、`orders`、`deals`、`cash-flow` 子命令。
- 已补充 Futu 只读 CLI contract 与安全回归测试，覆盖新增命令 stdout JSON、Futu `SIMULATE` 账户类只读查询，以及 CLI 不暴露写入类子命令。

## 当前状态

- 公共对外协议仍然只有 HTTP REST API
- skill / agent 可消费的内部 CLI 当前为：
  - `scripts/stock_analyze.py`
  - `scripts/poll_realtime_quotes.py`
  - `scripts/futu_market_data.py`
  - `scripts/trading_run_once.py`
  - `scripts/trading_scheduler_tick.py`
  - `scripts/trading_daily_summary.py`
  - `scripts/trading_strategy_review.py`
  - `scripts/trading_strategy_backtest.py`
- `scripts/stock_analyze.py` 当前支持代码直传与中文股票名解析，股票名解析只属于内部 CLI contract，不新增公共 HTTP API。
- `scripts/poll_realtime_quotes.py` 当前 contract 固定为轻量 quote payload：
  - `status / computed_at / source / request / summary / items`
- `scripts/poll_realtime_quotes.py` 当前实现固定为 Tushare-only：
  - 身份信息：`stock_basic / etf_basic`
  - 实时行情：`quotation`
  - 降级：旧版 `get_realtime_quotes`
- 模拟盘自动交易一期已完成最小执行闭环：
  - 已新增 `src/data_provider/sources/futu.py`
  - 已新增 `src/model/trading.py`
  - 已新增 `src/services/trading_automation_service.py`
  - 已新增 `src/repositories/trading_ledger_repository.py`
  - 已新增 `src/services/trading_run_once_cli.py`
  - 已新增 `src/services/futu_simulate_broker.py`
  - 已新增 `src/services/trading_daily_summary_cli.py`
  - 已新增 `src/services/trading_strategy_review_cli.py`
  - 已新增 `src/services/trading_strategy_backtest_cli.py`
- Futu/OpenD hkipo / research 迁移在 API 侧已完成内部 CLI 与 contract 测试：
  - 已新增 `src/services/futu_market_data_cli.py`
  - 已新增 `scripts/futu_market_data.py`
  - 已覆盖 `global-state` / `ipo-list` / `kline` / `snapshot` / `order-book` / `ticker` / `rt-data` / `option-expirations` / `option-chain` / `account` / `positions` / `orders` / `deals` / `cash-flow` JSON contract
- Futu CLI import 现在不依赖行情仓可写性；只执行实际 Futu 子命令时才连接 OpenD。
- Futu CLI 只读账户类查询固定使用 Futu `SIMULATE` 环境；CLI 不暴露下单、改单、撤单、交易解锁或订阅子命令。
- `scripts/trading_daily_summary.py` 当前仅做只读盘后汇总，不进入实时交易链路；默认 summary-only，明细输出需显式 opt-in。

## 下一步计划

- 继续迁移剩余 Futu 只读 provider 能力：窝轮 / 牛熊证、资金流、资金分布、经纪队列、板块与成分股、条件选股、期货资料等尚未覆盖查询
- 如需从候选 `strategy_proposal` 进入策略版本管理，再补 schema 校验、人工批准记录和运行时策略配置读取机制
- 后续如需更真实的回测，再补交易成本、滑点、成交量约束和分钟线 / tick 级执行模型

## 已知风险与阻塞

- Tushare `quotation` 可能受源端权限或可用性影响，因此 legacy realtime 降级语义必须保持真实，不得伪装成完整 realtime
- `TushareDataSource.get_pro()` 当前仍可能打印初始化信息；CLI 层必须继续保证 stdout 纯 JSON
- `stock-analysis-skill` 将不再保留本地 wrapper，文档必须明确调用入口在 API 仓库，避免使用方继续假设 skill 根目录存在同名脚本
- 股票名解析依赖 `cn_symbols/us_symbols` 本地目录和必要时的目录刷新；多候选时必须由调用方提示用户澄清，不得猜测。
- Futu/OpenD 依赖本机 OpenD 进程、端口和权限；单元测试必须使用 fake gateway / broker，不能依赖真实网络或真实账户。
- 自动交易一期仅允许 `SIMULATE`，不实现真实交易、交易解锁、订阅推送或 OpenD 配置写入。
- 策略迭代必须先落结构化 proposal 和回测门槛，不能让 Agent 在轮询链路里直接决定下单。
- SQLite ledger 已能跨进程复用 `idempotency_key` 去重，`trading_run_once.py` 默认调度锁已覆盖单机并发 worker；后续若多机部署，需要替换为共享锁或集中式调度。
