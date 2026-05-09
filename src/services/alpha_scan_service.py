from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, Sequence

from ..model.alpha import AlphaCandidate
from ..model.serialization import json_safe
from ..repositories import MarketDataRepository, market_data_repository
from .alpha_feature_service import AlphaFeatureService
from .alpha_universe_service import AlphaUniverseService


class AlphaScanService:
    def __init__(
        self,
        repository: Optional[MarketDataRepository] = None,
        universe_service: Optional[AlphaUniverseService] = None,
        feature_service: Optional[AlphaFeatureService] = None,
    ):
        self.repository = repository or market_data_repository
        self.universe_service = universe_service or AlphaUniverseService(self.repository)
        self.feature_service = feature_service or AlphaFeatureService(self.repository)

    def scan(
        self,
        *,
        market: str = "cn",
        universe: str = "all",
        symbols: str | Sequence[str] | None = None,
        top: int = 20,
        as_of: str | None = None,
    ) -> dict:
        normalized_market = str(market or "cn").strip().lower()
        normalized_top = max(int(top or 20), 1)
        built_universe = self.universe_service.build_universe(
            market=normalized_market,
            universe=universe,
            symbols=symbols,
        )
        if not built_universe.symbols:
            return self._payload(
                status="empty",
                market=normalized_market,
                universe=str(universe or "all").strip().lower(),
                symbols=[],
                top=normalized_top,
                items=[],
            )

        candidates: list[AlphaCandidate] = []
        for row in built_universe.symbols:
            symbol = str(row.get("symbol") or "").strip().upper()
            if not symbol:
                continue
            feature = self.feature_service.build_features(
                symbol=symbol,
                market=normalized_market,
            )
            signal_as_of = as_of or feature.as_of or self._today()
            candidates.append(
                AlphaCandidate(
                    candidate_id=f"alpha-{signal_as_of}-{symbol}",
                    universe_id=built_universe.universe_id,
                    as_of=signal_as_of,
                    market=normalized_market,
                    symbol=symbol,
                    factor_values=feature.factor_values,
                    score=feature.score,
                    reasons=feature.reasons,
                    data_quality=feature.data_quality,
                    data_gaps=feature.data_gaps,
                    status="candidate" if feature.score is not None else "insufficient_data",
                )
            )

        sorted_candidates = self._rank(candidates)[:normalized_top]
        items = [candidate.to_dict() for candidate in sorted_candidates]
        failed = sum(1 for item in items if item.get("data_quality") == "missing")
        partial = sum(1 for item in items if item.get("data_quality") == "partial")
        status = "ok"
        if partial or failed:
            status = "partial"
        return self._payload(
            status=status,
            market=normalized_market,
            universe=str(universe or "all").strip().lower(),
            symbols=[
                str(row.get("symbol") or "").strip().upper() for row in built_universe.symbols
            ],
            top=normalized_top,
            items=items,
            failed=failed,
            partial=partial,
        )

    def _rank(self, candidates: list[AlphaCandidate]) -> list[AlphaCandidate]:
        sorted_candidates = sorted(
            candidates,
            key=lambda item: (
                item.score is not None,
                item.score if item.score is not None else float("-inf"),
            ),
            reverse=True,
        )
        ranked: list[AlphaCandidate] = []
        rank = 1
        for candidate in sorted_candidates:
            if candidate.score is None:
                ranked.append(candidate)
                continue
            ranked.append(
                AlphaCandidate(
                    candidate_id=candidate.candidate_id,
                    universe_id=candidate.universe_id,
                    as_of=candidate.as_of,
                    market=candidate.market,
                    symbol=candidate.symbol,
                    factor_values=candidate.factor_values,
                    score=candidate.score,
                    rank=rank,
                    reasons=candidate.reasons,
                    data_quality=candidate.data_quality,
                    status=candidate.status,
                    data_gaps=candidate.data_gaps,
                )
            )
            rank += 1
        return ranked

    def _payload(
        self,
        *,
        status: str,
        market: str,
        universe: str,
        symbols: list[str],
        top: int,
        items: list[dict],
        failed: int = 0,
        partial: int = 0,
    ) -> dict:
        return json_safe(
            {
                "status": status,
                "source": "alpha_scan",
                "computed_at": datetime.now(timezone.utc).isoformat(),
                "request": {
                    "market": market,
                    "universe": universe,
                    "symbols": symbols,
                    "top": top,
                },
                "summary": {
                    "scanned": len(symbols),
                    "candidates": len(items),
                    "partial": partial,
                    "failed": failed,
                },
                "items": items,
            }
        )

    def _today(self) -> str:
        return datetime.now(timezone.utc).date().isoformat()
