# 当前任务计划

更新时间：2026-05-06

## 当前目标

- 将 skill / agent 标准化 CLI 能力彻底收口到 `stock-analysis-api`
- 新增内部 `poll_realtime_quotes` CLI，承接原 `stock-analysis-skill` 中的 A 股 / ETF 日内行情轮询逻辑
- 保持 `scripts/stock_analyze.py` 继续作为唯一客观分析 CLI，不改公共 HTTP API
- 启动模拟盘自动交易一期：把 Futu/OpenD 作为 API 内部正式 data provider / broker adapter 接入，先建立确定性 `run_once` 执行闭环
- 迁移 `stock-analysis-skill` `/hkipo` 与 `/research` 已用到的 Futu/OpenD 只读能力到 API 内部 CLI，逐步删除 skill 对 `futuapi` 脚本的运行依赖

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

## 当前状态

- 公共对外协议仍然只有 HTTP REST API
- skill / agent 可消费的内部 CLI 当前为：
  - `scripts/stock_analyze.py`
  - `scripts/poll_realtime_quotes.py`
  - `scripts/futu_market_data.py`
- `scripts/stock_analyze.py` 当前支持代码直传与中文股票名解析，股票名解析只属于内部 CLI contract，不新增公共 HTTP API。
- `scripts/poll_realtime_quotes.py` 当前 contract 固定为轻量 quote payload：
  - `status / computed_at / source / request / summary / items`
- `scripts/poll_realtime_quotes.py` 当前实现固定为 Tushare-only：
  - 身份信息：`stock_basic / etf_basic`
  - 实时行情：`quotation`
  - 降级：旧版 `get_realtime_quotes`
- 当前仍待完成：
  - `docs/architecture.md` / `docs/specs/` 的内部 CLI 规格补齐
  - cross-repo `stock-analysis-skill` 文档与命名收口
  - 端到端验证与双仓提交
- 模拟盘自动交易一期已完成最小执行闭环：
  - 已新增 `src/data_provider/sources/futu.py`
  - 已新增 `src/model/trading.py`
  - 已新增 `src/services/trading_automation_service.py`
- Futu/OpenD hkipo / research 迁移在 API 侧已完成内部 CLI 与 contract 测试：
  - 已新增 `src/services/futu_market_data_cli.py`
  - 已新增 `scripts/futu_market_data.py`
  - 已覆盖 `global-state` / `ipo-list` / `kline` / `snapshot` JSON contract

## 下一步计划

- 更新 `docs/architecture.md`，明确 `poll_realtime_quotes.py` 是内部 CLI，不属于公共 API
- 新增 `docs/specs/skill-cli-contract.md`，统一记录 `poll_realtime_quotes.py` 与 `stock_analyze.py` 的输入、输出与状态语义
- 完成 `stock-analysis-skill` 仓库重构：
  - 删除本地 wrapper
  - 文档改名为 `stock-analysis-skill`
  - 直接通过 `STOCK_ANALYSIS_API_ROOT` 消费本仓库 CLI
- 运行 API / skill 两仓验证并分别提交 commit
- 新增真实 Futu `SIMULATE` broker adapter，封装账户、持仓、下单和撤单查询，但继续禁止真实交易与 `unlock_trade`
- 增加本地持久化 ledger，替换当前只用于一期 contract 的 `InMemoryTradingLedger`
- 增加定时调度脚本和单次 dry-run 入口，供 Agent / launchd / cron 调用
- 补齐盘后总结、回测分析和结构化 `strategy_proposal` 评审链路

## 已知风险与阻塞

- Tushare `quotation` 可能受源端权限或可用性影响，因此 legacy realtime 降级语义必须保持真实，不得伪装成完整 realtime
- `TushareDataSource.get_pro()` 当前仍可能打印初始化信息；CLI 层必须继续保证 stdout 纯 JSON
- `stock-analysis-skill` 将不再保留本地 wrapper，文档必须明确调用入口在 API 仓库，避免使用方继续假设 skill 根目录存在同名脚本
- 股票名解析依赖 `cn_symbols/us_symbols` 本地目录和必要时的目录刷新；多候选时必须由调用方提示用户澄清，不得猜测。
- Futu/OpenD 依赖本机 OpenD 进程、端口和权限；单元测试必须使用 fake gateway / broker，不能依赖真实网络或真实账户。
- 自动交易一期仅允许 `SIMULATE`，不实现真实交易、交易解锁、订阅推送或 OpenD 配置写入。
- 策略迭代必须先落结构化 proposal 和回测门槛，不能让 Agent 在轮询链路里直接决定下单。
- 当前 `InMemoryTradingLedger` 只保证单进程内幂等，进入定时调度前必须落 SQLite 或同等持久化存储。
