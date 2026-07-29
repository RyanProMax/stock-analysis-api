---
name: stock-analysis-skill
description: Use when users ask in Chinese or natural language for stock objective analysis, realtime quotes, research-report summaries, HK IPO pool screening, HK grey-market/OTC watch, raw Tushare data, or read-only Futu/OpenD market/account queries.
metadata:
  version: 2.3.0
---

# stock-analysis-skill

`stock-analysis-skill` 是股票任务的意图路由与输出约束，不是行情、分析或交易实现源。当前只保留五类入口：

本 skill 与实现仓库同版本维护在
`stock-analysis-api/.agents/skills/stock-analysis/`；运行时优先自动识别当前
monorepo 根目录，不再要求旁边存在独立 `stock-analysis-skill` 仓库。

- `CLI 使用技能`：标准化 A 股客观分析、单票研报摘要、A 股 / ETF 低 token
  实时行情，以及定时内容任务使用的无状态日报行情数据包。
- `Futu/OpenD 使用技能`：统一通过 `stock-analysis-api` 内部 CLI / provider 使用 Futu/OpenD；API 已支持 snapshot、K 线、盘口、逐笔、分时、期权链、港股 IPO 暗盘 watch、账户、资金、持仓、订单、成交和流水等只读查询；尚未迁入 API 的能力必须明确标记为未支持，不再路由到外部 Futu skill。
- `模拟盘 dry-run 使用技能`：只在用户明确要求模拟盘自动化、回放或链路验证时调用 `stock-analysis-api/scripts/trading_run_once.py`；默认 dry-run broker；定时轮询调用 `stock-analysis-api/scripts/trading_scheduler_tick.py`；盘后总结和策略候选评审调用 `trading_daily_summary.py` / `trading_strategy_review.py`；历史 K 线回测调用 `trading_strategy_backtest.py`；连接 Futu 模拟盘必须显式使用 `--broker futu-simulate`。
- `Tushare 使用技能`：用户明确要求的原始 Tushare 接口、字段、时间窗或接口查阅。
- `Slash Commands`：`/research` 单票深度研报、`/hkipo` 港股 IPO 池研究工作流、`/otc` 港股暗盘 / OTC 单次查询或定时间隔轮询；`/cnipo` 目前占位。

## 全局只读护栏

运行时使用本 skill 时默认只允许查询和结果展示；不得产生任何账户、订单、订阅、配置、自选股、提醒或本地文件状态变更。例外仅限用户明确要求的 API 侧调度 / 回放状态：模拟盘 dry-run 可写 API 侧 SQLite dry-run ledger；只读定时查询可写 API 侧 scheduler tick 节流状态，但不得写入券商账户、订单、订阅或 watchlist。

- 允许：行情、K 线、盘口、逐笔、分时、IPO、港股暗盘 watch、期权链、账户、资金、持仓、订单、成交、流水等只读查询。
- 禁止：下单、改单、撤单、交易解锁、订阅推送、创建 / 修改价格提醒、写入 watchlist、修改配置、导出文件或任何其他写入动作。
- 模拟盘 dry-run 只允许使用 API 默认 dry-run broker；不得把它替换为真实交易、交易解锁、订阅或任何 OpenD 写入能力。
- 用户请求写入 / 编辑 / 下单 / 订阅 / 解锁时，必须拒绝执行；不得用模拟账户、已登录 OpenD 或用户二次确认作为绕过理由。
- 仓库维护例外：只有在用户明确要求维护本仓库文档 / 脚本时，才允许运行会更新本仓库文件的维护命令，例如 `scripts/tushare_toolkit.py generate-docs`。
- 不输出买卖建议、本系统目标价、主观 conviction、`recommendation`、`confidence`、`price_target`、`thesis`；机构目标价只能作为带来源、日期和币种的外部观点引用，不得改写成本系统建议。
- 账户、资金、持仓等敏感信息按最小必要原则展示。

## 路由优先级

先判断用户意图，再选择唯一主路由；不要为同一个问题同时散开到多个数据源。

| 用户意图 | 默认路由 | 关键边界 |
| --- | --- | --- |
| `/research <symbol>` | `Slash Commands` | 单票深度研报，A 股 / 美股优先复用运行时解析出的 `stock_analyze.py --mode full` 绝对命令；显式港股先做 OpenD 预检，失败时先询问是否继续 |
| `/hkipo` | `Slash Commands` | 触发 Cli Claw 内置 `hkipo` workflow，自动发现港股 IPO 池并按 `references/hkipo.md` 评分 |
| `/otc <HK symbol> [--loop=300s]` | `Slash Commands` | 单次查询先映射 API `grey_market_watch.py --once`；轮询映射 API `--interval-seconds`；非暗盘时段直接结束提示 |
| `/cnipo` | `Slash Commands` | 当前只返回占位说明 |
| 单票客观分析、研报式摘要、“最近怎么样” | `CLI 使用技能` | 默认走 `stock_analyze.py`，不直接查原始 `report_rc` |
| A 股股票 / ETF 低 token 实时行情 | `CLI 使用技能` | 默认走 `poll_realtime_quotes.py` |
| 日报 / 定时内容任务所需中美指数与美债收盘数据包 | `CLI 使用技能` | 走 `market_data_query.py daily-pack`；单次执行、无需启动 HTTP、固定 `persistence=none` |
| 港 / 美 / 多市场行情、盘口、逐笔、分时、K 线、期权链、账户、资金、持仓、订单、成交、流水等只读查询 | `Futu/OpenD 使用技能` | 仅限 API 已迁移能力；未迁移能力明确返回未支持 |
| 港股 IPO 暗盘 / OTC 报价监听、定时查询 | `Futu/OpenD 使用技能` | 走 API `grey_market_watch.py`；Futu 为正式 provider，Tiger / Fosun 等未接入正式授权 API 时返回 unsupported |
| 模拟盘自动化、策略回放、dry-run 链路验证 | `模拟盘 dry-run 使用技能` | 单轮执行走 API `trading_run_once.py`；定时 tick 走 `trading_scheduler_tick.py`；默认 dry-run broker、SQLite ledger 和调度锁；Futu 模拟盘必须显式 `--broker futu-simulate`；禁止真实交易 |
| 模拟盘盘后总结、策略评审、自我迭代方向 | `模拟盘 dry-run 使用技能` | 只读 API ledger，走 `trading_daily_summary.py` / `trading_strategy_review.py`；proposal 只作为候选，必须人工批准，不自动改策略 |
| 模拟盘历史 K 线回测 | `模拟盘 dry-run 使用技能` | 走 API `trading_strategy_backtest.py`；只读历史 K 线或注入样本，不读写 ledger，不触发 broker |
| 原始 Tushare 数据、接口清单、自定义字段或时间窗 | `Tushare 使用技能` | 只有用户明确要求原始接口时才使用 |

明确例外：

- “查 300627 的研报”默认走 `stock_analyze.py`；只有“原始券商研报记录 / 原始 report_rc 数据”才走 Tushare。
- A 股 watchlist 只需现价、涨跌幅、全量快照或简单异动提醒时，默认仍走 `poll_realtime_quotes.py`。
- 混合市场 watchlist、带 `HK.` / `US.` 等前缀，或需要盘口、逐笔、分时、K 线、期权链、账户只读联动时，走 `Futu/OpenD 使用技能`。

## CLI 使用技能

适用于标准化结果、固定模板和稳定 JSON contract。执行前确认：

1. API 根目录可从当前 `.agents/skills/stock-analysis/` 安装位置自动识别；
   `STOCK_ANALYSIS_API_ROOT` 仅作为显式覆盖。
2. 固定 `uv` 可用：优先 `STOCK_ANALYSIS_UV`，其次 `UV_BIN` / `UV` / PATH / `$HOME/.local/bin/uv` / `$HOME/.cargo/bin/uv`；生成给 agent 的命令必须使用解析后的绝对 `uv` 路径。
3. API 仓库存在 `scripts/poll_realtime_quotes.py`、`scripts/stock_analyze.py`、
   `scripts/market_data_query.py`、`scripts/futu_market_data.py`、
   `scripts/grey_market_watch.py`、`scripts/trading_run_once.py`、
   `scripts/trading_scheduler_tick.py`、`scripts/trading_daily_summary.py`、
   `scripts/trading_strategy_review.py` 与 `scripts/trading_strategy_backtest.py`。
4. A 股数据所需的 `TUSHARE_TOKEN` / `TUSHARE_HTTP_URL` 可被 API 仓库读取。

标准命令：

```bash
cd "$STOCK_ANALYSIS_API_ROOT" && "$STOCK_ANALYSIS_UV" run python scripts/poll_realtime_quotes.py --symbols 600000,510300 --pretty
cd "$STOCK_ANALYSIS_API_ROOT" && "$STOCK_ANALYSIS_UV" run python scripts/stock_analyze.py --market cn --symbols 300827 --mode base --pretty
cd "$STOCK_ANALYSIS_API_ROOT" && "$STOCK_ANALYSIS_UV" run python scripts/market_data_query.py daily-pack --cutoff-at 2026-07-29T13:00:00Z --persistence none
cd "$STOCK_ANALYSIS_API_ROOT" && "$STOCK_ANALYSIS_UV" run python scripts/futu_market_data.py ipo-list --market HK --json
cd "$STOCK_ANALYSIS_API_ROOT" && "$STOCK_ANALYSIS_UV" run python scripts/futu_market_data.py order-book --code HK.00700 --num 10 --json
cd "$STOCK_ANALYSIS_API_ROOT" && "$STOCK_ANALYSIS_UV" run python scripts/futu_market_data.py option-chain --code US.AAPL --start 2026-05-15 --end 2026-06-19 --option-type CALL --json
cd "$STOCK_ANALYSIS_API_ROOT" && "$STOCK_ANALYSIS_UV" run python scripts/futu_market_data.py positions --market HK --code HK.00700 --json
cd "$STOCK_ANALYSIS_API_ROOT" && "$STOCK_ANALYSIS_UV" run python scripts/grey_market_watch.py --once --code HK.02618 --name 剂泰医药 --issue-price 10 --json
cd "$STOCK_ANALYSIS_API_ROOT" && "$STOCK_ANALYSIS_UV" run python scripts/grey_market_watch.py --code HK.02618 --name 剂泰医药 --issue-price 10 --interval-seconds 300 --json
cd "$STOCK_ANALYSIS_API_ROOT" && "$STOCK_ANALYSIS_UV" run python scripts/trading_run_once.py --codes HK.00700 --buy-above HK.00700=0 --quantity 1 --max-order-notional 1000000
cd "$STOCK_ANALYSIS_API_ROOT" && "$STOCK_ANALYSIS_UV" run python scripts/trading_scheduler_tick.py --codes HK.00700 --buy-above HK.00700=0 --quantity 1 --max-order-notional 1000000
cd "$STOCK_ANALYSIS_API_ROOT" && "$STOCK_ANALYSIS_UV" run python scripts/trading_daily_summary.py --date 2026-05-07 --pretty
cd "$STOCK_ANALYSIS_API_ROOT" && "$STOCK_ANALYSIS_UV" run python scripts/trading_strategy_review.py --date 2026-05-07 --min-runs 3 --pretty
cd "$STOCK_ANALYSIS_API_ROOT" && "$STOCK_ANALYSIS_UV" run python scripts/trading_strategy_backtest.py --codes HK.00700 --buy-above HK.00700=100 --start 2026-05-01 --end 2026-05-07 --pretty
```

输出规则统一见 `references/cli.md`。默认不要原样转贴 raw JSON；除非用户明确要求调试或原始输出，优先按固定模板汇总。`change_pct`、`turnover_rate`、`amplitude` 等 ratio 字段面向用户展示为百分比。

`daily-pack` 是机器调用例外：定时任务应直接消费严格 JSON contract，不让 Agent
重新选择 provider。它只读取外部行情，不启动 FastAPI，不读写 API SQLite、
scheduler state、watchlist 或券商状态；返回 `partial/failed` 时调用方必须显式失败
或降级，不得补编缺失行情。

## Futu/OpenD 使用技能

适用于 `HK.` / `US.` 等多市场代码、深度行情、港股 IPO 暗盘 / OTC 定时查询、期权链、窝轮 / 牛熊证、期货资料、资金流、板块、条件选股、账户、资金、持仓、订单、成交和流水等只读查询。

进入该路由前确认：

1. `/hkipo`、`/research` 港股预检 / snapshot / K 线和 HK IPO 回测优先使用 `stock-analysis-api/scripts/futu_market_data.py`。
2. 盘口、逐笔、分时、期权链、账户、资金、持仓、订单、成交和流水查询已迁移到 `stock-analysis-api/scripts/futu_market_data.py`；只能调用这些只读子命令，不得绕回外部 Futu skill。
3. 港股 IPO 暗盘 / OTC 报价监听走 `stock-analysis-api/scripts/grey_market_watch.py`；`/otc 07666.HK` 映射 `--once` 单次查询，`/otc 07666.HK --loop=300s` 映射 `--interval-seconds 300` 轮询 tick；非暗盘时间直接结束并提示。Futu 为正式 provider，Tiger / Fosun 等未接入正式授权 API 时只能返回 `unsupported`，不得网页抓取伪造跨券商报价。
4. 窝轮 / 牛熊证、资金流、资金分布、经纪队列、板块与成分股、条件选股、期货资料等尚未迁移能力不得改走其他脚本；必须明确说明“尚未迁入 stock-analysis-api”。
5. OpenD 正在运行，默认地址 `127.0.0.1:11111`。
6. Python SDK `futu-api` 版本满足 API 仓库要求。
7. 请求不涉及交易、订阅、提醒、自选股、配置或券商侧写入；只读定时查询允许 API 侧记录 scheduler tick 节流状态。

OpenD 未安装、未启动或 SDK 版本不满足时，说明 API Futu CLI / OpenD 环境不可用，并按 `references/futu.md` 的降级和拒绝模板处理。

## 模拟盘 dry-run 使用技能

适用于用户明确要求 Agent 定时轮询、模拟盘策略执行、回放验证或 dry-run 自动化链路检查。

- 只能调用 `stock-analysis-api/scripts/trading_run_once.py`。
- cron / launchd / Agent 高频轮询必须调用 `stock-analysis-api/scripts/trading_scheduler_tick.py`，由它判断 active window、执行间隔和 state key。
- 盘后总结必须调用 `stock-analysis-api/scripts/trading_daily_summary.py`，只读 API 侧 SQLite ledger。
- 盘后总结默认只消费 summary-only 输出；只有排障时才允许显式加 `--include-details` 读取 ledger 明细。
- 策略候选评审必须调用 `stock-analysis-api/scripts/trading_strategy_review.py`；输出的 `strategy_proposal` 只能作为候选和审计底稿，不自动应用到运行时策略。
- 历史 K 线回测必须调用 `stock-analysis-api/scripts/trading_strategy_backtest.py`；它只读历史 K 线或注入样本，不读写 ledger，不触发 broker。
- 默认 broker 为 dry-run，不连接真实交易环境，不调用 `unlock_trade`。
- 只有用户明确要求连接 Futu 模拟盘执行时，才允许传 `--broker futu-simulate`；该路径固定 Futu `TrdEnv.SIMULATE`，不得调用 `unlock_trade`，也不得和 `--snapshots-json` 混用。
- 默认写入 API 侧 SQLite trading ledger，并使用 `trading_run_once` 调度锁；拿不到锁时返回 `status=skipped / reason=lock_unavailable`。
- 输出必须是严格 JSON；`NaN` / `Infinity` 等非标准值由 API CLI 归一化为 `null`。
- 该能力只能作为模拟执行和审计底稿，不输出买卖建议、系统目标价或真实下单指令。

## Tushare 使用技能

仅在用户明确要求原始 Tushare 数据或接口能力时使用，例如：

- 点名 `report_rc`、`research_report`、`news` 等接口。
- 要求自定义字段、自定义时间窗或接口清单。
- CLI 无法覆盖当前需求，且需要继续深挖原始数据。

原则：

- 单票分析、单票研报摘要、A 股标准化实时行情，默认回到 `CLI 使用技能`。
- 数据权限不够或接口返回为空时，直接说明限制，不伪造。
- 面向用户的查询默认只在回复中展示结果，不写文件、不导出。
- `scripts/tushare_toolkit.py generate-docs` 只用于仓库维护任务；接口总表见 `references/api_reference.md`。

## Slash Commands

- `/research`：对一只 A 股 / 美股 / 港股生成深度研报 prompt。支持股票名 / 公司名输入；executor 不做本地缓存或硬编码匹配。短裸美股 ticker（如 `AAPL`）可直接走美股，较长英文公司名或非标准裸输入（如 `MINIMAX`）必须进入待解析工作流，不能因为全大写就强行标记为美股。A 股 / 美股优先复用 `stock-analysis-api` 的 `stock_analyze.py --mode full`；executor 会按 `STOCK_ANALYSIS_API_ROOT`、当前 monorepo 根目录、兼容 sibling `stock-analysis-api` 的顺序动态生成可复制的绝对 `cd ... && /absolute/uv run python ...` 命令。找不到 API 仓库时必须显式标记预检失败；上游返回 `identity_conflict` / `identity_not_found`，或返回 `data.items[0].status=failed/not_supported` 且 `error/info/meta` 指向身份、行情或市场不支持问题时，必须先解析这些字段并澄清或改道，不能沿用错误市场标题。显式港股在进入 agent 前必须调用 `stock-analysis-api/scripts/futu_market_data.py global-state --json` 做 OpenD 只读预检；预检失败只返回确认提示，用户用 `--continue-without-opend` 明确确认后才允许按 HKEX / 公司公告 / AKShare / yfinance 降级继续。待解析输入若唯一核验为港股，也必须先确认 OpenD 可调用；不可调用时先询问用户，不得自行降级。输出模板、飞书短版、最终回复清洗、`module_status` / `source_freshness` / `data_gaps` 可信度层、行业整体趋势、市场热度、同类公司平均 PE、权威机构研报汇总、风险与反证、历史验证、Sources 和禁止事项见 `references/research.md`。
- `/hkipo`：executor 不再生成长 `assistant_prompt`；它只返回 `workflowId=hkipo`、`prompt=港股 IPO 打新分析` 和结构化 input。默认自动发现当前仍可认购的港股 IPO 池，并按评分卡输出简明优先级报告；`/hkipo --all` 会把 `includeClosed=true` 传给 workflow，才纳入已截止认购但未上市标的。
- `/cnipo`：预留 A 股 IPO 指令位，当前只返回占位说明。

`/research` 飞书默认短版采用重点版结构：先回答财务结构是否健康、估值是否合理、相对行业高估还是低估、当下情绪热度、未来叙事与增长点、权威机构评级/观点、机构目标价、共识与分歧，再给风险、数据可信度、降级说明和 Sources。

`/hkipo` 要求：

- 读取 `references/hkipo.md`，使用 0-100 首日赔率评分卡。
- 默认过滤 Futu/OpenD 返回的 `is_subscribe_status=false` 已截止新股；只有用户显式传入 `--all` 时，才输出已截止认购但未上市标的。
- 必须按当前日期重新获取最新数据，不允许把旧日期的孖展、公开认购、暗盘或中签率当作当前数据；若只能找到旧数据，必须标注来源日期并按“过期/仅供趋势参考”处理，不得用于当前热度主评分。
- 当前 IPO 池发现、招股状态、上市日、招股截止日、发售价、一手股数和入场费优先由 Cli Claw workflow 的 `stock.hkipo.fetch_pool` local task 调用 `stock-analysis-api/scripts/futu_market_data.py ipo-list --market HK --json`；Futu/OpenD 不可用时 pool discovery 明确失败，不用网页猜 IPO 池。Futu 字段缺失或不暴露 App 热度时，workflow 的 `stock.hkipo.scan_heat` local task 调用 `stock-analysis-api/scripts/hkipo_heat_scan.py` 补齐二级热度并标注来源。
- 事实层中的招股书、全球发售、配发结果和上市文件优先依赖 HKEX / 公司公告等一手来源；财经站只补充 Futu/OpenD 与一手来源未提供的孖展/认购热度、中签率、一手中签率、灰市、首日涨幅等二级数据。
- 开放认购中的 IPO 热度必须通过当日硬门槛：每只池内 IPO 进入评分前，必须按代码、中文名和英文名自动重试检索，至少检索 3 类权威来源，包括券商新股中心 / 券商孖展表、财经门户新股频道、主流行情 App 新股页或 HKEX / 公司公告时间表（例如富途牛牛、辉立 POEMS、华盛通、老虎、AAStocks、ETNet、新浪港股 / 智通、格隆汇）。拿不到当日热度时，热度字段写“热度未达当日核验门槛”，不得把前一日或更旧孖展倍率用于主评分。
- 热度字段必须做多权威机构聚合：Futu CLI 不暴露 App 新股热度时，不得视为 Futu 热度缺失并停止；必须继续查 Futu/牛牛新股页、TradeGo / 活报告、多券商新股孖展统计、AAStocks、ETNet、智通 / 新浪、格隆汇，以及华盛、老虎、辉立、耀才、致富、KGI 等券商新股中心 / 孖展表。优先取同日多券商汇总 / 全市场聚合的最新值；不得把单一券商孖展下限当作全市场主热度。
- 热度字段必须按固定顺序核验：Futu/OpenD 当前字段和 Futu App / 牛牛热度 → 同日多券商汇总 / 全市场聚合 → 同一 IPO 当日券商新股中心 / 孖展表 → 当日财经门户新股频道的公开认购倍数 / 一手中签率 → 暗盘。所有孖展、公开认购和暗盘数值都要标注来源更新时间；来源冲突时使用更新时间最新且不晚于报告日的数据，旧值或单一券商下限只能作趋势参考。
- 必须检查绿鞋 / 超额配股权、稳定价格操作人、基石质量与占比、保荐人、回拨和公众货比例。
- 每个个股标题末尾写申购截止日和开奖/配发结果日，格式为 `M/D截止 | M/D开奖`；不要写建议性措辞、跟踪标签或“优先级”文字。
- 默认输出极简报告正文：普通加粗标题、结论最多 3 条、窄字段块列表、短链接 Sources；Futu 当前字段、外部补充热度、回测映射、发行结构、基本面/估值和风险整合进每只 IPO 的短字段。不要使用 `#` / `##` Markdown 大标题或宽 Markdown 表格。正文不要插入空白空行；“💡 关键结论”“📌 优先级”“🔗 来源”、bullet、个股标题和 `📍 阶段`、`💰 热度`、`🛡 结构`、`📈 回测`、`⚠️ 风险` 等个股小点都用单换行连续排列。用少量固定 emoji 强化重点：🟢/🟡/⚪ 排序，💰热度，🛡结构，📈回测，⚠️风险，🔗来源。
- 需要校准权重时运行：`python3 scripts/hkipo_backtest.py --limit 100 --source aastocks --enrichment-source xinguyufu --debut-price-source futu-kline --api-root "$STOCK_ANALYSIS_API_ROOT" --uv "$STOCK_ANALYSIS_UV" --format markdown`；OpenD 或 API Futu CLI 不可用时降级为 `python3 scripts/hkipo_backtest.py --limit 100 --source aastocks --enrichment-source xinguyufu --debut-price-source listed-table --format markdown`。重点看绿鞋/基石/暗盘覆盖、评分分桶、评分排序相关性、Top/Bottom 评分分位首日涨幅差和失配样本。

## 输出要求

- 结论先行，只输出影响用户决策、验收或下一步行动的信息。
- 面向用户展示时间默认使用北京时间（Asia/Shanghai, UTC+8）。
- 明确标注数据源、请求标的、成功 / 失败 / 降级状态。
- 源端不可用、权限不足或结果缺失时，说明限制，不补编。
- 财务与账户相关结果只做事实汇总和风险提示，不替代投资顾问。

## References

- CLI 使用说明：`references/cli.md`
- 单票深度研报：`references/research.md`
- 港股 IPO 评分与回测：`references/hkipo.md`
- Tushare 接口总表：`references/api_reference.md`
- Futu/OpenD 路由与输出 Contract：`references/futu.md`
- Futu/OpenD 能力：`/hkipo` / `/research` 已迁移到 `stock-analysis-api/scripts/futu_market_data.py`；盘口、逐笔、分时、期权链、账户、资金、持仓、订单、成交和流水等只读查询也已迁移到同一 API CLI；港股 IPO 暗盘 watch 走 `stock-analysis-api/scripts/grey_market_watch.py`；其他尚未迁移能力等待 API provider 扩展，不再从本 skill 路由到外部 Futu skill
- Tushare 官方文档：<https://tushare.pro/document/1?doc_id=290>
