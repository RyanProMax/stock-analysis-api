# 架构约束

更新时间：2026-05-07

## 系统边界

- 项目当前仅保留 HTTP REST API，对外协议不再包含 MCP
- 仓库允许保留内部 `scripts/` 作为 Agent / skill 调用入口，但这类脚本不属于公共接口，不改变“HTTP 是对外协议”的边界
- 当前对 skill / agent 暴露的内部 CLI 固定为：
  - `scripts/stock_analyze.py`
  - `scripts/poll_realtime_quotes.py`
  - `scripts/futu_market_data.py`
  - `scripts/trading_run_once.py`
  - `scripts/trading_scheduler_tick.py`
- 公共研究分析能力统一收敛到单一 `POST /stock/analyze` 入口，不再暴露 `/analysis/research/snapshot`、`/valuation/*`、`/model/*`、`/analysis/*`、`/stock/list`、`/stock/search` 等额外公共分析或基础查询路由
- 模拟盘自动交易能力第一阶段只作为内部 worker / script 能力建设，不新增公共 HTTP 路由
- Futu/OpenD 只能作为正式 `data_provider` / broker adapter 接入，不从 API 仓库反向调用外部 `futuskill` 脚本
- `README.md` 只承担使用说明职责；架构、仓表语义、状态模型和演进约束统一写入 `docs/architecture.md` 与 `docs/specs/`
- 外部 Agent 的盯盘能力统一通过单一轮询接口提供，不提供额外的 cursor、rules、health 等公共盯盘接口
- 公共能力新增优先通过 HTTP 路由、schema、文档和测试交付
- 业务逻辑放在 `src/services/`、`src/repositories/` 或 `src/analyzer/`
- 标准化 contract 放在 `src/model/contracts.py` 和 `src/analyzer/normalizers.py`

## 模块边界

```text
scripts/            # 内部脚本入口（skill / agent 调用），不属于公共 API
src/
├── analyzer/         # 因子计算、分析拼装、标准化适配
├── api/              # FastAPI 路由、schema 与 deps
├── core/             # 兼容层与流程编排
├── data_provider/    # 外部数据源接入、fallback 与字段采集
├── model/            # 领域模型与统一 contract
├── repositories/     # SQLite 持久化访问
├── services/         # 业务编排服务
├── storage/          # 兼容导入层，不再承载正式业务实现
└── utils/            # 工具
```

- `api/` 只负责 HTTP 输入输出，不承载业务规则
- `scripts/` 只负责内部脚本参数解析、结果输出和轻量编排，不承载核心业务规则
- `scripts/poll_realtime_quotes.py` 的核心业务逻辑必须落在 `src/services/`，脚本本身只负责参数解析与纯 JSON 输出
- `services/` 负责工作流、读写编排和聚合逻辑
- `repositories/` 负责单机 SQLite 行情仓访问，不承载分析规则
- `data_provider/` 负责取数、source chain、fallback、字段原始语义维护，不反向依赖 SQLite
- `data_provider/sources/futu.py` 负责 Futu OpenD SDK 适配和行情 snapshot 标准化；账户、持仓、模拟盘订单只能通过 service 层定义的 broker contract 暴露
- `scripts/futu_market_data.py` 只暴露 hkipo / research 已迁移所需的 Futu/OpenD 只读能力：OpenD global state、IPO list、history kline 和 snapshot
- `scripts/trading_run_once.py` 只暴露模拟盘一期单次执行入口，默认 dry-run broker；核心流程必须落在 `TradingAutomationService`，审计与幂等必须落在 SQLite trading ledger
- `scripts/trading_run_once.py` 默认使用 SQLite 调度锁；并发触发时只能有一个 worker 进入行情 / 策略 / broker 流程，其余调用返回 `status=skipped`
- `scripts/trading_scheduler_tick.py` 只负责 cron / launchd / Agent 调度判断：时间窗、间隔和 state key；到点后复用 `trading_run_once.py` 的单轮执行能力，不复制策略或风控逻辑
- `core/` 仅保留流程编排和旧导入兼容
- `model/` 负责统一 contract，避免 route 或 provider 私自扩字段语义

## 输出 contract 约束

- 复杂接口默认返回 `entity`、`facts`、`analysis`、`meta`
- `POST /stock/analyze` 是当前唯一公共重型分析入口，外层仍包在 `StandardResponse.data` 中；其内部 payload 顶层固定返回 `status`、`computed_at`、`source`、`market`、`strategy`、`request`、`items`
- `POST /stock/analyze` 的请求体只允许：
  - `market`
  - `symbols`
  - `start_date`
  - `end_date`
  - `mode`
- `mode` 固定为 `base` / `full`
- `/stock/analyze` 的 item 固定返回：
  - `requested_symbol`
  - `status`
  - `error`
  - `info`
  - `summary`
  - 成功产出业务数据的模块 body
  - `meta`
- `/stock/analyze` 的模块 body 统一瘦身：
  - 原始块只保留 `records`
  - 结构化模块不再公开 `entity`、`meta`、`module_status`、`module_error`、`attempted_sources`
  - 重复状态、来源、限制说明统一上收至 `item.meta.modules`
- `/stock/analyze` 的 `summary` 是跨市场统一汇总层，用于承载 Agent 决策所需的关键确定性摘要，替代旧的 CN-only `derived`
- `/stock/analyze` 的 `summary` 采用 FSP 风格研究顺序组织，首位固定为 `research_strategy`，用于表达：
  - `expectations_vs_reported`
  - `fundamental_quality`
  - `valuation_context`
  - `catalyst_path`
  - `price_action_confirmation`
  - `cross_signal_alignment`
  - `risk_flags`
  - `evidence_strength`
- `/stock/analyze` 的 `technical` 是公共分析 contract 的固定模块，用于承载：
  - `trend`
  - `technical_signals`
  - `fear_greed`
- `/stock/analyze` 的 `technical` 是研究辅助确认层，不单独承担“买卖建议”语义；其公共输出应优先表达趋势确认、动量、量价、波动与失效条件
- 盯盘接口默认返回 compact snapshot，不复用重型分析报告整包 payload
- `facts` 仅允许 `reported` / `consensus`
- `analysis` 仅允许 `derived` / `estimate` / `model_output`
- 比例型机器值统一存 `ratio`
- 缺少可靠原始数据时宁可降级，也不要伪造历史或共识

## 数据与来源约束

- `facts` 优先使用 statement/event 等具备明确期别和来源语义的数据
- `snapshot` 型字段不得混充季度事实或报表期事实
- A 股与美股的 canonical 日线历史优先沉淀到本地 SQLite 行情仓，作为 watch 与分析接口的首选历史数据来源
- SQLite 只保存数据源返回的必要持久信息与事实型扩展字段，不保存分析报告缓存，不保存 5-10 分钟级 watch baseline
- SQLite 行情仓只承载单机、单写多读的 EOD/日线场景，不承载分钟线、tick 或多实例共享写入
- SQLite 日线仓主表固定为：
  - `cn_symbols`
  - `cn_daily`
  - `us_symbols`
  - `us_daily`
  - `sync_runs`
- `cn_symbols` 只保存当前上市 A 股股票 + ETF 最新快照，不建模历史状态
- `cn_symbols.market` 直接承担类型区分：股票保留原板块口径，ETF 固定为 `ETF`
- `cn_symbols.daily_start_date` / `daily_end_date` 是本地 `cn_daily` 覆盖摘要，只表示本地已落库的最早 / 最晚交易日
- 覆盖摘要用于同步前置剪枝和快速状态判断，但不能替代对 `cn_daily` 的精确校验
- A 股 current universe 固定以 `Tushare stock_basic(exchange='', list_status='L') + etf_basic(list_status='L')` 为准
- `cn_daily` 的全市场补库口径固定为当前上市 A 股、自 `2026-01-01` 起的日线数据
- `cn_daily` 主列应覆盖 Tushare `daily`、`daily_basic`、`adj_factor`、`stk_limit`、`suspend_d` 中稳定且标准化的日级市场事实
- `cn_daily` 只保存真实存在的日线事实，不为停牌日期补 synthetic row
- `cn_daily.is_suspended` 只表示“这条已有日线 row 命中了停复牌事件”，不是持续状态，也不能解释整段无 row 的停牌区间
- `suspend_d` 当前只作为同步阶段的辅助事实源使用，不单独落业务表
- `extra` 只保留非标准、低频或暂不标准化的事实字段，不承担长期核心市场事实
- 所有关键事实字段应逐步补齐 `source_chain`、`as_of`、`period_end_date`、`filing_or_release_date`
- `/stock/analyze` 的关键研究结论除模块级 trace 外，还应逐步补齐字段级 provenance；`item.meta.provenance` 用于承载 `summary.research_strategy.*` 的来源模块、字段路径、fallback 与 heuristic 标记
- fallback 需要区分：
  - 降级成功
  - 真实失败
  - `partial`
  - `not_supported`
- 不同 fallback 路径应支持分层 cache key，避免跨路径污染

## 工作流与质量约束

- 各复杂分析接口应逐步补齐 workflow contract，而不是只定义最终返回字段
- 盯盘接口优先服务 5-10 分钟轮询场景，服务端内部维护 symbol 级内存 baseline，重启后不恢复
- 定时同步任务通过统一 `sync-market-data` 命令执行，支持按市场、scope、symbol 和时间窗口补库
- 统一读写服务固定为：
  - `symbol_catalog_service`
  - `daily_data_read_service`
  - `daily_data_write_service`
  - `watch_polling_service`
- 公共 HTTP 接口默认先读 SQLite，若最新日线超过 7 个自然日则按需回退外部源并回写，不暴露强制 `refresh`
- 每日首次任意 HTTP 请求都要后台执行一次 symbols preflight；`cn/us` 分市场独立判断、独立封账，且不阻塞当前请求
- symbols preflight 覆盖 `/health` 与业务接口，但排除 `/docs`、`/redoc`、`/openapi.json`
- `cn_symbols` preflight 仅在 A 股开市日触发刷新；`us_symbols` preflight 仅在美股开市日触发刷新
- A 股列表与日线优先级默认是 `Tushare -> fallback`，URL 与 token 必须通过环境变量读取，不允许硬编码
- A 股盘中 realtime quote 优先级固定为 `Tushare -> Efinance -> Pytdx`；`Baostock` 不参与 realtime 主链路
- 美股 `/watch/poll` realtime quote 主源固定为 `Yfinance`
- A 股 `/watch/poll` 基本面固定为轻量模式：优先消费 realtime quote 与本地 canonical daily 事实，不再触发重型多源财务 fallback
- provider 不支持某项能力时，应视为 `not_supported`，不能计入失败、不能污染熔断状态
- `/watch/poll` 里凡是 `quote.mode = daily_fallback` 都必须视为非 realtime 降级结果，不能再把 A 股 fallback 伪装成完整 `ok`
- `POST /stock/analyze` 只允许输出客观、结构化、可追溯的研究能力，不输出主观 thesis、评级建议、目标价结论、morning note 或 investment idea 文案
- `POST /stock/analyze` 的公开“可信度”不再使用自由表述或主观打分；统一使用规则生成的 `evidence_strength`
- `/stock/analyze` 仅通过请求体 `mode` 控制模块集合：
  - `base` 面向决策信息全的默认消费场景
  - `full` 在 `base` 之上补充长尾原始块和扩展模块
- `/stock/analyze` 不再向公共调用方暴露自定义模块选择能力，不再为 DCF、Comps、LBO、Three-statement、Competitive、Earnings 等能力单独设计公共 HTTP 路由
- `/stock/analyze` 的来源链、限制说明、filter rule、fallback 说明等调试信息统一进入 `item.meta.modules.<module>.notes`，不在模块 body 内重复铺开
- 面向 Agent / skill 的 CLI 入口与 `/stock/analyze` 保持能力对齐，但 CLI 仍属于仓库内部脚本能力，不属于公共 HTTP API
- `scripts/poll_realtime_quotes.py` 是独立于 `/watch/poll` 的内部轻量行情 CLI：
  - 保持 `status / computed_at / source / request / summary / items` contract
  - 不复用 `/watch/poll` 的 `entity / facts / analysis / meta` contract
- `sync-market-data` 的目标执行链固定为：
  - 读取最新 `sync_runs`
  - 读取 live universe 与目标最新交易日
  - 先用 `cn_symbols` 覆盖摘要做粗筛
  - 再用 `cn_daily` 精确判定 symbol 缺口、历史缺口或 stale 日线
  - 刷新 `cn_symbols`
  - 补齐 `cn_daily`
  - 回写本次运行后的全局状态快照
- stale 判定使用 freshness grace，而不是强制每只股票都等于市场最新交易日；同一状态重复运行应直接 `skipped`
- stale / current 判定必须引入停牌豁免：若 `suspend_d` 能解释窗口内无新日线，则不应把该 symbol 计入普通 stale
- `sync_runs` 不只是运行日志，还必须表达：
  - 本次请求参数
  - 本次运行进度
  - 本次结束后整张市场表的全局状态
- workflow 至少覆盖：
  - 输入检查
  - 证据要求
  - 输出结构
  - 质量检查
  - 限制说明
- 输出中的关键结论应可追溯到事实、证据或模型方法
- stock analyze CLI 与公共 HTTP 入口必须保持能力同构，不输出自由文本总结、主观 thesis、评级建议或目标价结论
- realtime quote CLI 与 skill 侧历史 `poll_realtime_quotes.py` 保持轻量 contract 同构，且当前仅服务 CN 股票 / ETF 的 Tushare 日内行情查询
- 模拟盘自动交易 workflow 固定由确定性 worker 执行：
  - 定时轮询、行情读取、策略执行、风控、模拟盘下单、成交回写和对账均不经过 Agent 即时决策
  - Agent 只参与盘后复盘、回测解释和策略迭代建议，产物必须是结构化 `strategy_proposal`
  - `strategy_proposal` 通过 schema 校验、回测门槛和人工批准后，才能生成候选或生效策略版本
  - 第一阶段交易环境固定为 Futu `SIMULATE`，禁止实现真实交易、交易解锁、订阅推送或 OpenD 配置写入
  - 所有订单必须携带可复算的 idempotency key，重复轮询不得重复下单
  - 订单幂等和运行审计必须持久化到 SQLite trading ledger，不能依赖单进程内存态
  - 调度入口必须使用 SQLite 锁或等价互斥，防止并发 worker 在同一窗口重复通过预检
  - 内部 `trading_run_once.py` 默认使用 dry-run broker；真实 Futu `SIMULATE` broker adapter 必须另行接入并继续禁止 `unlock_trade`
  - 风控失败必须返回结构化拒绝原因，不允许用 Agent 文案替代机器判断

## 演进方向

- 继续向共享 `fundamental_context` 收敛
- 在共享 context 之上补齐 compact/detail snapshot 层
- 让 route 层和 analysis 层默认消费稳定 extractor，而不是直接消费整包 context
- 持续增强 evidence、quality check、source-chain、fallback 和 provenance 测试
