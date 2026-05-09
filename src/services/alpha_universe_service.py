from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

from ..repositories import MarketDataRepository, market_data_repository


@dataclass(frozen=True)
class AlphaUniverse:
    universe_id: str
    market: str
    symbols: list[dict]


class AlphaUniverseService:
    def __init__(self, repository: Optional[MarketDataRepository] = None):
        self.repository = repository or market_data_repository

    def parse_symbols(self, raw: str | Sequence[str] | None) -> list[str]:
        if raw is None:
            return []
        if isinstance(raw, str):
            parts = raw.split(",")
        else:
            parts = list(raw)
        return [str(part).strip().upper() for part in parts if str(part).strip()]

    def build_universe(
        self,
        *,
        market: str = "cn",
        universe: str = "all",
        symbols: str | Sequence[str] | None = None,
        limit: int | None = None,
    ) -> AlphaUniverse:
        normalized_market = str(market or "cn").strip().lower()
        normalized_universe = str(universe or "all").strip().lower()
        requested_symbols = self.parse_symbols(symbols)
        if requested_symbols:
            rows = [
                self.repository.get_symbol_record(symbol, market=normalized_market)
                or {"symbol": symbol, "market": normalized_market.upper()}
                for symbol in requested_symbols
            ]
        elif normalized_universe == "watchlist":
            rows = []
        else:
            rows = self.repository.list_symbols(market=normalized_market)

        filtered = [row for row in rows if self._matches_universe(row, normalized_universe)]
        if limit is not None and limit > 0:
            filtered = filtered[:limit]

        return AlphaUniverse(
            universe_id=f"{normalized_market}-{normalized_universe}",
            market=normalized_market,
            symbols=filtered,
        )

    def _matches_universe(self, row: dict, universe: str) -> bool:
        if universe in ("all", "watchlist"):
            return True
        is_etf = str(row.get("market") or "").strip().upper() == "ETF"
        if universe == "etf":
            return is_etf
        if universe == "stock":
            return not is_etf
        return True
