# HK IPO Research Workflow

Use this reference only for `/hkipo` reports. The goal is a concise, evidence-based IPO pool ranking, not a long investment memo.

## Lessons Borrowed from Open Skills

- Prefer executable workflows and clear phases: discover → verify → score → rank → report.
- Use explicit weighted scoring, like market-breadth skills, so outputs are repeatable.
- Validate ideas with historical cases, like backtest-focused skills; do not rely on narrative conviction.
- Keep the main skill short and move scoring/rubrics into this reference for progressive disclosure.

## Scope

By default, discover current Hong Kong IPOs that are:

1. currently open for subscription.

Filter out IPOs where Futu/OpenD reports `is_subscribe_status=false` by default,
even if the listing date has not arrived yet. Include subscription-closed but
not-yet-listed IPOs only when the user explicitly passes `/hkipo --all`.

If none qualify, state: `当前无符合条件的港股 IPO 池`.

## Source Priority

Current IPO reports must separate **current-state discovery** from **document evidence** and **secondary market heat**.

1. `stock-analysis-api/scripts/futu_market_data.py ipo-list --market HK --json` is the first source for the current IPO pool, subscription status, listing date, apply end date, offer price, lot size and entrance price. Use it before web finance portals whenever OpenD is available.
2. HKEX official listing documents, prospectus, allotment results, listing-date notices and company announcements are the first source for prospectus facts, offering structure, greenshoe, stabilizing manager, cornerstone investors, sponsors and proceeds use.
3. Reliable finance portals and broker pages are fallback/secondary sources only for fields Futu/OpenD and HKEX do not expose: margin financing, public-offer multiple, one-lot success rate, grey-market data and first-day performance. Use a fixed source order for these heat fields: Futu/OpenD current fields and Futu App / Niuniu heat if available → same-day multi-broker aggregate sources → same-day broker IPO center / margin table → same-day finance portal IPO channel public-offer multiple / one-lot success rate → grey-market data.
4. Never use GitHub repos, model outputs, stale cached snippets, or unverifiable social posts as IPO fact sources.

### Freshness Gate

- Always evaluate sources against the report date. If the user gives a date, use that date; otherwise use today's actual date and state it explicitly.
- Margin financing, public-offer multiple, one-lot success rate and grey-market return are time-sensitive. For an IPO still open for subscription or in the grey-market/listing window, apply a same-day hard gate before scoring heat.
- The same-day hard gate requires searching by stock code plus Chinese and English names, then retrying and expanding across at least three authoritative source families before concluding data is unavailable: broker IPO centers / margin tables, major finance IPO channels, and mainstream quote-app IPO pages or official HKEX / company timetable pages. Typical sources include Futu/Niuniu, Phillip POEMS, HSTong, Tiger, AAStocks, ETNet, Sina HK / Zhitong and Gelonghui.
- Same-day heat means a source timestamp or update label on the report date in Hong Kong / Beijing time. If a later same-day source exists, use it. If sources disagree, use the latest timestamp no later than the report date and cite the conflict when useful.
- For open IPOs, do not score previous-day or older margin data, public-offer data, one-lot success rates or grey-market data in Subscription Heat. They may only be shown as `过期/仅供趋势参考`.
- If a newer source exists, older margin or grey-market values must not be used in the score. They may only be shown as historical trend, with the source date clearly labeled.
- If no same-day heat source is found after the retry / expanded-source pass, write `热度未达当日核验门槛` and cap the Subscription Heat contribution as missing current heat; do not fill the main heat field with the previous available value.
- The Sources section must label each secondary source with its publication/update date and purpose, e.g. `2026-04-27 孖展统计`.

### Latest Heat Aggregation

- For open subscriptions, do not stop at one broker. If Futu/OpenD CLI does not expose the Futu App / Niuniu IPO heat field, explicitly search Futu App / Niuniu pages or related Futu content before concluding Futu heat is unavailable.
- Search and compare multiple authoritative institutions every time: Futu App / Niuniu, TradeGo / 活报告 aggregate margin data, same-day `新股孖展统计` from Zhitong / Sina or Gelonghui, AAStocks / ETNet IPO pages, and broker IPO centers or margin tables such as Phillip POEMS, HSTong, Tiger, Bright Smart, Chief, KGI, Livermore and other named underwriters.
- Always prefer same-day multi-broker aggregate sources over a single broker. A single-broker lower bound, such as one broker's margin quota or client financing amount, must not be treated as market-wide heat and must not replace a fresher Futu App or multi-broker aggregate value.
- If several same-day values conflict, choose the latest timestamped value no later than the report date, and prefer a clearly market-wide aggregate over an institution-specific number at the same timestamp. Keep the older or narrower number only as `单一券商下限/趋势参考`.
- Do not finalize a normal heat score for an open IPO until the source search has covered the required families. If current heat still cannot be found, the report must say `热度未达当日核验门槛` and the score must reflect missing current heat rather than a stale or single-source substitute.

## Required Data Fields

For each IPO, collect only decision-useful fields:

- identity: code, company, sector, issuer type, stage
- calendar: subscription dates, pricing/allotment/listing dates
- deal: offer price/range, market cap, shares offered, public/international split
- structure: sponsors, cornerstone investors, greenshoe / over-allotment option, stabilizing manager, lock-up where relevant
- fundamentals: revenue, profit/loss, cash flow or cash burn, commercialization stage, top customers/orders, R&D and customer concentration
- valuation: implied market cap/multiple, closest public peers, obvious premium/discount
- sentiment/odds: public-offer multiple, margin heat, international placing language, callback, one-lot success rate if available
- backtest context: recent listed HK IPO first-day performance and similar-deal outcomes

Use `未披露` or `未找到可靠来源` for missing fields.

## Weighted Scorecard

Score each IPO from 0 to 100 as a short-term HK IPO subscription / first-day odds score, not a long-term investment rating. Show the total and compact dimension scores in the overview table.

| Dimension | Weight | What to Evaluate |
|---|---:|---|
| Subscription Heat | 30 | margin financing multiple, public-offer multiple, order-book/placing language, callback, one-lot success rate, grey-market signal if available |
| Deal Structure | 20 | greenshoe, stabilizing manager, cornerstone quality/size, public float, sponsor quality, lock-up, shareholder overhang |
| Backtest Fit | 20 | recent HK IPO first-day win rate, median first-day return, sector/theme match, whether similar deals with similar heat worked |
| Fundamentals | 15 | revenue scale/growth, profitability, cash burn, commercialization, customer concentration |
| Valuation | 10 | valuation vs peers, valuation vs growth quality, downside from aggressive pricing |
| Evidence Quality | 5 | official-source completeness and freshness, cross-source consistency |

### Heat / Financing Tiers

Use margin financing multiple and public-offer multiple as core heat inputs. If sources conflict, cite the range and use the freshest same-day source that is no later than the report date. Do not score previous-day or older margin data when the IPO is still open for subscription.

- margin financing `<10x`: weak heat, usually cap Subscription Heat at 10/30 unless first-day backtest is unusually strong.
- `10-50x`: normal heat, usually 10-16/30.
- `50-200x`: strong heat, usually 16-22/30.
- `200-1000x`: very strong heat, usually 22-26/30.
- `>1000x`: extreme heat, usually 26-30/30; check allocation odds and overpricing risk.
- grey-market `>100%`: treat as a late-stage positive signal; `>250%` usually lifts total score into `90+` unless evidence is unreliable or structure has major selling pressure.

### Phase-Sensitive Score Updates

Update the score as the IPO window advances:

1. **招股中**: rely on fundamentals, valuation, deal structure, margin financing progress, and recent backtest fit.
2. **截止待配发**: add public-offer multiple, international placing language, callback, one-lot success rate.
3. **暗盘后待上市**: grey-market return becomes the strongest near-term signal; explain whether first-day score is upgraded or whether dark-pool overheating raises reversal risk.

If an IPO has verified margin financing above 1000x and verified grey-market gain of 300%-400%, the old scoring that puts it only in the high-70s is too conservative for first-day odds. It should normally be `90-95` for打新/首日优先级, while still flagging long-term fundamental risk separately.

### Scoring Rules

- `90-100`: 极高优先级 — extreme heat / grey-market confirmation / supportive structure; still disclose reversal risk.
- `80-89`: strong watch — strong combined setup, but one key uncertainty remains.
- `65-79`: 可观察/可小仓博弈 — has a clear edge but at least one material weakness.
- `50-64`: 中性 — facts are mixed or valuation/odds are not attractive enough.
- `<50`: 谨慎/回避 — poor odds, weak fundamentals, stretched valuation, or unreliable evidence.

Do not call the score a buy/sell recommendation. Phrase it as `打新优先级` or `首日赔率评分`. Keep long-term quality separate from first-day odds.

## Greenshoe / Stabilization Checks

For every IPO, explicitly check:

- whether an over-allotment option / greenshoe exists;
- maximum over-allotment size if disclosed;
- stabilizing manager if disclosed;
- whether lack of greenshoe weakens early aftermarket support;
- whether the deal has cornerstone investors and their approximate share of offering/market cap.

Score effect:

- confirmed greenshoe + credible stabilizing manager: positive Deal Structure factor;
- no greenshoe or not disclosed: neutral-to-negative unless sentiment/float structure compensates;
- cornerstone is not automatically positive: assess quality, lock-up, and whether valuation still leaves upside.

## Backtest Calibration

### Automated Backtest

Run this command before or during `/hkipo` calibration when network access is available:

```bash
python3 scripts/hkipo_backtest.py --limit 100 --source aastocks --format markdown
```

The script uses AAStocks Listed IPO fields: listing date, offer/listing price, market-cap range, public over-subscription rate, applied lots for one lot, one-lot success rate, last price, first-day return and accumulated return. When OpenD is logged in, use Futu historical daily K-line to recompute first-day close returns:

```bash
python3 scripts/hkipo_backtest.py --limit 100 --source aastocks --enrichment-source xinguyufu --debut-price-source futu-kline --api-root "$STOCK_ANALYSIS_API_ROOT" --uv "$STOCK_ANALYSIS_UV" --format markdown
```

AAStocks still provides the recent listed IPO sample list and offer price. The API Futu CLI `ipo-list --market HK` covers current IPOs only; it is not a recent-100 listed IPO history source and does not provide historical greenshoe, cornerstone or grey-market fields. Use `--enrichment-source xinguyufu` to fetch public Xinguyufu API rows by stock code for greenshoe, cornerstone, grey-market, sponsor and stabilizer fields. This follows the open-source AKShare-style pattern of requesting public financial web pages / JSON with a browser user-agent and mapping fields explicitly.

The report includes total win rate, average/median first-day return, break rate, heat buckets, score buckets, industry buckets, valuation/market-cap buckets, score/return correlation, score rank correlation, top-vs-bottom score quintile spread, and high-score loser / low-score winner mismatch samples.

Industry is inferred heuristically from the company name by default unless enrichment supplies an industry field. Greenshoe, cornerstone and grey-market fields are also supported through an optional enrichment CSV:

```bash
python3 scripts/hkipo_backtest.py --limit 100 --enrichment-csv data/hkipo_enrichment.csv
```

CSV optional columns: `code,industry,greenshoe,cornerstone,grey_market_return_pct`. Missing greenshoe/cornerstone/grey-market fields are treated as neutral and reported as missing coverage. Use this tool to calibrate heat/odds weights and inspect score reasonableness, not as a complete scoring replacement.


Before ranking current IPOs, collect a small recent sample of already listed HK IPOs, ideally 5-10 names from the last 1-3 months or the same sector/deal type.

For each sample, capture:

- code/company, listing date, offer price, first-day close or first-day return;
- public-offer multiple / one-lot success rate if available;
- greenshoe / cornerstone status if available;
- sector/deal type similarity.

Summarize only:

- sample size;
- first-day win rate;
- median first-day return;
- observed pattern: e.g. high subscription + greenshoe + reasonable valuation worked better/worse;
- limitations: small sample, missing grey-market data, sector mismatch.

If reliable recent first-day data cannot be found quickly, do not invent it; set Backtest Fit to neutral and say why.

## Concise Output Contract

Use this final report body shape by default. Do **not** include separate per-name narrative sections; integrate dimension details into compact per-name blocks.

Keep the report terse:

- Do not explain trigger text, date mismatches, collection steps, or scoring derivation.
- Put per-IPO content into compact per-name blocks, including Futu field coverage, external heat data, backtest mapping, structure, valuation and risk.
- Do not add a separate backtest section unless the user explicitly asks for details; the block's `回测` line is enough.
- Outside the IPO blocks, only keep 1-3 conclusion bullets and compact sources.
- Avoid wide Markdown tables; use compact per-name blocks to keep the report body readable on narrow chat surfaces.
- Avoid Markdown headings (`#`, `##`). Use bold labels and a short divider instead.
- Each ranked IPO title must end with the subscription deadline and allotment/result date, not an investment suggestion or priority label: `M/D截止 | M/D开奖`.
- Do not insert blank empty lines. Keep top-level labels, bullets, IPO title lines and per-IPO small fields separated by single newlines only.
- Keep `📍 阶段`, `💰 热度`, `🛡 结构`, `📈 回测`, and `⚠️ 风险` compact and consecutive.
- Use fixed emoji cues sparingly: 🟢 highest in pool, 🟡 watch, ⚪ observe; 💰 heat, 🛡 structure, 📈 backtest, ⚠️ risk, 🔗 sources.
- Heat numbers must follow the fixed source order in `Source Priority`; every margin/public-subscription/grey-market value needs a source timestamp or explicit stale-data note.

```markdown
**港股 IPO 池｜YYYY-MM-DD**
----
**💡 关键结论**
- 🟢 highest priority: code + one reason.
- 🟡 watch: code + one reason.
- ⚪ observe/cautious: code + one reason.
**📌 优先级**
**🟢 1｜代码 公司｜评分｜M/D截止 | M/D开奖**
📍 阶段：招股/截止/暗盘/上市日；Futu：发售价/一手/入场费/状态
💰 热度：最新孖展/公开认购/暗盘，标注日期和是否外部补充
🛡 结构：绿鞋/基石/保荐/回拨
📈 回测：对应热度分桶和首日赔率映射
⚠️ 风险：一句话最大风险
**🔗 来源**
- Key links only; max 2-3 markdown links per IPO/sample; label purpose and date.
```

Keep the whole report concise. Avoid long company introductions. Do not repeat the same fact in multiple sections.
