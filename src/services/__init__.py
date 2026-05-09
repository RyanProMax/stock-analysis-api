"""业务服务层。

Package import must stay side-effect free. Internal CLIs such as
``scripts/futu_market_data.py`` import ``src.services.futu_market_data_cli`` and
must not initialize unrelated repositories just because the package loaded.
"""

from importlib import import_module
from typing import Any

_EXPORT_MODULES = {
    "DailyDataReadService": "daily_data_read_service",
    "daily_data_read_service": "daily_data_read_service",
    "DailyDataWriteService": "daily_data_write_service",
    "daily_data_write_service": "daily_data_write_service",
    "SymbolCatalogService": "symbol_catalog_service",
    "symbol_catalog_service": "symbol_catalog_service",
    "SymbolSnapshotRefreshService": "symbol_snapshot_refresh_service",
    "symbol_snapshot_refresh_service": "symbol_snapshot_refresh_service",
    "WatchPollingService": "watch_polling_service",
    "watch_polling_service": "watch_polling_service",
    "StockAnalyzeService": "stock_analyze_service",
    "stock_analyze_service": "stock_analyze_service",
    "RealtimeQuotePollingService": "realtime_quote_polling_service",
    "realtime_quote_polling_service": "realtime_quote_polling_service",
    "AlphaScanService": "alpha_scan_service",
    "AlphaEvaluationService": "alpha_evaluation_service",
    "StrategyRegistryService": "strategy_registry_service",
    "AlphaDailyReportService": "alpha_daily_report_service",
    "WatchWorkerService": "watch_worker_service",
    "StrategyJudgeService": "strategy_judge_service",
}

__all__ = [
    "DailyDataReadService",
    "daily_data_read_service",
    "DailyDataWriteService",
    "daily_data_write_service",
    "SymbolCatalogService",
    "symbol_catalog_service",
    "SymbolSnapshotRefreshService",
    "symbol_snapshot_refresh_service",
    "WatchPollingService",
    "watch_polling_service",
    "StockAnalyzeService",
    "stock_analyze_service",
    "RealtimeQuotePollingService",
    "realtime_quote_polling_service",
    "AlphaScanService",
    "AlphaEvaluationService",
    "StrategyRegistryService",
    "AlphaDailyReportService",
    "WatchWorkerService",
    "StrategyJudgeService",
]


def __getattr__(name: str) -> Any:
    module_name = _EXPORT_MODULES.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = import_module(f"{__name__}.{module_name}")
    value = getattr(module, name)
    globals()[name] = value
    return value
