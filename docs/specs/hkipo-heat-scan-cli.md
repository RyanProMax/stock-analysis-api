# HK IPO Heat Scan CLI

## 目标

`scripts/hkipo_heat_scan.py` 是内部 agent / skill workflow 使用的只读数据采集入口，不属于公共 HTTP API。它接收 Futu/OpenD 已发现的港股 IPO 池，补充二级热度证据：孖展 / 融资倍数、公开认购倍数、一手中签率、暗盘、来源时间和来源冲突。

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

## 输出 Contract

顶层字段：

- `status`
- `source = hkipo_heat_scan`
- `report_date`
- `summary`
- `data`
- `errors`

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

## 安全边界

- 只做公开只读数据采集。
- 不登录券商账户。
- 不绕过付费、验证码或反爬限制。
- CI 不访问真实网页；测试使用 fake service / fixture。
