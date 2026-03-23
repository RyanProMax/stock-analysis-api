# 当前任务计划

更新时间：2026-03-23

## 当前目标

- 下线 `/ping`，统一收口到 `/health`
- 将 `/watch/poll` 的美股链路提升为正式 realtime 轮询能力
- 保持 A 股轻量基本面轮询与既有降级语义稳定

## 最近完成项

- 删除 `GET /ping`，收口 `GET /health` 为唯一健康检查接口，并将 `data.message` 固定为 `ok`
- 参考 DSA 为 `YfinanceDataSource` 新增美股 realtime quote，实现 `fast_info -> history(period=\"2d\")` 回退链路
- 收口 `/watch/poll` 的美股 realtime 语义：美股股票 realtime 命中时明确返回 `quote.mode = realtime`
- 修复美股日线 timezone-aware 日期与 naive `Timestamp` 比较导致的 `/watch/poll` 运行时 `500`
- 更新 README、`docs/api.md`、`docs/specs/watch-polling-api.md`，统一说明 `/health` 与美股 realtime 轮询能力
- 补充健康检查下线测试、美股 realtime source 测试与美股轮询行为测试
- 将 A 股 `/watch/poll` 改为轻量基本面模式；A 股轮询不再调用重型 `get_financial_data()` fallback 链路
- 修正 `DataManager.get_financial_data()` 的 provider 能力过滤，只让真正支持财务接口的 source 参与 fallback 与熔断
- 为 `AkShare`、`Tushare` 的 A 股财务失败路径移除 `traceback.print_exc()`，改为单行结构化 warning
- 下调 `Efinance` 盘中 realtime 的预期源端异常噪音，避免东方财富脏响应重复刷 warning
- 修复 `Pytdx` 多 host 连接失败路径，失败时显式断开 candidate socket，避免 `unclosed TrafficStatSocket`
- 已将健康检查统一收口到 `GET /health`
- 补充 provider 稳定性测试，覆盖能力过滤、A 股轻量轮询、`Pytdx` 清理和财务日志降噪
- 新增 `docs/api.md`，统一沉淀当前所有 HTTP 接口的用途、调用方式、入参、出参和字段含义
- 更新 `AGENTS.md` 文档索引，明确 `docs/api.md` 是 HTTP 接口设计说明的唯一文档
- 审计当前 `/watch/poll` A 股实时链路，确认此前真实可用源主要是 `Efinance / Pytdx`，`Tushare` 未实现 realtime quote
- 参考 DSA 迁入 `TushareDataSource.get_realtime_quote()`，改为先尝试 Pro `quotation`，失败后降级到旧版 `ts.get_realtime_quotes`
- 保持 A 股 realtime manager 优先级为 `Tushare -> Efinance -> Pytdx`，不新增独立 realtime manager
- 将 `/watch/poll` 的 `daily_fallback` 语义改为市场无关：A 股和美股只要走日线降级，都必须返回 `partial`
- 更新 `docs/specs/watch-polling-api.md` 与 `docs/architecture.md`，明确 A 股盘中验收必须检查 `quote.mode = realtime`
- 补充 Tushare realtime source 测试，以及 A 股 `daily_fallback` 语义单测
- 为本机开发环境新增 LaunchAgent 常驻方案，落地 `scripts/run_http_service.sh`、`scripts/restart_http_service.sh`、`scripts/status_http_service.sh`
- 已将 HTTP 服务注册为用户级 LaunchAgent，并保持后台运行
- 在 `README.md` 中补充 HTTP API 端点用途说明，同时保持 README 只承担使用说明职责
- 为 `cn_symbols` 新增 `daily_start_date`、`daily_end_date`，并在日线写入后自动回写覆盖摘要
- 为旧库新增覆盖摘要回填逻辑，避免 schema 升级后误判全量缺口
- 让 `replace_symbols` 保留已有覆盖摘要，避免主数据刷新清空本地覆盖信息
- 让 `sync-market-data` 先用 `cn_symbols` 覆盖摘要做粗筛，再进入 `cn_daily` 精确校验
- 为 stale / current 判定引入 `suspend_d` 停牌豁免，避免把停牌无新日线直接算作普通 stale
- 明确 `cn_daily.is_suspended` 只是停复牌事件标记，不表示完整停牌区间
- 将 `README.md` 压缩为使用说明，把仓表语义和停牌设计迁回 `AGENTS.md` / `docs/`
- 完成盯盘 API 方案设计，确定对外只保留 `POST /watch/poll`
- 确认服务端内部按 `symbol` 维护 baseline，不使用 cursor / monitor_id
- 确认首版范围覆盖 A 股和美股，US 链路允许降级为 latest available snapshot
- 实现 `/watch/poll` route、request schema、watch polling service 和 symbol 级 baseline cache
- 输出 compact snapshot、delta、alerts 的统一 contract
- 删除旧 specs，新增唯一规格文档 `docs/specs/watch-polling-api.md`
- 补齐 watch contract 测试、HTTP route 测试和轮询逻辑单测
- 明确 `quote.mode` 与 `meta.degradation` 语义，区分 realtime / daily_fallback / unavailable
- 将美股日线降级统一标记为 `partial`，避免将 fallback 结果误判为 realtime `ok`
- 补充 `source_chain`、降级信息和 watch contract 语义测试
- 扩展美股 `next_earnings_date` 提取路径，支持 `info`、`calendar` 和 `earnings_dates` 回填
- 补充财报日期提取与 `earnings_watch` 回填单测
- 新增本地 SQLite 行情仓，落地 symbol / daily 分表与 `sync_runs` 任务记录
- 新增统一行情仓同步服务和命令入口，支持按市场、scope 与时间窗口补库
- 让 `/watch/poll` 与 `/stock/analyze` 的 A 股历史日线优先读取 SQLite 仓，缺失时回退外部源并回写
- 补充 SQLite 仓储、读路径优先级与同步任务测试
- 下线 `CacheUtil` 文件缓存，移除 `cache_version`、报告缓存与 watch baseline 文件落盘
- 移除 `/watch/poll` 与 `/stock/list` 的公共 `refresh` 参数
- 将 `/stock/list` 与 `/stock/search` 改为默认从 SQLite `symbols` 读取，缺失时冷启动拉源并回写
- 将 watch baseline 改为纯内存态，保留 symbol 级 TTL 语义
- 将 Tushare 调整为主数据源，token / URL 统一从环境变量读取
- 将本地行情仓重构为 `cn_symbols`、`cn_daily`、`us_symbols`、`us_daily` 与 `sync_runs`
- 新增 `extra` JSON 扩展字段，主列按 tushare 核心口径保存稳定事实字段
- 删除 `sync-a-share-daily` / `backfill-a-share-daily`，统一为 `sync-market-data`
- 将 `/stock/analyze` 与 `/watch/poll` 改为 7 天 freshness 检查后自动补数并回写
- 将 Docker workflow 改为仅在 `main` push 且最新 commit message 包含 `[pack]` 时构建
- 完成 `300827` 近 30 天真实同步验收，确认 `CN_Tushare` 写库与 SQLite 命中读取正常
- 新增 `src/repositories/market_data_repository.py` 和 `src/services/` 分层
- 将旧 `storage/`、`core/market_data_*`、`core/watch_polling` 改为兼容转发层
- 为统一同步命令新增精确 `start_date` 能力
- 将同步进度改为按股票数实时统计，并在 CLI 输出 `processed/total` 进度
- 完成 A 股 `market=cn`、`scope=all`、`start_date=2026-01-01` 的全市场补库
- 修复 Tushare 北交所 `ts_code` 映射，将 `920xxx / 8xxx / 4xxx` 正确映射到 `.BJ`
- 重试北交所缺失 symbol 后补齐 `cn_daily` 缺口，当前 `5000/5000` 个 `cn_symbols` 均已有日线
- 实时核实 Tushare `stock_basic(list_status='L')` 当前返回 `5000` 只，`P/D` 当前都为 `0`
- 实时核实当前本地 `cn_daily` 最新交易日为 `2026-03-20`，与截至 `2026-03-22` 的最新开市日一致
- 明确本轮重构重点从“补更多 symbol”转为“补状态模型与事实字段模型”
- 更新 `README.md`、`AGENTS.md`、`docs/architecture.md`、`docs/specs/local-daily-warehouse.md`，先锁定新设计再改代码
- 为 `cn_symbols` 增加 `cnspell` 主列，并将 `act_name`、`act_ent_type` 归入 `extra`
- 为 `cn_daily` 提升 `turnover_rate`、`volume_ratio`、`pe/pb/ps`、`circ_mv/total_mv` 等 Tushare `daily_basic` 标准列
- 升级 `sync_runs` schema，增加请求参数、运行进度和全局状态快照字段
- 让 `sync-market-data` 先查状态再决策，并支持同一状态重复执行直接 `skipped`
- 新增 `daily_basic` 批量回填路径，完成现有 `cn_daily` 旧行回填，当前 `total_mv` 缺口为 `0`
- 用真实 Tushare 数据完成 A 股仓回填验收；最新 `sync_runs.id=14` 已进入 `skipped`

## 当前状态

- HTTP 服务仍是唯一对外协议
- `facts / analysis / meta` 分层仍是当前输出 contract 基线
- 当前唯一对外盯盘能力应收敛为单一轮询接口
- 文件缓存已下线，持久层收敛为 SQLite + 进程内内存态
- Tushare 现为股票列表与 A 股日线的主优先级数据源
- Tushare 现已成为 A 股 realtime quote 的主优先级数据源；若 realtime 不可用，再依次降级到 `Efinance`、`Pytdx`
- `Yfinance` 当前已成为美股 `/watch/poll` realtime quote 主源；失败时仍按 `daily_fallback / unavailable` 处理
- A 股 `/watch/poll` 当前只使用轻量基本面字段，不再为轮询触发重型多源财务抓取
- `get_financial_data()` 当前会先过滤不支持财务能力的 provider，避免误计失败和污染熔断状态
- `/health` 当前是唯一健康检查接口，返回 `message=ok`、`status=healthy`
- `repositories/` 和 `services/` 已成为正式业务层，`storage/` 只保留兼容导入
- 当前 A 股 listed universe 以 Tushare `list_status='L'` 为准，实时计数为 `5000`
- `cn_symbols` 当前为 `5000`
- `cn_daily` 当前为 `244475` 行，覆盖 `5000/5000` 个 symbol
- `cn_daily` 当前 `total_mv` 缺口为 `0`
- `cn_symbols.daily_start_date` / `daily_end_date` 已成为本地覆盖摘要字段
- `sync-market-data` 当前会先查 `sync_runs`、再做覆盖粗筛、再做精确校验
- `cn_daily.is_suspended` 当前仍是弱标记模型；`suspend_d` 不落表、不生成停牌虚拟 row
- 最新 `sync_runs` 已可表达请求参数、进度和全局状态快照
- 首版已完成的实现包括：
  - compact snapshot
  - delta / alerts
  - symbol 级 baseline memory state
  - A 股实时优先、美股 realtime 已正式接入 `Yfinance`
  - quote 降级模式显式暴露
  - 任一市场的 daily fallback 都不再伪装为 realtime `ok`
  - `cn_* / us_*` 拆分的 SQLite symbol / daily 仓
  - `extra` JSON 扩展字段与 tushare 核心主列
  - 统一 `sync-market-data` 命令入口
  - A 股 `2026-01-01` 起全市场补库已完成
  - `/stock/analyze` 不再缓存分析报告
  - `/stock/list` 与 `/stock/search` 默认消费 SQLite symbol 仓
  - `/stock/analyze` 与 `/watch/poll` 默认执行 freshness 检查后按需补数
  - 北交所 `cn_daily` 现已可通过 `CN_Tushare` 正常补库
  - `sync-market-data` 当前会先查最新状态，再决定补库或 `skipped`
  - `daily_basic` 标准字段已成为 `cn_daily` 主列
  - 历史 `running` 脏记录已统一改为 `cancelled`

## 下一步计划

### P0

- 重启常驻服务并验证 `/health` 已成为唯一健康检查入口
- 抽样验证 `NVDA / AAPL` 的 `/watch/poll` 返回 `quote.mode = realtime`
- 继续观察 A 股轮询日志，确认此前降噪改动未回退

### P1

- 评估是否需要引入更稳定的 US realtime quote 链路
- 继续压缩轮询 payload，控制 token 与重复字段

## 已知风险与阻塞

- A 股长历史回填和扩展字段完整性高度依赖 `Tushare` 可用性，fallback 源可能只能提供较短窗口
- 美股 realtime 当前仍为单源 `Yfinance`，稳定性与覆盖度低于 A 股链路；源端失败时仍需接受 `daily_fallback` / `partial`
- symbol 级 baseline 为进程内全局共享，不区分调用方，且重启后丢失，会影响多 Agent 并发观测语义
- SQLite 方案当前只适合单机、单写多读场景，不适合未来多实例共享写入
- 东方财富相关链路仍可能因环境或源端不稳定返回空响应 / 脏响应；本轮只做 graceful degradation，不修改全局代理策略
- 旧兼容导入层仍然存在，后续若要继续收敛，需要逐步清理 `src/core/` / `src/storage/` 的转发用法
- 当前未持久化完整停牌区间；`is_suspended` 只能表示事件命中，不能单独解释中间无 row 的整段停牌
- 若后续要让停牌语义可追溯到区间级事实，需要新增独立停牌持久化方案，而不是继续扩展 `cn_daily`
