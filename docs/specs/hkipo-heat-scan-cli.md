# HK IPO Heat Scan CLI

## 目标

`scripts/hkipo_heat_scan.py` 是内部 agent / skill workflow 使用的只读数据采集入口，不属于公共 HTTP API。它接收 Futu/OpenD 已发现的港股 IPO 池，补充三类核心证据：二级热度证据（孖展 / 融资倍数、公开认购倍数、一手中签率、暗盘、来源时间和来源冲突）、发行结构证据（绿鞋 / 超额配股权、稳定价格操作人、基石投资者与占比、保荐人、公开发售比例、回拨机制）和估值证据（主营业务、核心能力、行业、发行市值、同类股票 PE/PS/PB、合理估值区间）。

输入 IPO 若带有 `display_name` / `name_zh` / `cn_name`，CLI 生成检索计划和输出 `data[].name` 时必须优先使用中文展示名；`name_en` / `english_name` / 原始 `name` 只作为英文别名保留，避免最终 workflow 报告主标题退回英文简称。

## 输入

```bash
uv run python scripts/hkipo_heat_scan.py \
  --date 2026-05-17 \
  --ipos-json /tmp/ipos.json \
  --json
```

- `--date`：报告日期，默认北京时间当天。
- `--ipos-json`：必填，JSON list 或 `{ "data": [...] }`。
- `--include-closed`：允许已截止认购但未上市 IPO 参与扫描。
- `--json` / `--pretty`：输出严格 JSON；`--pretty` 仅改变缩进。

## 执行预算

- 单只 IPO 内部按来源做有界并发抓取，默认最多 10 个 worker，避免 10 个公开来源逐个超时把 workflow 拖到分钟级。
- 每个公开来源默认 6 秒超时；可用 `HKIPO_HEAT_SCAN_FETCH_TIMEOUT_SECONDS` 调整。
- worker 数可用 `HKIPO_HEAT_SCAN_MAX_WORKERS` 调整；不要设置为无限并发，避免对公开网站造成不必要压力。
- 单个来源失败只写入 `data[].source_errors[]`，不阻断其他来源证据，也不让 CLI 因网页结构变化直接失败。

## 输出 Contract

顶层字段：

- `status`
- `source = hkipo_heat_scan`
- `report_date`
- `summary`
- `data`
- `errors`

`data[]` 名称字段：

- `code`
- `name`：中文展示名优先
- `name_en`：Futu/OpenD 原始英文简称或英文名
- `query_plan`

`data[].evidence[]` 每条证据必须包含：

- `source`
- `source_family`
- `field`
- `value`
- `unit`
- `published_at` 或 `updated_at`
- `url`
- `confidence`
- `staleness_status`

缺少来源时间、URL 或 confidence 时，不得进入主热度评分；CLI 会把该 IPO 降级为：

- `heat_status = heat_threshold_not_met`
- `evidence_quality = low`
- `subscription_heat.status = 热度未达当日核验门槛`

`data[].structure_evidence[]` 与 `data[].valuation_evidence[]` 使用同一归因字段 contract，并额外允许 `peer`、`value.low/value.high` 等结构化字段。状态字段：

- `structure_status = core_structure_verified | partial_structure_verified | core_structure_not_verified`
- `valuation_status = valuation_context_verified | partial_valuation_verified | valuation_context_not_verified`

结构字段最少覆盖：

- `greenshoe_pct`
- `cornerstone_investor_count`
- `cornerstone_offer_pct`
- `sponsor`
- `stabilizing_manager`
- `public_float_pct`
- `clawback_max_pct`

估值字段最少覆盖：

- `core_business`
- `core_capability`
- `industry`
- `peer_pe` / `peer_ps` / `peer_pb`
- `offer_market_cap`
- `fair_value_market_cap_range` 或 `fair_value_price_range`

拿不到字段时不得编造；必须保留 `source_errors[]` 或输出缺失状态，供 workflow 最终报告写“多源未取到”。

## 安全边界

- 只做公开只读数据采集。
- 不登录券商账户。
- 不绕过付费、验证码或反爬限制。
- CI 不访问真实网页；测试使用 fake service / fixture。
