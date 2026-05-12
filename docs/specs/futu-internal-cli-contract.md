# Futu 内部 CLI Contract

更新时间：2026-05-12

## 目标

把 `stock-analysis-skill` 中 `/hkipo` 和 `/research` 已用到的 Futu/OpenD 只读能力迁移到 `stock-analysis-api`，让 skill 只通过 API 仓库内部 CLI 取数，不再解析或调用外部 `futuapi` skill 脚本。

## 范围

新增内部 CLI：

```bash
uv run python scripts/futu_market_data.py <command> --json
```

第一阶段覆盖已被 `/hkipo` / `/research` / HK IPO 回测实际使用的能力：

- `global-state`：OpenD 行情登录和全局状态预检，替代 `futuapi/scripts/quote/get_global_state.py`
- `ipo-list --market HK`：港股 IPO 当前池，替代 `futuapi/scripts/quote/get_ipo_list.py HK`
- `kline --code HK.00700 --start YYYY-MM-DD --end YYYY-MM-DD --ktype 1d --rehab none`：历史日 K，替代 HK IPO 回测里直接调用 Futu SDK
- `snapshot --codes HK.00700,US.AAPL`：港股 `/research` prompt 中需要的只读行情快照入口
- `symbol-rules --codes HK.00700,US.AAPL`：逐标的交易规则，只读输出 Futu snapshot 中的 `lot_size` / `price_spread`，缺失时回退到 `MarketSpec` 默认值

第二阶段补齐高频只读查询能力：

- `order-book --code HK.00700 --num 10`：盘口查询
- `ticker --code HK.00700 --num 500`：逐笔成交查询
- `rt-data --code HK.00700`：分时数据查询
- `option-expirations --code US.AAPL`：期权到期日查询
- `option-chain --code US.AAPL --start YYYY-MM-DD --end YYYY-MM-DD --option-type CALL|PUT|ALL`：期权链查询
- `account --market HK --currency HKD`：Futu `SIMULATE` 账户资金只读查询
- `positions --market HK --code HK.00700`：Futu `SIMULATE` 持仓只读查询
- `orders --market HK --code HK.00700 --start YYYY-MM-DD --end YYYY-MM-DD --history`：Futu `SIMULATE` 订单只读查询
- `deals --market HK --code HK.00700 --start YYYY-MM-DD --end YYYY-MM-DD --history`：Futu `SIMULATE` 成交只读查询
- `cash-flow --market HK --clearing-date YYYY-MM-DD`：Futu `SIMULATE` 交易流水只读查询

灰市 / 暗盘 watch 能力独立为 `scripts/grey_market_watch.py`，不塞进通用 Futu 查询 CLI。它复用 Futu OpenD snapshot / order book，并额外处理暗盘时间窗、provider capability 状态、单次查询和调度节流；详见 `docs/specs/grey-market-watch.md`。

## 运行依赖

- API 仓库声明 `futu-api>=10.4.6408` 依赖，内部 CLI 必须在 `uv run` 环境中可直接 `import futu`。
- OpenD 默认地址为 `127.0.0.1:11111`，可通过 `FUTU_OPEND_HOST` / `FUTU_OPEND_PORT` 覆盖。
- skill 侧只解析 API root 与绝对 `uv`，不再调用外部 `futuapi` skill 脚本或其 Python venv。

## 非范围

- 不新增公共 HTTP API。
- 不实现真实交易、交易解锁、订阅推送或 OpenD 配置写入。
- 不在 `futu_market_data.py` 暴露下单、改单、撤单、交易解锁、订阅、提醒、自选股或配置写入类子命令。
- 不从 API 仓库反向调用外部 `futuapi` skill 脚本。

## 输出

所有命令 stdout 只输出 JSON：

```json
{
  "status": "ok",
  "source": "futu_opend",
  "data": []
}
```

失败时：

```json
{
  "status": "failed",
  "source": "futu_opend",
  "error": "..."
}
```

输出约束：

- stdout 必须是可被严格 JSON parser 解析的标准 JSON，不允许混入 Futu SDK 连接日志。
- 成功路径不向 stderr 输出 Futu SDK warning / log 噪声。
- Futu 原始数据里的 `NaN` / `Infinity` 等非有限数值统一归一化为 `null`。
- 账户、持仓、订单、成交和流水查询固定使用 Futu `TrdEnv.SIMULATE`，且只读展示最小必要信息；不得触发 `place_order`、`modify_order`、`cancel_order`、`unlock_trade`、`subscribe` 或其他写操作。
