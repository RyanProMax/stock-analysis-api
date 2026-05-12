# HK Grey-Market Watch Contract

更新时间：2026-05-12

## 目标

为 skill / Agent 提供港股 IPO 暗盘（grey market / OTC）只读查询入口，支持 cron / launchd / Agent 定时 tick 调用。该能力只做行情查询和跨 provider 状态聚合，不下单、不订阅、不解锁交易、不写 watchlist 或券商配置。

## 内部 CLI

```bash
uv run python scripts/grey_market_watch.py --code HK.02618 --name 剂泰医药 --issue-price 10 --json
```

常用调度参数：

- `--providers`: 默认 `futu,tiger,fosun`。当前仅 `futu` 接入正式 API；`tiger` / `fosun` 返回 `status=unsupported`，等待正式授权 API adapter。
- `--order-book-depth`: 默认 5，Futu provider 会尝试只读盘口摘要。
- `--timezone`: 默认 `Asia/Shanghai`。
- `--active-window`: 默认 `16:15-18:30`。
- `--interval-seconds`: 默认 10。
- `--state-db`: SQLite scheduler tick 状态库路径；默认 `.cache/grey_market_watch.sqlite`，只保存调度节流状态，不保存券商账户或订单状态。
- `--state-key`: 可选，不传时按代码、provider 和发行价生成。
- `--force`: 忽略时间窗和间隔，仅用于显式验证。

## Provider 状态

### Futu

- 状态：正式 provider。
- 数据源：Futu OpenD `get_market_snapshot` + `get_order_book`。
- 输出字段：`dark_status`、最新价、bid / ask、成交量、成交额、相对发行价涨跌幅、相对前收涨跌幅、盘口最优买卖档。

### Tiger / Fosun

- 状态：`unsupported`。
- 原因：尚未接入正式授权 API adapter。
- 约束：不得用网页抓取或非授权接口伪造“全券商暗盘报价”。

## 输出 Contract

到点执行：

```json
{
  "status": "ok",
  "source": "grey_market_watch_tick",
  "schedule": {
    "state_key": "grey-market-watch:...",
    "timezone": "Asia/Shanghai",
    "active_window": "16:15-18:30",
    "interval_seconds": 10
  },
  "watch": {
    "status": "ok",
    "source": "grey_market_watch",
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
    "providers": []
  }
}
```

未到时间窗：

```json
{"status": "skipped", "reason": "outside_active_window"}
```

未到执行间隔：

```json
{"status": "skipped", "reason": "not_due"}
```

## 安全边界

- 不暴露下单、改单、撤单、交易解锁、订阅或自选股写入能力。
- 不把单一 provider 报价解释为全市场暗盘价。
- provider 不支持或源端不可用时明确输出 `unsupported` / `failed`，不得补编报价。
