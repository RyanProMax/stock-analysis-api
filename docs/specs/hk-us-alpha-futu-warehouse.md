# HK/US Alpha Futu Warehouse

## Goal

先在不依赖 Tushare 的情况下跑通港股 / 美股 Alpha 研究链路：

Futu OpenD daily kline -> local SQLite daily warehouse -> alpha scan -> alpha evaluate -> alpha daily report -> alpha research loop。

Status: explicit symbol, explicit symbol-batch, and tracked seed MVP completed on 2026-05-11.

## Scope

- 第一阶段只支持显式 symbols，例如 `HK.00700,US.AAPL`；补库入口支持单标的 `--symbol` 和逗号分隔批量 `--symbols`。
- `config/alpha_universe_seeds.json` 提供可审计的 HK / US 种子池；`--universe-seed` 只把 seed 展开成显式 symbols，不做全市场抓取。
- 不做港股 / 美股全市场 universe 抓取。
- 不做实时交易、不订阅、不解锁、不写订单。
- `sync-market-data --market hk/us --scope symbol --symbol ...` 可用 Futu 日 K 补单标的本地仓。
- `sync-market-data --market hk/us --scope symbol --symbols ...` 可用 Futu 日 K 批量补显式标的本地仓。
- `sync-market-data --market hk/us --scope symbol --universe-seed ...` 可从 seed 读取显式 symbols 后批量补库。
- Alpha CLI 必须接受 `--market hk`；`cn/us` 既有语义不回退。

## Data Contract

- SQLite 日线仓新增 `hk_symbols` 和 `hk_daily`，字段与 `cn/us` 日线表保持同构。
- `symbol` 对 HK 保留 Futu 原生前缀，例如 `HK.00700`，避免和 A 股 6 位数字冲突。
- `ts_code` 对 HK 使用同一 Futu code。
- Futu kline 的 `time_key` 标准化为 `date` / `trade_date`。
- Futu kline 的 `turnover` 标准化为 `amount`，避免和 `turnover_rate` 混淆。
- Futu source 只沉淀 OHLCV 和必要 source metadata；市场细节由 `src/model/market.py` 的 `MarketSpec` 独立表达，不写入 Futu 日线 source。
- HK / US Alpha 评估未显式传 `--cost-bps` 时，使用 `MarketSpec` 的市场默认 round-trip 成本模型；显式传参时保留 fixed bps override。
- Seed contract 固定为 `version` + `seeds[]`；每个 seed 至少包含 `id`、`market`、`symbols`，可选 `description`。

## Acceptance

- repository 可 upsert / load / search HK symbols 和 HK daily bars。
- `sync-market-data --market hk --scope symbol --symbol HK.00700` 可通过 Futu daily source 写入 HK daily。
- `sync-market-data --market hk --scope symbol --symbols HK.00700,HK.09988` 可在同一 sync run 内写入多只 HK daily，并回写覆盖摘要。
- `sync-market-data --market hk --scope symbol --universe-seed hk_core` 可从默认 seed 文件补 HK daily。
- `alpha_scan.py --market hk --symbols HK.00700` 能基于本地日线输出候选。
- `alpha_evaluate.py --market hk --symbols HK.00700,HK.09988` 能输出因子评估。
- `alpha_research_loop.py --market hk --symbols ...` 能进入 `human_review_ready` 或 `needs_iteration`，不触发 broker。
