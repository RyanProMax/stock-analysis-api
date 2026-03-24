# 当前任务计划

更新时间：2026-03-24

## 当前目标

- 为 `cn_symbols` 扩展当前上市 A 股 ETF 快照，并与现有 A 股股票共存于同一张表
- 在每日首次任意 HTTP 请求时后台触发 `cn_symbols / us_symbols` 刷新检查，且不阻塞当前请求
- 收口 symbols 刷新链路日志语义，明确区分 SQLite 命中、source 内存缓存命中、source 外部拉取与快照刷新完成

## 最近完成项

- 为 `BaseStockDataSource` 新增统一 symbols 拉取日志，明确区分 `symbol source cache hit` 与 `symbol source fetch success`
- 为 `TushareDataSource` 新增 `fetch_cn_etfs()`，通过 `etf_basic` 拉取当前上市 ETF，并标准化为 `market=ETF`
- 将 `SymbolCatalogService.refresh_market_snapshot()` 扩展为 `refresh_market_snapshot_result()`，支持返回 `success`、`source`、`partial`、`reason`
- 将 `cn` 市场 symbols 刷新改为“股票快照 + ETF 快照”合并后统一覆盖写入 `cn_symbols`
- 锁定 `cn` 刷新规则：股票拉取失败则整次刷新失败；ETF 拉取失败仅记为 `partial`，不阻断股票快照刷新
- 为 `resolve_symbol()` 增加 ETF 旁路，避免 ETF 记录误走 A 股股票 metadata 补齐链路
- 新增 `SymbolSnapshotRefreshService`，维护 `cn/us` 各自的 `last_checked_date`、`last_success_at`、`last_error`、`in_flight`
- 在 FastAPI 全局 middleware 接入 symbols preflight；`/health` 与业务接口都会触发，`/docs`、`/redoc`、`/openapi.json` 会跳过
- 每日 preflight 固定后台异步执行，不阻塞当前 HTTP 请求
- A 股开市判断复用 `Tushare trade_cal`；美股开市判断使用 `yfinance` `SPY` best-effort，并允许工作日 fallback
- 新增 `MarketDataRepository.get_symbol_snapshot_meta()`，用于判断今日 symbols 快照是否已是最新
- 保持 `sync-market-data --market cn --scope all` 只同步股票日线，不把 `market=ETF` 记录纳入 `cn_daily` 全市场补库 universe
- 已补充并通过本轮定向测试：`tests/test_symbol_snapshot_refresh.py`、`tests/test_market_data_warehouse.py`

## 当前状态

- HTTP 服务仍是唯一对外协议
- `facts / analysis / meta` 分层仍是当前输出 contract 基线
- symbols 相关代码已基本落地本轮方案，但 `docs/` 与 `AGENTS.md` 仍停留在旧口径，尚未同步到 ETF + 每日 preflight 语义
- `cn_symbols` 已开始支持“当前上市 A 股股票 + ETF”统一快照，ETF 与股票共存于同一张表
- `cn_symbols.market` 当前直接承担类型区分：股票保留原板块值，ETF 统一为 `ETF`
- `SymbolCatalogService.list_symbols()` 与 `search_symbols()` 仍默认优先读取 SQLite；只有冷启动、显式 refresh 或每日 preflight 命中时才会走 source 刷新
- 每日首次请求触发的 symbols preflight 当前为进程内状态，不跨进程共享，也不会持久化到 SQLite
- 每个市场只有在“成功检查”后才会将当天封账；若检查失败或刷新失败，当天后续请求仍允许再次尝试
- A 股开市判断依赖 `Tushare trade_cal`
- 美股开市判断为基于 `SPY` 的 `yfinance` best-effort 策略；当会话信息不可用时会退化为工作日 fallback
- `sync-market-data` 当前仍只覆盖股票日线 universe；ETF 不进入 `cn_daily` 全市场补库
- `/health` 当前仍是唯一健康检查接口，且已纳入“任意 HTTP 请求”范围，会触发后台 symbols preflight

## 下一步计划

### P0

- 统一 `SymbolSnapshotRefreshService` 的 preflight 日志字段，补齐 `market`、`trigger`、`is_open`、`fallback`
- 补充 `/redoc` 跳过、失败不封账、`in_flight` 去重、美股 fallback 成功检查等测试
- 补充 `/stock/list`、`/stock/search` 的 ETF 可见性测试，以及 `/health` 的 middleware 非阻塞测试

### P1

- 更新 `docs/architecture.md`、`docs/api.md`、`docs/specs/local-daily-warehouse.md` 与 `AGENTS.md`
- 完成本轮定向回归并提交 commit

## 已知风险与阻塞

- 美股 symbols preflight 的开市判断仍是 `yfinance` best-effort；当 `SPY` 会话信息不可用时会退化为工作日 fallback，精度低于交易所日历
- symbols preflight 当前是进程内协调状态；多进程部署时每个进程都会独立判断并可能各自触发一次后台刷新
- A 股 ETF 快照当前只扩到 `etf_basic`，不扩展到全部公募基金，也不提供 ETF-only 过滤参数
- `sync-market-data` 当前仍只覆盖股票日线；若未来需要 ETF 日线 canonical 仓，需要单独设计 scope 和数据口径
- 旧兼容导入层仍然存在，后续若要继续收敛，需要逐步清理 `src/core/` / `src/storage/` 的转发用法
