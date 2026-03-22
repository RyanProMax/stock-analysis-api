# 本地 SQLite 日线仓规格

更新时间：2026-03-22

## 目标

- 为 A 股提供单机本地 SQLite canonical 日线仓
- 支持按天同步 symbol 元数据、日线数据和同步任务记录
- 让 `/watch/poll` 与 `/stock/analyze` 优先读取本地仓中的 A 股历史日线

## 数据模型

- `symbols`
  - `symbol`
  - `ts_code`
  - `name`
  - `market`
  - `list_date`
  - `updated_at`
- `daily_bars`
  - 主键：`(symbol, trade_date)`
  - `open`
  - `high`
  - `low`
  - `close`
  - `volume`
  - `amount`
  - `turnover_rate`
  - `source`
  - `updated_at`
- `sync_runs`
  - `source`
  - `mode`
  - `started_at`
  - `ended_at`
  - `status`
  - `total_symbols`
  - `success_count`
  - `failure_count`
  - `error_summary`

## 行为约束

- v1 只存 canonical A 股日线，不存多 source 原始表
- SQLite 只保存数据源返回的必要信息，不保存分析报告缓存，也不保存 watch baseline
- API 查询 A 股历史日线时，应优先读 SQLite 仓；缺失时，再回退外部源并回写仓库
- `/watch/poll` 与 `/stock/analyze` 不改对外 contract，只改内部历史日线路径
- 公共 HTTP 接口不暴露 `refresh` 参数
- `/watch/poll` 的 baseline 仅保留进程内内存态，TTL 为 24 小时
- 日更任务优先源为 `Tushare`，fallback 为 `AkShare`、`Efinance`
- 首次回填允许按年窗口，日常刷新允许按天窗口

## 当前未完成项

- 其他依赖历史日线的分析接口尚未统一切到 SQLite 仓
- 定时调度只提供命令入口，调度器编排仍依赖外部 cron / scheduler
- 目前仍未引入多 source 对账与原始表留存
