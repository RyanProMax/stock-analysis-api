# HK/US Alpha Futu Warehouse

## Goal

先在不依赖 Tushare 的情况下跑通港股 / 美股 Alpha 研究链路：

Futu OpenD daily kline -> local SQLite daily warehouse -> alpha scan -> alpha evaluate -> alpha daily report -> alpha research loop。

Status: first explicit-symbol MVP completed on 2026-05-10.

## Scope

- 第一阶段只支持显式 symbols，例如 `HK.00700,US.AAPL`。
- 不做港股 / 美股全市场 universe 抓取。
- 不做实时交易、不订阅、不解锁、不写订单。
- `sync-market-data --market hk/us --scope symbol` 可用 Futu 日 K 补本地仓。
- Alpha CLI 必须接受 `--market hk`；`cn/us` 既有语义不回退。

## Data Contract

- SQLite 日线仓新增 `hk_symbols` 和 `hk_daily`，字段与 `cn/us` 日线表保持同构。
- `symbol` 对 HK 保留 Futu 原生前缀，例如 `HK.00700`，避免和 A 股 6 位数字冲突。
- `ts_code` 对 HK 使用同一 Futu code。
- Futu kline 的 `time_key` 标准化为 `date` / `trade_date`。
- Futu kline 的 `turnover` 标准化为 `amount`，避免和 `turnover_rate` 混淆。
- Futu source 只沉淀 OHLCV 和必要 source metadata；财务、lot size、tick size 等市场细节后续单独补 MarketSpec。

## Acceptance

- repository 可 upsert / load / search HK symbols 和 HK daily bars。
- `sync-market-data --market hk --scope symbol --symbol HK.00700` 可通过 Futu daily source 写入 HK daily。
- `alpha_scan.py --market hk --symbols HK.00700` 能基于本地日线输出候选。
- `alpha_evaluate.py --market hk --symbols HK.00700,HK.09988` 能输出因子评估。
- `alpha_research_loop.py --market hk --symbols ...` 能进入 `human_review_ready` 或 `needs_iteration`，不触发 broker。
