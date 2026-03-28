# Tushare-First Research Snapshot 规格

更新时间：2026-03-28

## 目标

- 提供一个供内部 Agent / skill 调用的研报快照脚本入口
- 当前只交付 `CN` 股票；`US` 仅保留结构化占位响应
- 统一以 Tushare 字段和时间语义为主规范，不输出自由文本结论

## 入口与边界

- 入口文件：`scripts/poll_research_snapshot.py`
- 用途：内部 skill / agent 调用脚本
- 不属于公共 HTTP API
- 不注册到 `pyproject.toml` 的 `[project.scripts]`

## CLI

- `--market cn|us`，默认 `cn`
- `--symbols` 必填，逗号分隔，保序去重
- `--start-date` / `--end-date` 格式 `YYYYMMDD`
- 默认窗口：
  - `end_date = today`
  - `start_date = end_date - 30d`
- `--pretty` 控制 JSON 美化输出

## 顶层输出

- `status`
- `computed_at`
- `source`
- `market`
- `strategy`
- `request`
- `items`

固定约束：

- `strategy = "tushare_first_research_snapshot_v1"`
- 输出只允许 JSON，不允许自由文本总结

## Item 输出

每个 item 固定字段：

- `requested_symbol`
- `status`
- `error`
- `info`
- `research_report`
- `report_rc`
- `anns_d`
- `news`
- `major_news`
- `derived`

### `info`

- `common`
  - `ts_code`
  - `name`
  - `list_date`
  - `delist_date`
- `cn_specific`
  - `symbol`
  - `exchange`
  - `list_status`
  - `area`
  - `industry`
  - `market`
- `us_specific`
  - `ts_code`
  - `name`
  - `enname`
  - `classify`
  - `list_date`
  - `delist_date`

### 数据块结构

每个数据块固定为：

- `records`
- `source`
- `source_status`
- `source_error`
- `attempted_sources`

扁平 block 示例：

```json
{
  "records": [],
  "source": "tushare",
  "source_status": "empty",
  "source_error": null,
  "attempted_sources": ["tushare"]
}
```

`news` / `major_news` 额外返回：

- `filter_rule`

`research_report` 需要时额外返回：

- `skip_reason`

`report_rc` 需要时额外返回：

- `requested_start_date`
- `requested_end_date`
- `resolved_start_date`
- `resolved_end_date`
- `fallback_mode`

### `source_status`

固定枚举：

- `ok`
- `empty`
- `permission_denied`
- `not_supported`
- `error`

## 状态语义

### Item `status`

- `ok`
  - `research_report` 与 `report_rc` 都成功
- `partial`
  - 核心块成功，但 `anns_d` / `news` / `major_news` 任一不可用
- `failed`
  - 非法 symbol，或任一核心块 `permission_denied` / `error`
- `not_supported`
  - `CN` 下命中 ETF / 基金等非普通股票
- `not_implemented`
  - `US`

### 顶层 `status`

- `ok`
  - 全部 item 为 `ok`
- `partial`
  - 存在 `partial` / `failed` / `not_supported`
- `not_implemented`
  - `market = us`

## Provider 规则

- 当前 provider registry 固定为 `["tushare"]`
- 统一通过 block-level dispatcher 调度
- 按 provider 优先级顺序尝试
- 命中首个可用源后立即短路
- 不做跨源字段合并
- `attempted_sources` 永远返回，即使只有 `["tushare"]`

## 数据块规则

### `research_report`

- 含义：券商研报列表 / 覆盖记录，偏“研报正文索引”
- Tushare 接口：`research_report`
- 按 `ts_code + start_date + end_date` 查询
- 保留 Tushare 原始字段
- 按 `trade_date desc, inst_csname asc, title asc` 排序
- 仅做精确重复行去重

### `report_rc`

- 含义：券商盈利预测与评级记录，偏“预测 / 评级快照”
- Tushare 接口：`report_rc`
- 按 `ts_code + start_date + end_date` 查询
- 保留 Tushare 原始字段
- 按 `report_date desc, quarter desc, org_name asc, report_title asc` 排序
- 仅做精确重复行去重

### `anns_d`

- 含义：上市公司公告流
- Tushare 接口：`anns_d`
- 按 `ts_code + start_date + end_date` 查询
- 保留 Tushare 原始字段
- 按 `ann_date desc, rec_time desc, title asc` 排序

### `news`

- 含义：通用新闻源中命中股票提及过滤后的新闻
- Tushare 接口：`news`
- 固定来源：`cls` / `sina` / `wallstreetcn` / `10jqka`
- 按时间窗拉取后，本地按“股票名或代码命中 `title` / `content`”做确定性提及过滤
- 排序按发布时间倒序

### `major_news`

- 含义：重点媒体 / 长新闻源中命中股票提及过滤后的新闻
- Tushare 接口：`major_news`
- 固定来源：`新浪财经` / `财联社` / `中证网` / `第一财经`
- 按时间窗拉取后，本地按“股票名或代码命中 `title` / `content`”做确定性提及过滤
- 排序按发布时间倒序

## Derived 规则

- `derived` 的含义：系统基于前述原始块做的确定性汇总，不是主观结论

### `coverage_snapshot`

- `report_count`
- `latest_trade_date`
- `institution_count`
- `report_type_distribution`

### `estimate_snapshot`

- `report_count`
- `latest_report_date`
- `latest_records`
- `by_quarter`
- `rating_distribution`

### `catalyst_timeline`

- 合并 `anns_d` / `news` / `major_news`
- 每条事件固定字段：
  - `event_type`
  - `event_time`
  - `title`
  - `source_label`
- 统一按时间倒序

### `change_flags`

- `has_new_report_7d`
- `has_new_estimate_7d`
- `has_new_catalyst_7d`

时间锚点：

- 优先使用请求 `end_date`
- 未传时使用 `computed_at`

## 非目标

- 不输出 thesis / rating / price target / narrative summary
- 不做跨源合并
- 不实现 US 研报策略
- 不改造本地 `SKILL.md`
