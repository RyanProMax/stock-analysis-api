# HKIPO Official Docs CLI

`scripts/hkipo_official_docs.py` 是内部 agent / workflow 使用的只读数据源文件解析入口，不属于公共 HTTP API。它接收 Futu/OpenD 已发现的港股 IPO 池，定位 HKEX 官方公告和招股书文件，下载并解析正文，输出可审计的结构化 evidence。

定位顺序：

- 先尝试 HKEX `titlesearch.xhtml` / `titleSearchServlet.do` 同族标题搜索页面。
- 若标题搜索首屏无静态结果，则回退解析 HKEX “新上市资料” Main Board / GEM 表格，按 IPO 代码或公司中文名匹配当前行，并读取“新上市公告 / 招股章程 / 股份配發結果”下载链接。
- 两类官方来源都不可用时，按 source-level error 降级，不把网页猜测当官方证据。

PDF 正文抽取优先使用 `PyMuPDF`，并以 `pypdf` 兜底；抽取阶段必须抑制原生 PDF 库直接写入 stdout/stderr 的诊断，保证 CLI stdout 始终是严格 JSON。

## Usage

```bash
uv run python scripts/hkipo_official_docs.py \
  --date 2026-05-17 \
  --ipos-json /path/to/ipos.json \
  --cache-dir ~/.cli-claw/cache/hkipo-official-docs \
  --json
```

`--ipos-json` 可以是 IPO 数组，也可以是 `{ "data": [...] }`。`--include-closed` 允许处理已截止但未上市 IPO。`--cache-dir` 由调用方传入共享 cache namespace；CLI 可以缓存可重建下载文件，但输出 artifact 不能依赖 cache 文件永久存在。

## Output Contract

顶层字段：

- `status`: `ok` 或 `error`
- `source`: 固定为 `hkipo_official_docs`
- `report_date`: 报告日期
- `summary.ipo_count`
- `summary.parsed_document_count`
- `summary.degraded_count`
- `data[]`
- `errors[]`

每个 `data[]`：

- `code`
- `name`
- `stage`
- `status`: `official_docs_parsed` / `official_docs_degraded` / `official_docs_not_found`
- `query_plan[]`: HKEX 搜索 URL
- `documents[]`: 已定位并读取的文件元数据，只保存 `title`、`document_type`、`published_at`、`url`、`sha256`、`bytes`、`parsed_text_chars`
- `structure_evidence[]`
- `valuation_evidence[]`
- `source_errors[]`

`documents[].document_type` 当前支持：

- `listing_announcement`
- `prospectus`
- `allotment_result`
- `stabilization`
- `pricing`

`structure_evidence[]` / `valuation_evidence[]` 使用与 `hkipo_heat_scan` 相同的归因字段：

- `source`
- `source_family`
- `field`
- `value`
- `unit`
- `published_at` 或 `updated_at`
- `url`
- `confidence`
- `staleness_status`
- `snippet`

当前字段覆盖：

- 发行结构：`greenshoe_pct`、`stabilizing_manager`、`cornerstone_investor_count`、`cornerstone_offer_pct`、`sponsor`、`public_float_pct`、`clawback_max_pct`
- 估值/基本面：`offer_market_cap`、`use_of_proceeds`、`core_business`

## Failure Policy

- HKEX 搜索页、文件下载或 PDF 解析失败时，写入 `source_errors[]`，单只 IPO 降级为 `official_docs_degraded`。
- 不把招股书或网页全文写入输出 artifact。
- 不登录券商、不绕过验证码/付费/反爬限制。
- 无法定位或无法解析时只输出降级原因，不编造绿鞋、基石、回拨、估值字段。
