# Futu 内部 CLI Contract

更新时间：2026-05-06

## 目标

把 `stock-analysis-skill` 中 `/hkipo` 和 `/research` 已用到的 Futu/OpenD 只读能力迁移到 `stock-analysis-api`，让 skill 只通过 API 仓库内部 CLI 取数，不再解析或调用外部 `futuapi` skill 脚本。

## 范围

新增内部 CLI：

```bash
uv run python scripts/futu_market_data.py <command> --json
```

第一阶段只覆盖已被 `/hkipo` / `/research` / HK IPO 回测实际使用的能力：

- `global-state`：OpenD 行情登录和全局状态预检，替代 `futuapi/scripts/quote/get_global_state.py`
- `ipo-list --market HK`：港股 IPO 当前池，替代 `futuapi/scripts/quote/get_ipo_list.py HK`
- `kline --code HK.00700 --start YYYY-MM-DD --end YYYY-MM-DD --ktype 1d --rehab none`：历史日 K，替代 HK IPO 回测里直接调用 Futu SDK
- `snapshot --codes HK.00700,US.AAPL`：港股 `/research` prompt 中需要的只读行情快照入口

## 运行依赖

- API 仓库声明 `futu-api>=10.4.6408` 依赖，内部 CLI 必须在 `uv run` 环境中可直接 `import futu`。
- OpenD 默认地址为 `127.0.0.1:11111`，可通过 `FUTU_OPEND_HOST` / `FUTU_OPEND_PORT` 覆盖。
- skill 侧只解析 API root 与绝对 `uv`，不再调用外部 `futuapi` skill 脚本或其 Python venv。

## 非范围

- 不新增公共 HTTP API。
- 不迁移盘口、逐笔、分时、期权、账户、持仓和订单只读查询；这些后续按能力逐步迁移。
- 不实现真实交易、交易解锁、订阅推送或 OpenD 配置写入。
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
