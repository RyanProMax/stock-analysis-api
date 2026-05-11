from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from ..repositories import MarketDataRepository, market_data_repository
from .alpha_universe_seed_service import AlphaUniverseSeedService


class AlphaUniverseSeedStatusService:
    def __init__(
        self,
        *,
        repository: Optional[MarketDataRepository] = None,
        seed_service: Optional[AlphaUniverseSeedService] = None,
    ):
        self.repository = repository or market_data_repository
        self.seed_service = seed_service or AlphaUniverseSeedService()

    def inspect(
        self,
        *,
        seed_id: str,
        market: Optional[str] = None,
        seed_file: str | Path | None = None,
        start_date: Optional[str] = None,
        stale_before: Optional[str] = None,
    ) -> dict:
        seed_service = AlphaUniverseSeedService(seed_file) if seed_file else self.seed_service
        seed = seed_service.get_seed(seed_id, market=market)
        symbols = list(seed["symbols"])
        date_ranges = self.repository.get_symbol_date_ranges(seed["market"], symbols=symbols)
        effective_start_date = self._resolve_effective_start_date(
            seed["market"], symbols=symbols, start_date=start_date
        )

        items = []
        counts = {
            "total": len(symbols),
            "ok": 0,
            "missing": 0,
            "incomplete": 0,
            "stale": 0,
            "needs_sync": 0,
        }
        for symbol in symbols:
            symbol_range = date_ranges.get(symbol)
            item = self._build_item(
                symbol=symbol,
                symbol_range=symbol_range,
                start_date=effective_start_date,
                stale_before=stale_before,
            )
            items.append(item)
            counts[item["bucket"]] += 1
            if item["needs_sync"]:
                counts["needs_sync"] += 1

        return {
            "status": "ok" if counts["needs_sync"] == 0 else "needs_sync",
            "source": "alpha_universe_seed_status",
            "computed_at": datetime.now(timezone.utc).isoformat(),
            "request": {
                "seed_id": seed_id,
                "market": seed["market"],
                "start_date": start_date,
                "effective_start_date": effective_start_date,
                "stale_before": stale_before,
            },
            "seed": seed,
            "summary": counts,
            "items": items,
            "constraints": [
                "read_only_local_warehouse",
                "seed_not_strategy_config",
                "no_broker_or_order_side_effects",
            ],
        }

    def _resolve_effective_start_date(
        self,
        market: str,
        *,
        symbols: list[str],
        start_date: Optional[str],
    ) -> Optional[str]:
        if not start_date:
            return None
        first_available = self.repository.get_first_available_trade_date(
            market,
            on_or_after=start_date,
            symbols=symbols,
        )
        if first_available and first_available > start_date:
            return first_available
        return start_date

    def _build_item(
        self,
        *,
        symbol: str,
        symbol_range: Optional[dict],
        start_date: Optional[str],
        stale_before: Optional[str],
    ) -> dict:
        if symbol_range is None:
            return self._item(
                symbol=symbol,
                status="missing_daily_history",
                bucket="missing",
                needs_sync=True,
                data_gaps=["missing_daily_history"],
            )

        min_trade_date = symbol_range.get("min_trade_date")
        max_trade_date = symbol_range.get("max_trade_date")
        row_count = int(symbol_range.get("row_count") or 0)
        data_gaps: list[str] = []
        status = "ok"
        bucket = "ok"

        if start_date and (min_trade_date is None or min_trade_date > start_date):
            status = "incomplete_history"
            bucket = "incomplete"
            data_gaps.append("history_starts_after_requested_start")
        elif stale_before and (max_trade_date is None or max_trade_date < stale_before):
            status = "stale"
            bucket = "stale"
            data_gaps.append("daily_history_stale")

        return self._item(
            symbol=symbol,
            status=status,
            bucket=bucket,
            needs_sync=status != "ok",
            data_gaps=data_gaps,
            daily_start_date=min_trade_date,
            daily_end_date=max_trade_date,
            row_count=row_count,
        )

    @staticmethod
    def _item(
        *,
        symbol: str,
        status: str,
        bucket: str,
        needs_sync: bool,
        data_gaps: list[str],
        daily_start_date: Optional[str] = None,
        daily_end_date: Optional[str] = None,
        row_count: int = 0,
    ) -> dict:
        return {
            "symbol": symbol,
            "status": status,
            "bucket": bucket,
            "needs_sync": needs_sync,
            "daily_start_date": daily_start_date,
            "daily_end_date": daily_end_date,
            "row_count": row_count,
            "data_gaps": data_gaps,
        }
