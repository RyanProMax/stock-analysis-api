# Futu/OpenD 路由与输出 Contract

> 本文件记录 `stock-analysis-skill` 对 Futu/OpenD 能力的统一路由、输出模板和安全边界。本仓库不复制富途脚本，不直接实现行情、账户或交易逻辑；Futu/OpenD 统一通过 `stock-analysis-api/scripts/futu_market_data.py`、`stock-analysis-api/scripts/grey_market_watch.py` 或后续 API provider 扩展接入。尚未迁入 API 的能力必须明确标记为未支持，不再路由到外部 Futu skill。通过本 skill 使用 Futu/OpenD 时只允许查询操作。

## 全局只读护栏

- 只允许调用行情、盘口、逐笔、分时、K 线、IPO、港股 IPO 暗盘 watch、期权链、账户、资金、持仓、订单、成交、流水等查询能力。
- 禁止下单、改单、撤单、交易解锁、订阅推送、创建 / 修改价格提醒、写入 watchlist、修改配置、导出文件或任何其他状态变更。
- 用户明确要求定时只读查询时，允许 API 侧写入 scheduler tick 节流状态；该状态不能包含券商账户、订单、订阅或 watchlist 写入。
- 用户请求写入 / 编辑 / 下单 / 订阅 / 解锁时，必须拒绝执行；不得用模拟账户、已登录 OpenD 或用户二次确认作为绕过理由。

## 能力边界

| 场景 | 默认路由 | 说明 |
| --- | --- | --- |
| A 股标准化客观分析 | `stock-analysis-api` / `scripts/stock_analyze.py` | 保持固定 objective analyze contract |
| A 股股票 / ETF 低 token 行情轮询 | `stock-analysis-api` / `scripts/poll_realtime_quotes.py` | 适合简单 watchlist 与飞书推送 |
| `/hkipo` 当前 IPO 池 | `stock-analysis-api` / `scripts/futu_market_data.py ipo-list --market HK --json` | executor 解析 API root 与绝对 `uv` |
| `/research` 港股预检 / snapshot / K 线 | `stock-analysis-api` / `scripts/futu_market_data.py` | 使用 `global-state`、`snapshot`、`kline` 子命令 |
| 港股 / 美股 / 多市场 snapshot、K 线、市场状态 | `stock-analysis-api` / `scripts/futu_market_data.py` | 支持 `global-state`、`snapshot`、`kline` |
| 盘口、逐笔、分时、期权链 | `stock-analysis-api` / `scripts/futu_market_data.py` | 支持 `order-book`、`ticker`、`rt-data`、`option-expirations`、`option-chain` |
| 港股 IPO 暗盘 / OTC 定时查询 | `stock-analysis-api` / `scripts/grey_market_watch.py` | Futu 为正式 provider；Tiger / Fosun 等未接入正式授权 API 时返回 `unsupported` |
| 账户、资金、持仓、订单、成交、流水 | `stock-analysis-api` / `scripts/futu_market_data.py` | 仅限 Futu `SIMULATE` 环境只读查询，按最小必要原则展示 |
| 窝轮 / 牛熊证、资金流、资金分布、经纪队列、板块与成分股、条件选股、期货资料 | 未迁入 API | 明确返回暂不支持，并进入 API provider backlog |
| OpenD 安装、启动、升级、SDK 环境检查 | 环境前置条件 | 本 skill 不执行安装脚本；只说明 API Futu CLI / OpenD 环境不可用 |
| 原始 Tushare 接口、自定义字段、接口文档 | `Tushare 使用技能` | 保留原始数据研究能力 |

## 通用字段规则

- 时间：面向用户统一展示北京时间（Asia/Shanghai, UTC+8）；源数据时间保留在 `source_time`。
- 百分比：内部 ratio 字段保持小数；面向用户展示为百分比，例如 `0.021` -> `+2.10%`。
- 数据源：必须标注 `source`，例如 `stock-analysis-api`、`futu_opend`、`tushare`。
- 降级：源端不可用时输出 `status=degraded` 或 `status=failed`，不要伪造行情或账户数据。
- 建议边界：不输出买卖建议、目标价、主观 conviction；只输出事实、触发原因和风险提示。

## 跨仓库命令解析

- `/hkipo` 不应把任何用户目录或非 API 脚本路径写死，也不应让宿主 Agent 在当前工作区猜测 `.venv/bin/python`。
- command executor 负责按 `STOCK_ANALYSIS_API_ROOT`、当前
  `.agents/skills/stock-analysis/` 上层 monorepo 根目录、兼容 sibling
  `stock-analysis-api` 的顺序解析 API 根目录，并按 `STOCK_ANALYSIS_UV` /
  `UV_BIN` / `UV` / PATH / `$HOME/.local/bin/uv` / `$HOME/.cargo/bin/uv`
  解析绝对 `uv`。
- `/hkipo` 当前 IPO 池必须生成 `cd <api_root> && <uv> run python scripts/futu_market_data.py ipo-list --market HK --json`；若 API CLI 或 `uv` 缺失，prompt 必须明确写出 Futu/OpenD 预检失败原因，再允许降级到 HKEX / 公司公告 / 财经站。
- `/research HK.*` 与 `/research *.HK` 必须更严格：executor 先用 `cd <api_root> && <uv> run python scripts/futu_market_data.py global-state --json` 做 OpenD 只读预检；API CLI、`uv`、OpenD 或行情登录不可用时，直接返回 `final_markdown` 询问用户是否继续，不生成研报 prompt。
- 只有用户明确追加 `--continue-without-opend` 后，`/research` 港股才允许按 HKEX / 公司公告 / AKShare / yfinance 降级继续；这类确认只放开数据源降级，不放开任何写入、订阅或交易能力。


## Watchlist 选路规则

watchlist 监控必须先按标的、市场和所需数据粒度拆分，不要把所有场景都塞给同一个数据源。

### 默认路由

| 输入特征 | 默认路由 | 原因 |
| --- | --- | --- |
| 全部是 A 股股票 / ETF 的 6 位代码，且只需要现价、涨跌幅、全量快照、简单异动提醒 | `stock-analysis-api` / `scripts/poll_realtime_quotes.py` | 低 token、稳定 JSON、适合 IM 定时推送 |
| 标的包含 `HK.` / `US.` 等 API Futu CLI 已支持市场前缀，且只需 snapshot / K 线 / 盘口 / 逐笔 / 分时 / 期权链 / 市场状态 | `stock-analysis-api` / `scripts/futu_market_data.py` | 需要 Futu 多市场代码体系 |
| 港股 IPO 暗盘 / OTC 报价、剂泰这类新股暗盘定时监听 | `stock-analysis-api` / `scripts/grey_market_watch.py` | 需要暗盘时间窗、provider capability 和调度节流 |
| 用户明确说“富途”“OpenD”“牛牛”“Futu” | API Futu CLI 已支持能力 | 尊重用户指定数据源，但不绕回非 API provider |
| 需要账户、持仓、订单、成交、流水查询 | `stock-analysis-api` / `scripts/futu_market_data.py` | 仅限 Futu `SIMULATE` 只读查询；不触发交易写操作 |
| 需要窝轮 / 牛熊证、资金流、资金分布、经纪队列、板块、条件选股或期货资料 | 未迁入 API | 明确返回暂不支持，不伪造结果 |
| 用户明确要原始 Tushare 字段、接口清单或自定义时间窗 | `Tushare 使用技能` | 保留原始数据研究路径 |

### 混合 watchlist

- 若 watchlist 同时包含 A 股 6 位代码和 `HK.` / `US.` 等前缀代码，先拆成多个 source batch。
- A 股低 token batch 走 `poll_realtime_quotes.py`；多市场 batch 只走 API 已支持的 Futu CLI 能力，未支持字段标记为 `not_supported`。
- 合并输出时统一成 `watch_alert` contract，每个 item 保留 `source`。
- 任一 batch 失败时，只把该 batch 标记为 `degraded` 或 `failed`，不要影响其他 batch 的成功结果。

### A 股是否改走 Futu

A 股默认仍走 `stock-analysis-api` CLI。只有以下情况才把 A 股 watchlist 改走 Futu/OpenD：

- 用户明确指定“用富途 / OpenD 查 A 股”；
- 需要盘口、逐笔、分时、K 线查询；
- 需要和富途账户持仓、订单等只读信息联动；
- `poll_realtime_quotes.py` 明确不支持该标的，且可以确定对应 Futu 代码（例如 `SH.600000` / `SZ.000001`）。

### 失败与降级

- Futu 路由需要 OpenD；如果 OpenD 未启动或 SDK 不满足要求，说明 API Futu CLI / OpenD 环境不可用，不要伪造行情。
- `poll_realtime_quotes.py` 返回 `partial` 时，成功 item 正常展示，失败 item 进入异常区或按用户要求剔除。
- 用户要求“全量标的都返回”时，输出所有成功 item；异动 item 加 emoji 和原因。
- 用户要求“不说明未纳入”时，只展示成功监控集合，不输出剔除列表。

## `quote_snapshot`

用于单标的或多标的现价快照。

```json
{
  "type": "quote_snapshot",
  "status": "ok",
  "source": "futu_opend",
  "market": "HK",
  "symbol": "HK.00700",
  "name": "腾讯控股",
  "price": 0.0,
  "change_pct": 0.0,
  "change_amount": 0.0,
  "source_time": "2026-04-27T10:30:00+08:00",
  "display_time": "2026-04-27 10:30 北京时间",
  "extra": {
    "volume": null,
    "turnover": null,
    "market_state": null
  }
}
```

用户展示模板：

```text
{symbol} {name} {price} {change_pct_display}
```

## `watch_alert`

用于 watchlist 全量快照和异动提醒。

```json
{
  "type": "watch_alert",
  "status": "ok",
  "display_time": "2026-04-27 10:30 北京时间",
  "summary": {"total": 15, "ok": 15, "alert_count": 2},
  "items": [
    {
      "symbol": "603228",
      "name": "景旺电子",
      "price": 75.35,
      "change_pct": 0.1,
      "is_alert": true,
      "emoji": "🚨",
      "reason": ["涨跌幅 +10.00%", "接近/达到涨停"]
    }
  ]
}
```

用户展示模板：

```text
盯盘全量快照：成功 {ok}/{total}，异动 {alert_count}
- 🚨 603228 景旺电子 75.35 +10.00%：涨跌幅 +10.00%；接近/达到涨停
- 300033 同花顺 230.75 +0.98%
```

## `grey_market_watch`

用于港股 IPO 暗盘 / OTC 跨 provider 快照、单次查询和定时 tick。用户可通过 `/otc 07666.HK` 做单次查询，或通过 `/otc 07666.HK --loop=300s` 请求 300 秒轮询 tick；非暗盘时间由 command 入口直接结束并提示。

```json
{
  "type": "grey_market_watch",
  "status": "ok",
  "source": "grey_market_watch_tick",
  "schedule": {
    "mode": "tick",
    "timezone": "Asia/Shanghai",
    "active_window": "16:15-18:30",
    "interval_seconds": 10
  },
  "watch": {
    "status": "ok",
    "request": {
      "code": "HK.02618",
      "name": "剂泰医药",
      "issue_price": 10.0,
      "providers": ["futu", "tiger", "fosun"]
    },
    "summary": {
      "ok_count": 1,
      "unsupported_count": 2,
      "failed_count": 0,
      "price_spread": null
    },
    "providers": [
      {
        "provider": "futu",
        "status": "ok",
        "official_api": true,
        "quote": {
          "price": 11.2,
          "dark_status": "TRADING",
          "change_vs_issue_pct": 0.12
        }
      },
      {
        "provider": "tiger",
        "status": "unsupported",
        "official_api": false
      }
    ]
  }
}
```

展示规则：

- 先展示可用 provider 的最新价、相对发行价涨跌幅、bid / ask 和时间。
- `source=grey_market_watch_once` 表示单次查询，不应写 scheduler tick 状态；`source=grey_market_watch_tick` 表示轮询 tick，可按 `schedule.next_run_at` 展示下一次。
- `unsupported` provider 单独列出“未接入正式 API”，不要补编报价。
- 只有多个 provider 都返回价格时，才展示跨 provider 价差；单一 provider 报价不得写成“全市场暗盘价”。

## `option_chain`

用于期权链与期权筛选结果。

```json
{
  "type": "option_chain",
  "status": "ok",
  "source": "futu_opend",
  "underlying": "US.AAPL",
  "expiration": "2026-05-15",
  "items": [
    {
      "code": "US.AAPL260515C200000",
      "option_type": "CALL",
      "strike": 200.0,
      "last_price": 0.0,
      "implied_volatility": null,
      "delta": null,
      "volume": null,
      "open_interest": null
    }
  ]
}
```

用户展示优先字段：到期日、Call/Put、行权价、最新价、IV、Delta、成交量、未平仓量。

## `portfolio_risk`

用于账户、持仓、资金、订单的只读汇总。

```json
{
  "type": "portfolio_risk",
  "status": "ok",
  "source": "futu_opend",
  "environment": "SIMULATE",
  "display_time": "2026-04-27 10:30 北京时间",
  "account_summary": {
    "cash": null,
    "market_value": null,
    "total_assets": null,
    "currency": null
  },
  "positions": [
    {
      "symbol": "US.AAPL",
      "name": "Apple",
      "quantity": 0,
      "market_value": null,
      "unrealized_pnl": null,
      "weight": null
    }
  ],
  "risk_flags": []
}
```

安全要求：账户号、资金、持仓等敏感字段按最小必要原则展示；不得把账户信息用于非用户请求场景。

## API Futu CLI 子命令

常用只读命令：

```bash
cd "$STOCK_ANALYSIS_API_ROOT" && "$STOCK_ANALYSIS_UV" run python scripts/futu_market_data.py order-book --code HK.00700 --num 10 --json
cd "$STOCK_ANALYSIS_API_ROOT" && "$STOCK_ANALYSIS_UV" run python scripts/futu_market_data.py ticker --code HK.00700 --num 500 --json
cd "$STOCK_ANALYSIS_API_ROOT" && "$STOCK_ANALYSIS_UV" run python scripts/futu_market_data.py rt-data --code HK.00700 --json
cd "$STOCK_ANALYSIS_API_ROOT" && "$STOCK_ANALYSIS_UV" run python scripts/futu_market_data.py option-chain --code US.AAPL --start 2026-05-15 --end 2026-06-19 --option-type CALL --json
cd "$STOCK_ANALYSIS_API_ROOT" && "$STOCK_ANALYSIS_UV" run python scripts/futu_market_data.py account --market HK --currency HKD --json
cd "$STOCK_ANALYSIS_API_ROOT" && "$STOCK_ANALYSIS_UV" run python scripts/futu_market_data.py positions --market HK --code HK.00700 --json
cd "$STOCK_ANALYSIS_API_ROOT" && "$STOCK_ANALYSIS_UV" run python scripts/futu_market_data.py orders --market HK --code HK.00700 --start 2026-05-01 --end 2026-05-07 --history --json
cd "$STOCK_ANALYSIS_API_ROOT" && "$STOCK_ANALYSIS_UV" run python scripts/futu_market_data.py deals --market HK --code HK.00700 --start 2026-05-01 --end 2026-05-07 --history --json
cd "$STOCK_ANALYSIS_API_ROOT" && "$STOCK_ANALYSIS_UV" run python scripts/futu_market_data.py cash-flow --market HK --clearing-date 2026-05-07 --json
cd "$STOCK_ANALYSIS_API_ROOT" && "$STOCK_ANALYSIS_UV" run python scripts/grey_market_watch.py --once --code HK.02618 --name 剂泰医药 --issue-price 10 --providers futu,tiger,fosun --json
cd "$STOCK_ANALYSIS_API_ROOT" && "$STOCK_ANALYSIS_UV" run python scripts/grey_market_watch.py --code HK.02618 --name 剂泰医药 --issue-price 10 --providers futu,tiger,fosun --interval-seconds 300 --json
```

这些命令只允许查询，不暴露 `place-order`、`modify-order`、`cancel-order`、`unlock-trade`、`subscribe` 等写入类子命令。

## 写入请求拒绝模板

遇到下单、改单、撤单、订阅、交易解锁、写入自选股、创建 / 修改提醒、导出文件或修改配置等请求时，直接拒绝执行。

```text
我不能执行这个操作。stock-analysis-skill 只允许查询操作，禁止任何写入、编辑、下单、订阅、交易解锁或账户 / 订单 / 配置状态变更。可以继续帮你查询行情、盘口、K 线、IPO、期权链、账户、资金、持仓、订单、成交或流水等只读信息。
```
