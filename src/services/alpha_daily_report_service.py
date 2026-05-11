from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, Sequence

from ..model.serialization import json_safe
from ..model.strategy import StrategyProposal
from ..repositories import MarketDataRepository, market_data_repository
from .alpha_backtest_service import AlphaBacktestService
from .alpha_evaluation_service import AlphaEvaluationService
from .alpha_scan_service import AlphaScanService


class AlphaDailyReportService:
    def __init__(
        self,
        repository: Optional[MarketDataRepository] = None,
        scan_service: Optional[AlphaScanService] = None,
        evaluation_service: Optional[AlphaEvaluationService] = None,
        backtest_service: Optional[AlphaBacktestService] = None,
    ) -> None:
        self.repository = repository or market_data_repository
        self.scan_service = scan_service or AlphaScanService(repository=self.repository)
        self.evaluation_service = evaluation_service or AlphaEvaluationService(
            repository=self.repository
        )
        self.backtest_service = backtest_service or AlphaBacktestService(repository=self.repository)

    def report(
        self,
        *,
        market: str = "cn",
        universe: str = "all",
        symbols: str | Sequence[str] | None = None,
        factor: str = "momentum_20d",
        date: str | None = None,
        start: str | None = None,
        end: str | None = None,
        forward_windows: Sequence[int] | None = None,
        top: int = 20,
        quantiles: int = 5,
        cost_bps: float | None = None,
        strategy_version: str | None = None,
        include_details: bool = False,
    ) -> dict:
        report_date = date or self._today()
        normalized_market = str(market or "cn").strip().lower()
        normalized_universe = str(universe or "all").strip().lower()
        normalized_factor = str(factor or "momentum_20d").strip()
        normalized_top = max(int(top or 20), 1)
        windows = self._normalize_forward_windows(forward_windows)
        scan = self.scan_service.scan(
            market=normalized_market,
            universe=normalized_universe,
            symbols=symbols,
            top=normalized_top,
            as_of=report_date,
        )
        candidate_symbols = [
            str(item.get("symbol") or "").strip().upper()
            for item in scan.get("items") or []
            if str(item.get("symbol") or "").strip()
        ]
        evaluation_symbols = candidate_symbols or symbols
        evaluation = self.evaluation_service.evaluate(
            market=normalized_market,
            universe=normalized_universe,
            symbols=evaluation_symbols,
            factor=normalized_factor,
            start=start,
            end=end,
            forward_windows=windows,
            quantiles=quantiles,
            cost_bps=cost_bps,
        )
        backtest = self.backtest_service.backtest(
            market=normalized_market,
            universe=normalized_universe,
            symbols=evaluation_symbols,
            factor=normalized_factor,
            start=start,
            end=end,
            top_n=normalized_top,
            holding_period=windows[0],
            cost_bps=cost_bps,
            include_details=include_details,
        )

        status = self._report_status(scan, evaluation)
        proposal = self._build_proposal(
            report_date=report_date,
            market=normalized_market,
            universe=normalized_universe,
            factor=normalized_factor,
            forward_windows=windows,
            top=normalized_top,
            strategy_version=strategy_version,
            scan=scan,
            evaluation=evaluation,
            backtest=backtest,
        )
        metrics = (evaluation.get("evaluation") or {}).get("metrics") or {}
        summary = {
            "market": normalized_market,
            "universe": normalized_universe,
            "factor": normalized_factor,
            "candidates": int((scan.get("summary") or {}).get("candidates") or 0),
            "evaluated_symbols": int((evaluation.get("summary") or {}).get("symbols") or 0),
            "observations": int((evaluation.get("summary") or {}).get("observations") or 0),
            "top_candidate_symbols": candidate_symbols[: min(normalized_top, 5)],
            "rank_ic_mean": metrics.get("rank_ic_mean"),
            "rank_ic_tstat": metrics.get("rank_ic_tstat"),
            "quantile_spread": metrics.get("quantile_spread"),
            "turnover": metrics.get("turnover"),
            "backtest_total_return": (backtest.get("summary") or {}).get("total_return"),
            "backtest_max_drawdown": (backtest.get("summary") or {}).get("max_drawdown"),
            "backtest_periods": (backtest.get("summary") or {}).get("periods"),
            "human_action_required": proposal is not None,
            "proposal_not_applied": True,
        }
        payload = {
            "status": status,
            "source": "alpha_daily_report",
            "date": report_date,
            "summary": summary,
            "watch": {
                "status": "not_configured",
                "alerts": [],
            },
            "simulated_trading": {
                "status": "not_connected",
                "orders": 0,
                "risk_decisions": 0,
            },
            "factor_evaluation_drift": {
                "status": "not_available",
                "reason": "single_report_mvp",
            },
            "alpha_scan": self._scan_section(scan, include_details=include_details),
            "alpha_evaluation": self._evaluation_section(
                evaluation,
                include_details=include_details,
            ),
            "alpha_backtest": self._backtest_section(backtest, include_details=include_details),
            "strategy_proposal": proposal,
        }
        return json_safe(payload)

    def _build_proposal(
        self,
        *,
        report_date: str,
        market: str,
        universe: str,
        factor: str,
        forward_windows: tuple[int, ...],
        top: int,
        strategy_version: str | None,
        scan: dict,
        evaluation: dict,
        backtest: dict,
    ) -> dict | None:
        candidates = scan.get("items") or []
        observations = int((evaluation.get("summary") or {}).get("observations") or 0)
        if not candidates or observations <= 0:
            return None
        version = strategy_version or f"alpha_topn_{factor}.{report_date.replace('-', '')}"
        metrics = (evaluation.get("evaluation") or {}).get("metrics") or {}
        data_gaps = list((evaluation.get("summary") or {}).get("data_gaps") or [])
        proposal = StrategyProposal(
            proposal_id=f"proposal-alpha-daily-{report_date}-{factor}",
            strategy_version=version,
            generated_at=self._now(),
            source="alpha_daily_report",
            proposed_changes=[
                {
                    "type": "register_alpha_topn_candidate",
                    "parameters": {
                        "market": market,
                        "universe": universe,
                        "factor": factor,
                        "top_n": top,
                        "forward_windows": list(forward_windows),
                    },
                    "risk_limits": {
                        "requires_human_approval": True,
                        "proposal_not_applied": True,
                    },
                }
            ],
            evidence={
                "alpha_scan_summary": scan.get("summary") or {},
                "alpha_evaluation_summary": evaluation.get("summary") or {},
                "rank_ic_mean": metrics.get("rank_ic_mean"),
                "quantile_spread": metrics.get("quantile_spread"),
                "turnover": metrics.get("turnover"),
                "data_gaps": data_gaps,
                "alpha_backtest_summary": backtest.get("summary") or {},
            },
        )
        return proposal.to_dict()

    def _scan_section(self, scan: dict, *, include_details: bool) -> dict:
        if include_details:
            return scan
        return {
            "status": scan.get("status"),
            "summary": scan.get("summary") or {},
            "top_candidates": [
                {
                    "rank": item.get("rank"),
                    "symbol": item.get("symbol"),
                    "score": item.get("score"),
                    "data_quality": item.get("data_quality"),
                    "reasons": item.get("reasons") or [],
                }
                for item in (scan.get("items") or [])[:5]
            ],
        }

    def _evaluation_section(self, evaluation: dict, *, include_details: bool) -> dict:
        if include_details:
            return evaluation
        result = evaluation.get("evaluation") or {}
        return {
            "status": evaluation.get("status"),
            "summary": evaluation.get("summary") or {},
            "evaluation_id": result.get("evaluation_id"),
            "candidate_id": result.get("candidate_id"),
            "metrics": result.get("metrics") or {},
            "sample_split": result.get("sample_split") or {},
            "data_gaps": result.get("data_gaps") or [],
        }

    def _backtest_section(self, backtest: dict, *, include_details: bool) -> dict:
        if include_details:
            return backtest
        return {
            "status": backtest.get("status"),
            "summary": backtest.get("summary") or {},
            "cost_model": backtest.get("cost_model") or {},
            "constraints": backtest.get("constraints") or [],
        }

    def _report_status(self, scan: dict, evaluation: dict) -> str:
        if scan.get("status") == "empty":
            return "empty"
        if scan.get("status") == "partial" or evaluation.get("status") == "partial":
            return "partial"
        return "ok"

    def _normalize_forward_windows(self, windows: Sequence[int] | None) -> tuple[int, ...]:
        raw = windows or AlphaEvaluationService.DEFAULT_FORWARD_WINDOWS
        normalized = tuple(sorted({int(window) for window in raw if int(window) > 0}))
        if not normalized:
            raise ValueError("forward_windows must not be empty")
        return normalized

    def _today(self) -> str:
        return datetime.now(timezone.utc).date().isoformat()

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()
