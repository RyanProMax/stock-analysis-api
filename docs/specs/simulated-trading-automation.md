# 模拟盘自动交易一期规格

更新时间：2026-05-05

## 目标

在 `stock-analysis-api` 内建设一个可审计、可回测、可迭代的模拟盘自动交易基础闭环：

1. 定时 worker 按固定流程轮询行情、执行当前策略、通过风控、写入模拟盘订单和运行结果。
2. 每日收盘后产出行情与操作总结，后续接入回测评估。
3. Agent 只参与盘后分析和策略迭代方向生成，不参与轮询链路的即时下单判断。
4. Futu/OpenD 作为 API 内部正式 data provider / broker adapter 接入，不直接调用外部 `futuskill` 脚本。

## 边界

- 第一期不新增公共 HTTP API。
- 第一期只提供内部 service / script 能力，后续如需外部控制面再补 HTTP contract。
- Futu 交易环境固定为 `SIMULATE`。
- 不实现真实交易、不调用或封装 `unlock_trade`、不写 OpenD 配置、不做订阅推送。
- 不把 `stock-analysis-skill` 或 `futuskill` 变成 API 的运行时依赖；skill 侧经验只作为 adapter 设计参考。
- 订单执行必须由确定性 service 完成，不能把实时下单决策交给 Agent 文案输出。

## 一期模块

### 行情 provider

- 新增 `src/data_provider/sources/futu.py`
- `FutuMarketDataProvider` 从 Futu OpenD snapshot 读取行情。
- 输入代码统一为 Futu 格式：
  - `HK.00700`
  - `US.AAPL`
  - `SH.600000`
  - `SZ.000001`
- 输出统一为 `MarketSnapshot`，保留 `source="futu_opend"` 和原始 `raw`。

### 交易执行 service

- 新增统一交易 contract：账户、持仓、行情、信号、订单请求。
- 新增 `TradingAutomationService.run_once(codes)`，单次执行流程固定为：
  1. 读取市场 snapshot
  2. 读取账户和持仓
  3. 用当前策略版本生成机器可解释 signal
  4. 风控检查
  5. 生成带 idempotency key 的 `SIMULATE` 订单
  6. 调用 broker adapter 下单
  7. 返回结构化执行结果
- 首个策略实现只用于建立 contract，不代表正式交易策略。

### Agent 参与点

Agent 只在盘后或离线任务中消费：

- 当日行情和订单摘要
- 策略版本表现
- 回测指标
- 风控拒绝原因

Agent 输出只能是结构化 `strategy_proposal`，必须经过：

1. schema 校验
2. 回测门槛
3. 人工批准

才能进入候选或生效策略版本。

## 测试要求

- 单元测试必须用 fake Futu gateway / fake broker，不依赖真实 OpenD。
- 覆盖 Futu code normalization。
- 覆盖 Futu snapshot 到 `MarketSnapshot` 的字段映射。
- 覆盖 `run_once` 默认 `SIMULATE` 下单。
- 覆盖 idempotency key 去重，重复轮询不能重复下单。
- 覆盖最大订单金额风控拒绝。
- SDK 缺失或 OpenD 不可用时，模块 import 不能失败，只有真实调用时返回明确错误。
