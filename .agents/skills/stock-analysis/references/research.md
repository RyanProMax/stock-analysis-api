# /research Single-Stock Deep Research Workflow

Use this reference for `/research` single-stock deep reports. The goal is an evidence-based research memo for one listed company, not a buy/sell recommendation, system-generated price target, or trading plan. Third-party institutional target prices may be cited only as sourced external views.

## Scope

`/research` covers one primary ticker at a time:

- A-share listed stocks.
- US-listed stocks and ADRs.
- HK-listed stocks only when explicitly requested or when A-share / US routing cannot resolve the target.

Do not use this workflow for `/hkipo` current IPO pool ranking. HK IPO scoring and first-day odds belong to `references/hkipo.md`.

## Market Resolution Priority

Resolve the target before collecting data. A-share and US routes have priority; HK is deliberately lower priority.

| Input pattern | Default market | Notes |
| --- | --- | --- |
| Chinese company / stock name such as `宁德时代` | Agent resolves first | Executor emits an identity-resolution workflow; the agent must verify the unique market and ticker from reliable sources before replacing the CLI template and running it. |
| 6-digit code such as `300827`, `600000` | A-share | Prefer `stock-analysis-api` CLI contracts. |
| `SH.600000`, `SZ.300827`, `BJ.8xxxxx` | A-share | Preserve explicit exchange if provided. |
| US ticker such as `AAPL`, `MSFT`, `TSLA`, `NVDA` | US | Prefer US route unless user mentions HK/A-share listing. |
| Longer bare English company names or nonstandard uppercase inputs such as `MINIMAX` | Agent resolves first | Do not force these into US only because they are uppercase. Verify the unique listing market and standard code; if the only reliable match is HK, switch to the HK route and use the HK title. |
| `US.AAPL`, `NASDAQ:AAPL`, `NYSE:KO` | US | Normalize to the provider's supported symbol format. |
| `HK.00700`, `00700.HK`, `港股 00700` | HK | Use HK route only because the user made HK explicit. |
| Chinese company name with multiple listings | Ask or infer A-share first, US ADR second, HK last | If ambiguity can change the company or listing venue, ask a short clarification. |

Rules:

- Do not route to HK only because a company has an HK listing. Use HK only for explicit HK symbols, explicit user intent, or no credible A-share / US match.
- If the same business has multiple listings, keep the selected listing clear in the report and mention other listings only as context.
- For stock-name inputs, the executor must not hardcode or locally cache-match the ticker. It passes the raw input to the upstream `stock-analysis-api` CLI; upstream resolves identity before analysis and returns structured identity errors when ambiguous or missing.
- If upstream identity resolution returns multiple candidates, stop and ask for the exact code or listing venue; do not guess from popularity alone.
- If the upstream result is a structured failure, read the returned fields before choosing the next route: `data.items[0].status`, `data.items[0].error.code/message`, `data.items[0].info`, `data.items[0].meta.modules`, and `meta.partial_reasons`. Quote, core-module, unsupported-security, or identity failures are evidence to clarify or re-route, not evidence that the requested input is a valid ticker in that market.
- If symbol identity remains uncertain after the upstream CLI result and source checks, stop and ask for the exchange or full ticker.

## Data Source Routing

Choose one primary market route, then add source-specific evidence.

| Market | Primary route | Supporting sources |
| --- | --- | --- |
| A-share | `stock-analysis-api` `stock_analyze.py`; `poll_realtime_quotes.py` for current quote | Exchange / company announcements, CNINFO, annual and quarterly reports, Tushare raw interfaces only when explicitly requested. |
| US | `stock-analysis-api` `stock_analyze.py --market us --mode full` | SEC EDGAR, company IR, 10-K / 10-Q / 8-K, earnings releases, investor presentations, Nasdaq / NYSE pages, Futu/OpenD read-only quote/K-line data when available, reputable finance data for consensus or market snapshot. |
| HK | `stock-analysis-api` `futu_market_data.py` read-only global-state / snapshot / kline with executor OpenD preflight | HKEXnews, company announcements, annual and interim reports, exchange filings, reputable finance portals for secondary market data only after confirmation if OpenD is unavailable. |

For A-share and US reports, the `/research` executor should provide a copy-pasteable absolute command for `stock-analysis-api`. It resolves `STOCK_ANALYSIS_API_ROOT` first, then the monorepo root above `.agents/skills/stock-analysis/`, and finally legacy sibling `stock-analysis-api` directories for compatibility. Explicit tickers and stock-name inputs both use a concrete command; stock-name inputs are passed raw to `--symbols`, and the upstream CLI resolves identity before analysis. Use the generated command exactly; it must contain an absolute API root and an absolute `uv` executable resolved by the executor. Do not replace it with the current workspace, a relative path, a bare `uv`, or an invented `$STOCK_ANALYSIS_API_ROOT` command. If the executor reports a `stock-analysis-api` preflight failure, mark the CLI module unavailable and continue only under the degradation rules below.

For explicit HK reports, the `/research` executor must run a read-only OpenD preflight before emitting an `assistant_prompt`. The preflight uses `stock-analysis-api/scripts/futu_market_data.py global-state --json` through the executor-resolved API root and absolute `uv` path, not the host process Python or any non-API script. If OpenD, the API CLI, or `uv` is unavailable, the executor must return local `final_markdown` asking whether to continue; it must not generate a research prompt and let the agent silently downgrade. Only an explicit user confirmation flag such as `--continue-without-opend` allows the HK report to continue with HKEX / company announcements / AKShare / yfinance as degraded sources. For auto-resolved targets that turn out to be HK, the agent must apply the same gate: if Futu/OpenD cannot be called, stop and ask the user whether to continue before collecting fallback data.

Source priority:

1. Official filings, exchange announcements, company IR, regulator records.
2. Structured local contracts already defined by this skill, especially `stock-analysis-api` for A-share / US standard analysis and the migrated Futu/OpenD `futu_market_data.py` CLI for HK `/research`.
3. Reputable finance portals for market data, analyst consensus, sector comparison, and news only when primary sources do not expose the field.
4. Search snippets, model memory, unverifiable social posts, forum rumors, stale screenshots, and GitHub repos are not evidence sources.

## Execution Phases

1. **Resolve identity**: confirm ticker, exchange, company name, currency, report date, and source timezone. User-facing time defaults to Beijing time.
2. **Collect market snapshot**: latest price, change, market cap if available, volume / turnover, 52-week context or recent trend. Label market status and source time.
3. **Collect primary evidence**: latest annual / quarterly filings, earnings release, guidance, major announcements, risk factors, and segment data.
4. **Cross-check secondary data**: peer valuation, consensus, news, sector indicators, ownership or capital flows if relevant. Always collect industry trend, market heat, peer-average PE, and authoritative research-report summaries with ratings / views and institutional target prices when sources are available.
5. **Build data reliability layer**: fill `module_status`, `source_freshness`, and `data_gaps` before writing conclusions.
6. **Write the memo**: default IM / Feishu output is focus-first. Answer the user's most actionable research questions before technical metadata: financial health, valuation reasonableness, relative industry valuation, market heat, future narrative / growth drivers, and institutional research consensus vs disagreement. Keep every material claim traceable to a source.
7. **Declare degradation**: if any required source is missing, stale, permission-limited, or unavailable, state it in the memo instead of filling gaps.

## Final Reply Hygiene

- 最终回复必须直接从标题开始：第一行必须是 `**/research｜...**`。
- 不得包含执行过程日志、工具调用尝试、思考过程、状态流水、调试细节、异常堆栈，或“我先检查 / 我找到 / 接下来”这类过程性文字。
- Debug details such as internal function names, stack traces, local absolute paths, raw environment probes, and token diagnostics belong only to debugging conversations. In user-facing reports, compress them into understandable degradation reasons.
- If the agent has accumulated process notes before drafting the report, discard those notes from the final answer and keep only the memo body.

## Required Output Structure

Use this shape for full or expanded reports. Keep headings compact and conclusion-first. For IM / Feishu replies, the default is the focus-first short form below; do not expand every full-report section unless the user asks for “详细 / 完整 / 深度 / 展开”.

```markdown
**/research｜{ticker} {company}｜{market}｜YYYY-MM-DD**

**结论摘要**
- 数据状态：ok / partial / degraded / failed；关键来源截至时间。
- 核心观察：1-3 条，只写可被证据支持的事实判断。
- 最大不确定性：1-2 条。

**数据可信度**
- `module_status`：逐项列出 quote / financials / filings / research_report / news / valuation / risk / validation 等模块状态。
- `source_freshness`：逐项列出行情、财报、公告、研报、新闻、历史验证数据的源端时间或截至日期。
- `data_gaps`：列出缺失、过期、冲突、权限不足或只读数据源不可用的字段；不得用推测补齐。

**标的识别**
- 代码 / 交易所 / 公司名 / 币种 / 行业。
- 是否存在多地上市、ADR、ETF 或同名歧义。

**市场快照**
- 最新价格、涨跌幅、成交量 / 成交额、市场状态、数据时间。
- 近期走势只做事实描述，不写交易指令。

**业务与行业**
- 主营业务、收入结构、行业位置、竞争格局。
- 行业周期、政策、需求或技术变化的证据。

**行业趋势与市场热度**
- 行业整体趋势：景气度、供需、政策、技术周期、竞争格局或价格链变化，必须标注来源和截至日期。
- 市场热度：板块表现、成交/资金、新闻/搜索/社媒热度、机构关注度等可得 proxy；区分短期交易热度与中长期基本面趋势。
- 同类公司平均 PE：列出可比公司样本、PE 口径（TTM / forward / 静态）、均值/中位数、是否剔除负 PE 或异常值、数据日期。
- 权威机构研报汇总：汇总券商、评级机构、行业协会、交易所、咨询机构或公司/行业权威报告；列机构名、研报发布日期、评级/观点、机构目标价、核心观点、共识与分歧。不得把单一机构观点当成市场共识，不把评级/目标价写成本系统建议。
- 机构目标价：只作为外部观点披露，必须标注机构、发布日期/更新时间、币种、当前价对比口径和来源；若只能找到二级报道或数据聚合页，必须标注来源限制，不得改写成本系统目标价。

**财务质量**
- 收入、利润、现金流、毛利率 / 费用率、资产负债、资本开支。
- 同比 / 环比变化和源自管理层披露的解释。

**估值上下文**
- 市值、主要倍数、可比公司或历史区间。
- 只说明相对位置和关键假设，不生成本系统目标价；机构目标价只能放在机构观点综合中作为外部观点引用。

**催化剂与验证路径**
- 未来 1-4 个可验证事件：财报、产品、订单、政策、监管、指数、资本动作。
- 每个催化剂写清验证信号和反证信号。

**风险与反证**
- 单票风险：基本面、估值、流动性、监管、财务、治理、地缘或执行风险。
- 组合/持仓风险：仅当用户明确给出组合、watchlist 或只读持仓上下文时，补充集中度、相关性、行业/市场暴露和流动性风险；不新增独立 /risk 指令。
- 反证信号：列出 2-4 个会推翻当前观察的可验证事实，不写交易动作。

**历史验证**
- 只做历史统计：仅当条件、窗口和数据源可复现时输出；否则写“未做历史验证”。
- 必须写清样本数、起止日期、筛选/事件条件、核心指标、基准和限制，例如幸存者偏差、交易成本缺失或样本过小。
- 历史验证不得生成买卖建议、仓位、止盈止损、交易时点或确定性收益判断。

**降级说明**
- 列出缺失模块、不可用来源、过期数据或权限限制。

**Sources**
- 按本文件 Sources 规范列出。
```

## Default Feishu Short Form

For IM / Feishu replies, default to a compact report of 2500-3500 字 unless the user explicitly asks for “详细 / 完整 / 深度 / 展开”.

The short form must be a **focus-first decision dashboard**, not a compressed checklist. The user should be able to capture the key points in the first screen:

- First answer: company financial structure health, current valuation reasonableness, whether the stock looks rich or cheap relative to the industry, current market heat, future narrative / growth points, and authoritative institutional ratings / views, target prices, consensus vs disagreement.
- Put `module_status`, `source_freshness`, and `data_gaps` after the focus sections unless the data state is `failed` or identity is unresolved. Reliability metadata is mandatory, but should not bury the research conclusion.
- Prefer strong section names such as `一句话结论`, `财务结构`, `估值与行业相对位置`, `情绪热度`, `叙事与增长点`, `机构观点综合`, `风险与反证`, `数据可信度`, `降级说明`, `Sources`.
- Avoid broad narrative sections that force the reader to hunt for the point. Each section should directly answer “so what?” with dated evidence.

Required short-form sections:

1. `一句话结论` or `结论摘要`: 1-3 bullets that state the core research answer, not process status.
2. `财务结构`: liquidity, leverage, cash flow, margin quality, inventory / receivables / capex pressure, and whether the structure is healthy or stressed.
3. `估值与行业相对位置`: current market cap / PE / PS / PB or relevant multiples, peer sample, PE basis, mean / median, exclusions for negative or abnormal PE, and whether the stock is relatively rich or cheap.
4. `情绪热度`: price / volume / sector heat / news or search proxy / institution attention, separated from long-term fundamentals.
5. `叙事与增长点`: 2-5 future narratives and their observable verification signals; include反证 signals when a narrative is still early.
6. `机构观点综合`: authoritative broker / rating agency / industry / exchange / consulting reports with institution, report date, rating/view, institutional target price, core point, consensus and disagreement. Do not turn ratings or target prices into advice.
7. `风险与反证`: 3-5 concrete risks and invalidation signals.
8. `数据可信度`: user-readable summary of `module_status`, `source_freshness`, and `data_gaps`; keep it compact unless reliability is the main issue.
9. `降级说明`: concise user-facing degradation reasons; no stack traces or internal function names.
10. `Sources`: 3-8 authoritative sources.

Compress business, industry trend, market snapshot, financials, valuation, catalysts, and historical validation into the focus-first sections by default. Still include concise bullets for 行业整体趋势、市场热度、同类公司平均 PE、权威机构研报汇总. If any of the four modules is unavailable, explicitly state the missing source or limitation in `数据可信度` or `降级说明`. Historical validation may be one line: “未做历史验证：原因...”. Expand the full structure only when requested.

## Data Reliability Contract

- `module_status`: module-level execution state. Use `ok`, `partial`, `degraded`, `failed`, `permission_denied`, `not_supported`, or `not_run`; include a short reason for non-ok modules.
- `source_freshness`: source timestamp or cutoff date for each material data class, including market quote, financial statements, filings, announcements, research reports, news, and historical validation inputs.
- `data_gaps`: explicit missing, stale, conflicting, permission-limited, or unavailable fields. Put unresolved gaps here even if the narrative can continue.
- These fields are mandatory for `/research`; they are credibility metadata, not analysis conclusions. In Feishu short form, render them in Chinese user-facing wording rather than raw engineering dumps.


## Industry Trend And Market Heat

These modules are required unless reliable sources are unavailable; if unavailable, record the gap in `data_gaps` and `降级说明`.

- 行业整体趋势: describe current industry direction with dated evidence, including demand/supply, policy, technology cycle, pricing, inventory, competitive structure, or regulatory changes when relevant.
- 市场热度: use available proxies such as sector/index performance, turnover, fund flows, news volume, search/social attention, broker coverage, and announcement intensity. Distinguish short-term heat from fundamental trend.
- 同类公司平均 PE: define peer selection, PE basis (TTM / forward / static), mean and median when possible, exclusions for negative or extreme PE, and data date. If peers are not comparable, explain why instead of forcing an average.
- 权威机构研报汇总: summarize authoritative reports from brokers, rating agencies, industry associations, exchanges, consulting firms, or recognized research providers. Include institution, report date, rating/view, institutional target price, core points, consensus, disagreement, and limitations. Do not treat one report as consensus, and do not present ratings or target prices as investment advice.
- 机构目标价: cite only sourced third-party target prices, with institution, publication/update date, currency, current-price comparison basis, and source limitations. If no reliable source is available, state `未找到可靠机构目标价来源` in `data_gaps` / `降级说明` instead of omitting the field. 机构目标价不得作为本系统建议、交易指令或预期结果。


## Analysis Rules

- State what the data says before interpreting why it matters.
- Separate long-term business quality from short-term price action.
- For A-share reports, consume `stock_analyze.py` summary fields first when available, then supplement with filings and current web evidence.
- For US reports, filings and company IR are the anchor. Quote / chart data is context, not the main evidence.
- For HK reports, do not reuse IPO first-day scoring. Treat listed HK stocks as normal single-stock research.
- If valuation is requested, use ranges, peer context, historical multiples, and explicit assumptions. Do not convert your own analysis into a target price or trade instruction; third-party institutional target prices belong only in `机构观点综合` as sourced external views.
- If the user asks "能不能买", answer with factual pros / cons, suitability caveats, and follow-up checks; do not provide a buy/sell/hold call.

## Risk and Historical Validation Contract

- Risk assessment belongs inside `/research`; do not create or ask for an independent `/risk` command.
- For a single stock, write risk as “风险与反证”: risks already visible in evidence, forward-looking risks to monitor, and facts that would invalidate the current observation.
- For portfolio/watchlist/holding questions, use the same `/research` constraints and only read allowed data. Mention concentration, correlation, sector/market exposure, volatility, drawdown, liquidity, and data gaps; do not advise rebalancing or orders.
- Historical validation is optional and evidence-only. It must include sample size, time window, reproducible condition, metric definitions, benchmark when applicable, and limitations.
- If reproducible data is unavailable, write “未做历史验证” and explain the missing data instead of inventing a backtest.


## Degradation Contract

Use a visible status in the report:

- `ok`: required identity, market snapshot, primary filings, and key financial facts are available.
- `partial`: core report is useful, but one or more secondary modules are missing.
- `degraded`: primary evidence or current market data is missing, stale, permission-denied, or conflicting.
- `failed`: ticker identity cannot be resolved or no reliable source can support the report.

Common degradation reasons:

- `identity_conflict`: multiple tickers or listings could match the request.
- `identity_not_found`: no reliable ticker or listing match can support the request.
- `market_data_unavailable`: quote source failed or market source is down. For explicit HK reports, OpenD unavailability is a blocking preflight failure until the user confirms `--continue-without-opend`.
- `primary_filing_missing`: latest annual / quarterly filing cannot be found.
- `permission_denied`: data provider requires entitlement or login not available.
- `stale_data`: latest source is older than the report context requires.
- `unsupported_market`: requested market is outside A-share / US / HK scope.
- `source_conflict`: two credible sources disagree materially; show both and avoid overclaiming.

When degraded:

- Keep the report if enough evidence remains for a useful factual memo.
- Put missing or unreliable items in `降级说明`.
- Never fabricate current prices, financial values, filing dates, analyst views, or management statements.
- Do not hide failed modules just because the final narrative still reads smoothly.
- Do not expose stack traces, internal function names, or verbose local environment probes in the user-facing report; summarize them as source or module failures.

## Forbidden Output

Do not output or imply:

- Buy / sell / hold recommendations.
- System-generated target prices, stop-losses, take-profit levels, position sizing, allocation advice, or exact trade timing.
- Unsourced target prices, or wording that presents an institutional target price as this system's own target, advice, or expected outcome.
- `recommendation`, `confidence`, `price_target`, `conviction`, `thesis` as formal fields.
- Guarantees about returns, "确定", "必涨", "稳赚", or similar certainty language.
- Unverified rumors, social-media claims, search snippets, model memory, or stale cached data as facts.
- Any write action: orders, order changes, cancellation, subscription, watchlist edits, alerts, exports, config changes, or local file writes.
- Account, position, or order details unless the user explicitly asked for a read-only account/portfolio check and the source is allowed by `references/futu.md`.

## Sources Section Rules

The final report must include `Sources` unless the task failed before any reliable source was found.

Format each source as a short bullet:

```markdown
- [Source title](url) — publisher, publication/update date, accessed YYYY-MM-DD, purpose.
```

Rules:

- Put primary sources first, then market data providers, then reputable secondary sources.
- Include source date and accessed date for all web sources.
- For local CLI / tool output, cite the command or tool name, request parameters, and `computed_at` / source time instead of a URL.
- Use a source only for the claim it actually supports. Do not cite an annual report for current price or a finance portal for audited financials unless no better source exists and the limitation is stated.
- If a source is not current enough for market data or recent catalysts, label it `历史参考` or exclude it from current-state claims.
- If sources conflict, keep both in Sources and describe the conflict in `降级说明`.
- Keep Sources concise: prefer the most authoritative 5-10 sources for a full memo, fewer for a short memo.
