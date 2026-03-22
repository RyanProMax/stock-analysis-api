# 本地 SQLite 日线仓规格

更新时间：2026-03-22

## 目标

- 为 A 股和美股提供单机本地 SQLite canonical 日线仓
- 支持统一同步命令按市场 / 单股 / 时间窗口写入 symbol 元数据、日线数据和同步任务记录
- 让 `/watch/poll` 与 `/stock/analyze` 优先读取本地仓中的历史日线，并按 freshness 自动补数
- 统一采用 `cn_* / us_*` 命名，不再保留 `a_share_*`

## 数据模型

- `cn_symbols` / `us_symbols`
  - `symbol`
  - `ts_code`
  - `name`
  - `area`
  - `industry`
  - `market`
  - `exchange`
  - `cnspell` (`cn_symbols`)
  - `list_date`
  - `updated_at`
  - `extra`
- `cn_daily` / `us_daily`
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
  - `turnover_rate`
  - `turnover_rate_f`
  - `volume_ratio`
  - `pe`
  - `pe_ttm`
  - `pb`
  - `ps`
  - `ps_ttm`
  - `dv_ratio`
  - `dv_ttm`
  - `float_share`
  - `free_share`
  - `total_share`
  - `circ_mv`
  - `total_mv`
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
  - `market`
  - `scope`
  - `symbol`
  - `requested_start_date`
  - `requested_end_date`
  - `requested_days`
  - `requested_years`
  - `universe_source`
  - `started_at`
  - `ended_at`
  - `status`
  - `total_symbols`
  - `processed_count`
  - `skipped_count`
  - `success_count`
  - `failure_count`
  - `rows_written`
  - `error_summary`
  - `error_details`
  - `symbol_snapshot_count`
  - `symbol_snapshot_updated_at`
  - `target_latest_trade_date`
  - `coverage_start_date`
  - `coverage_end_date`
  - `covered_symbol_count`
  - `missing_symbol_count`
  - `stale_symbol_count`
  - `daily_row_count`
  - `is_data_current`

## 行为约束

- v1 只存 canonical symbol 与日线事实，不存多 source 原始表，不存技术指标，不存分析结果
- SQLite 只保存数据源返回的必要信息与事实型扩展字段，不保存分析报告缓存，也不保存 watch baseline
- `cn_symbols` 只保存当前上市 A 股最新快照；刷新列表时按市场快照覆盖写入
- `cn_symbols` 当前 listed 口径固定为 `Tushare stock_basic(exchange='', list_status='L')`
- `cn_daily` 的全市场补库口径固定为当前上市 A 股、自 `2026-01-01` 起的日线数据
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
  - `--start-date`
- `sync-market-data` 应先查最新 `sync_runs`，再结合 live universe 与目标最新交易日判定：
  - `skipped`
  - symbol 缺口补齐
  - stale 日线补齐
  - 历史窗口补齐
- stale 判定采用 freshness grace，不要求每个 symbol 都精确等于市场最新交易日；同一状态重复执行应进入 `skipped`
- A 股主字段承接规则固定为：
  - `stock_basic` -> `cn_symbols` 主列 + `extra`
  - `daily` -> OHLCV / 涨跌幅主列
  - `daily_basic` -> 标准化日级市场事实主列
  - `adj_factor` -> `adj_factor`
  - `stk_limit` -> `up_limit` / `down_limit`
  - `suspend_d` -> `is_suspended`
- `extra` 仅保存非标准或暂不标准化的事实字段，如 `vwap`

## 当前观察项

- 现网已完成 `sync_runs` 状态快照升级、`cn_daily` 的 `daily_basic` 主列落地，以及旧行回填
- 截至 `2026-03-22`，A 股 listed universe 为 `5000`，`cn_daily` 行数为 `244475`，`total_mv` 缺口为 `0`
- 当前仍有 `4` 只 source-limited symbol 的最新日线早于 market latest，需要后续评估是否单独建模“停牌 / 无成交 / source latest available”语义
