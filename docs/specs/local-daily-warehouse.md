# 本地 SQLite 日线仓规格

更新时间：2026-03-22

## 目标

- 为 A 股和美股提供单机本地 SQLite canonical 日线仓
- 支持统一同步命令按市场 / 单股 / 时间窗口写入 symbol 元数据、日线数据和同步任务记录
- 让 `/watch/poll` 与 `/stock/analyze` 优先读取本地仓中的历史日线，并按 freshness 自动补数

## 数据模型

- `a_share_symbols` / `us_symbols`
  - `symbol`
  - `ts_code`
  - `name`
  - `area`
  - `industry`
  - `market`
  - `exchange`
  - `list_date`
  - `updated_at`
  - `extra`
- `a_share_daily` / `us_daily`
  - 主键：`(symbol, trade_date)`
  - `symbol`
  - `ts_code`
  - `trade_date`
  - `open`
  - `high`
  - `low`
  - `close`
  - `pre_close`
  - `change`
  - `pct_chg`
  - `vol`
  - `amount`
  - `adj_factor`
  - `is_suspended`
  - `up_limit`
  - `down_limit`
  - `source`
  - `updated_at`
  - `extra`
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

- v1 只存 canonical symbol 与日线事实，不存多 source 原始表，不存技术指标，不存分析结果
- SQLite 只保存数据源返回的必要信息与事实型扩展字段，不保存分析报告缓存，也不保存 watch baseline
- API 查询历史日线时，应优先读 SQLite 仓；若最近一条数据超过 7 个自然日，则回退外部源并回写仓库
- `/watch/poll` 与 `/stock/analyze` 不改对外 contract，只改内部历史日线路径
- 公共 HTTP 接口不暴露 `refresh` 参数
- `/watch/poll` 的 baseline 仅保留进程内内存态，TTL 为 24 小时
- A 股 symbols 优先源为 `Tushare`，fallback 为 `Efinance`、`AkShare`
- A 股 daily 优先源为 `Tushare`，fallback 为 `AkShare`、`Efinance`
- 统一同步命令为 `uv run sync-market-data`
- 同步命令参数固定：
  - `--market {cn,us}`
  - `--scope {all,symbol}`
  - `--symbol`
  - `--days`
  - `--years`
- `extra` 仅保存事实型扩展字段，如 `turnover_rate`、`vwap`、`free_share`、`total_share`、`free_mv`、`total_mv`

## 当前未完成项

- 其他依赖历史日线的分析接口尚未统一切到 SQLite 仓
- 定时调度只提供命令入口，调度器编排仍依赖外部 cron / scheduler
- 目前仍未引入多 source 对账与原始表留存
