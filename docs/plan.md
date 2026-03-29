# 当前任务计划

更新时间：2026-03-29

## 当前目标

- 将 skill / agent 标准化 CLI 能力彻底收口到 `stock-analysis-api`
- 新增内部 `poll_realtime_quotes` CLI，承接原 `stock-analysis-skill` 中的 A 股 / ETF 日内行情轮询逻辑
- 保持 `scripts/stock_analyze.py` 继续作为唯一客观分析 CLI，不改公共 HTTP API

## 最近完成项

- 已保留并稳定运行：
  - `POST /stock/analyze`
  - `POST /watch/poll`
  - `scripts/stock_analyze.py`
- 已确认公共 HTTP API 不需要为本次 skill 对接新增路由
- 已新增内部：
  - `src/services/realtime_quote_polling_service.py`
  - `src/services/realtime_quote_polling_cli.py`
  - `scripts/poll_realtime_quotes.py`
- 已为新 CLI 补充首批 contract 测试，覆盖普通股票、ETF、invalid symbol、legacy realtime 降级与纯 JSON stdout

## 当前状态

- 公共对外协议仍然只有 HTTP REST API
- skill / agent 可消费的内部 CLI 当前为：
  - `scripts/stock_analyze.py`
  - `scripts/poll_realtime_quotes.py`
- `scripts/poll_realtime_quotes.py` 当前 contract 固定为轻量 quote payload：
  - `status / computed_at / source / request / summary / items`
- `scripts/poll_realtime_quotes.py` 当前实现固定为 Tushare-only：
  - 身份信息：`stock_basic / etf_basic`
  - 实时行情：`quotation`
  - 降级：旧版 `get_realtime_quotes`
- 当前仍待完成：
  - `docs/architecture.md` / `docs/specs/` 的内部 CLI 规格补齐
  - cross-repo `stock-analysis-skill` 文档与命名收口
  - 端到端验证与双仓提交

## 下一步计划

- 更新 `docs/architecture.md`，明确 `poll_realtime_quotes.py` 是内部 CLI，不属于公共 API
- 新增 `docs/specs/skill-cli-contract.md`，统一记录 `poll_realtime_quotes.py` 与 `stock_analyze.py` 的输入、输出与状态语义
- 完成 `stock-analysis-skill` 仓库重构：
  - 删除本地 wrapper
  - 文档改名为 `stock-analysis-skill`
  - 直接通过 `STOCK_ANALYSIS_API_ROOT` 消费本仓库 CLI
- 运行 API / skill 两仓验证并分别提交 commit

## 已知风险与阻塞

- Tushare `quotation` 可能受源端权限或可用性影响，因此 legacy realtime 降级语义必须保持真实，不得伪装成完整 realtime
- `TushareDataSource.get_pro()` 当前仍可能打印初始化信息；CLI 层必须继续保证 stdout 纯 JSON
- `stock-analysis-skill` 将不再保留本地 wrapper，文档必须明确调用入口在 API 仓库，避免使用方继续假设 skill 根目录存在同名脚本
