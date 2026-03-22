# 当前任务计划

更新时间：2026-03-22

## 当前目标

- 完成 `CacheUtil` 下线与 SQLite 全迁移
- 让 `/watch/poll`、`/stock/analyze`、`/stock/list`、`/stock/search` 统一以 SQLite + 内存态运作
- 收紧存储边界，确保 SQLite 只保留必要持久数据
- 保持任务、架构和规格三层文档结构稳定

## 最近完成项

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
- 新增本地 SQLite 行情仓，落地 `symbols`、`daily_bars`、`sync_runs` 三张表
- 新增 A 股日线仓同步服务和独立命令入口，支持 recent refresh / history backfill
- 让 `/watch/poll` 与 `/stock/analyze` 的 A 股历史日线优先读取 SQLite 仓，缺失时回退外部源并回写
- 补充 SQLite 仓储、读路径优先级与同步任务测试
- 下线 `CacheUtil` 文件缓存，移除 `cache_version`、报告缓存与 watch baseline 文件落盘
- 移除 `/watch/poll` 与 `/stock/list` 的公共 `refresh` 参数
- 将 `/stock/list` 与 `/stock/search` 改为默认从 SQLite `symbols` 读取，缺失时冷启动拉源并回写
- 将 watch baseline 改为纯内存态，保留 symbol 级 TTL 语义

## 当前状态

- HTTP 服务仍是唯一对外协议
- `facts / analysis / meta` 分层仍是当前输出 contract 基线
- 当前唯一对外盯盘能力应收敛为单一轮询接口
- 文件缓存已下线，持久层收敛为 SQLite + 进程内内存态
- 首版已完成的实现包括：
  - compact snapshot
  - delta / alerts
  - symbol 级 baseline memory state
  - A 股实时优先、美股降级可用
  - quote 降级模式显式暴露
  - US daily fallback 不再伪装为 realtime `ok`
  - A 股本地 canonical 日线仓
  - A 股日线 recent refresh / history backfill 命令入口
  - `/stock/analyze` 不再缓存分析报告
  - `/stock/list` 与 `/stock/search` 默认消费 SQLite symbol 仓

## 下一步计划

### P0

- 验证 A 股大规模回填在真实数据源条件下的稳定性与耗时
- 将更多依赖历史日线的分析路径切到 SQLite 仓
- 细化 alert 阈值和 evidence 说明，减少误报

### P1

- 继续压缩轮询 payload，控制 token 与重复字段
- 评估是否需要引入更稳定的 US realtime quote 链路
- 评估是否需要补充 SQLite 只读诊断接口或运维脚本

## 已知风险与阻塞

- A 股长历史回填实际高度依赖 `Tushare` 可用性，fallback 源可能只能提供较短窗口
- 美股缺少与 A 股同等级的统一 realtime quote，首版需要接受 partial 降级
- symbol 级 baseline 为进程内全局共享，不区分调用方，且重启后丢失，会影响多 Agent 并发观测语义
- SQLite 方案当前只适合单机、单写多读场景，不适合未来多实例共享写入
