from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, Sequence

from ..model.serialization import json_safe
from ..repositories.strategy_registry_repository import SqliteStrategyRegistry
from .alpha_daily_report_service import AlphaDailyReportService
from .strategy_judge_service import StrategyJudgeService


class AlphaResearchLoopService:
    def __init__(
        self,
        report_service: Optional[AlphaDailyReportService] = None,
        judge_service: Optional[StrategyJudgeService] = None,
        strategy_registry: Optional[SqliteStrategyRegistry] = None,
    ) -> None:
        self.report_service = report_service or AlphaDailyReportService()
        self.judge_service = judge_service or StrategyJudgeService()
        self.strategy_registry = strategy_registry

    def run(
        self,
        *,
        market: str = "cn",
        universe: str = "all",
        symbols: str | Sequence[str] | None = None,
        factors: Sequence[str] | None = None,
        date: str | None = None,
        start: str | None = None,
        end: str | None = None,
        forward_windows: Sequence[int] | None = None,
        top: int = 20,
        quantiles: int = 5,
        cost_bps: float | None = None,
        researcher_id: str = "researcher-agent",
        backtester_id: str = "backtester-agent",
        evaluator_id: str = "judge-agent",
        min_rank_ic_mean: float = 0.03,
        min_quantile_spread: float = 0.0,
        max_turnover: float = 1.0,
        min_observations: int = 20,
        min_challenger_rank_ic_delta: float = 0.0,
        min_challenger_quantile_spread_delta: float = 0.0,
        min_backtest_total_return: float = 0.0,
        max_backtest_drawdown: float = -1.0,
        min_backtest_periods: int = 1,
        allow_data_gaps: bool = False,
        include_attempt_details: bool = False,
        record_to_registry: bool = False,
        run_id: str | None = None,
    ) -> dict:
        role_ids = self._roles(
            researcher_id=researcher_id,
            backtester_id=backtester_id,
            evaluator_id=evaluator_id,
        )
        normalized_factors = self._factors(factors)
        attempts: list[dict] = []
        selected: dict | None = None
        for index, factor in enumerate(normalized_factors, start=1):
            report = self.report_service.report(
                market=market,
                universe=universe,
                symbols=symbols,
                factor=factor,
                date=date,
                start=start,
                end=end,
                forward_windows=forward_windows,
                top=top,
                quantiles=quantiles,
                cost_bps=cost_bps,
                include_details=False,
            )
            attempt = self._attempt(
                index=index,
                factor=factor,
                report=report,
                role_ids=role_ids,
                min_rank_ic_mean=min_rank_ic_mean,
                min_quantile_spread=min_quantile_spread,
                max_turnover=max_turnover,
                min_observations=min_observations,
                min_challenger_rank_ic_delta=min_challenger_rank_ic_delta,
                min_challenger_quantile_spread_delta=min_challenger_quantile_spread_delta,
                min_backtest_total_return=min_backtest_total_return,
                max_backtest_drawdown=max_backtest_drawdown,
                min_backtest_periods=min_backtest_periods,
                allow_data_gaps=allow_data_gaps,
                include_attempt_details=include_attempt_details,
            )
            strategy_proposal = attempt.pop("_strategy_proposal", None)
            attempts.append(attempt)
            if attempt["status"] == "passed":
                selected = {
                    "iteration": attempt["iteration"],
                    "factor": attempt["factor"],
                    "proposal_id": attempt.get("proposal_id"),
                    "strategy_version": attempt.get("strategy_version"),
                    "verdict": attempt["verdict"],
                    "strategy_proposal": strategy_proposal,
                }
                break

        human_review_ready = selected is not None
        computed_at = self._now()
        payload = {
            "run_id": run_id or self._run_id(computed_at),
            "status": "human_review_ready" if human_review_ready else "needs_iteration",
            "source": "alpha_research_loop",
            "computed_at": computed_at,
            "team": {
                "researcher": {
                    "id": role_ids["researcher_id"],
                    "responsibility": "generate_strategy_proposal",
                },
                "backtester": {
                    "id": role_ids["backtester_id"],
                    "responsibility": "produce_alpha_evaluation",
                },
                "evaluator": {
                    "id": role_ids["evaluator_id"],
                    "responsibility": "judge_strategy_proposal",
                },
            },
            "request": {
                "market": market,
                "universe": universe,
                "symbols": symbols,
                "factors": normalized_factors,
                "date": date,
                "start": start,
                "end": end,
                "forward_windows": list(forward_windows or []),
                "top": int(top),
                "quantiles": int(quantiles),
                "cost_bps": float(cost_bps) if cost_bps is not None else None,
            },
            "summary": {
                "iterations": len(attempts),
                "passed_attempts": sum(1 for attempt in attempts if attempt["status"] == "passed"),
                "blocked_attempts": sum(
                    1 for attempt in attempts if attempt["status"] == "blocked"
                ),
                "selected_factor": selected.get("factor") if selected else None,
                "human_review_ready": human_review_ready,
                "proposal_not_applied": True,
                "approval_required": True,
                "recorded_to_registry": bool(record_to_registry),
            },
            "attempts": attempts,
            "selected": selected,
            "next_research_actions": [] if selected else self._next_actions(attempts),
            "recorded": None,
        }
        if record_to_registry:
            payload["recorded"] = self._record_to_registry(payload)
        return json_safe(payload)

    def _attempt(
        self,
        *,
        index: int,
        factor: str,
        report: dict,
        role_ids: dict[str, str],
        min_rank_ic_mean: float,
        min_quantile_spread: float,
        max_turnover: float,
        min_observations: int,
        min_challenger_rank_ic_delta: float,
        min_challenger_quantile_spread_delta: float,
        min_backtest_total_return: float,
        max_backtest_drawdown: float,
        min_backtest_periods: int,
        allow_data_gaps: bool,
        include_attempt_details: bool,
    ) -> dict:
        proposal = report.get("strategy_proposal")
        evaluation = report.get("alpha_evaluation") or {}
        metrics = evaluation.get("metrics") or {}
        if not proposal:
            attempt = {
                "iteration": index,
                "factor": factor,
                "status": "blocked",
                "roles": role_ids,
                "report_status": report.get("status"),
                "proposal_id": None,
                "strategy_version": None,
                "evaluation_status": evaluation.get("status"),
                "metrics": metrics,
                "judge_reasons": ["strategy_proposal_missing"],
                "verdict": None,
                "human_review_ready": False,
            }
            if include_attempt_details:
                attempt["report"] = report
            return attempt

        judge_result = self.judge_service.judge(
            proposal_payload=proposal,
            evaluation_payload={"alpha_evaluation": evaluation},
            champion_payload=self._champion_payload(),
            evaluator_id=role_ids["evaluator_id"],
            researcher_id=role_ids["researcher_id"],
            min_rank_ic_mean=min_rank_ic_mean,
            min_quantile_spread=min_quantile_spread,
            max_turnover=max_turnover,
            min_observations=min_observations,
            min_challenger_rank_ic_delta=min_challenger_rank_ic_delta,
            min_challenger_quantile_spread_delta=min_challenger_quantile_spread_delta,
            min_backtest_total_return=min_backtest_total_return,
            max_backtest_drawdown=max_backtest_drawdown,
            min_backtest_periods=min_backtest_periods,
            allow_data_gaps=allow_data_gaps,
        )
        verdict = judge_result["verdict"]
        attempt = {
            "iteration": index,
            "factor": factor,
            "status": verdict["gate_status"],
            "roles": role_ids,
            "report_status": report.get("status"),
            "proposal_id": proposal.get("proposal_id"),
            "strategy_version": proposal.get("strategy_version"),
            "evaluation_status": evaluation.get("status"),
            "metrics": metrics,
            "judge_reasons": verdict.get("reasons") or [],
            "verdict": verdict,
            "human_review_ready": bool(verdict.get("human_review_ready")),
            "_strategy_proposal": judge_result.get("strategy_proposal"),
        }
        if include_attempt_details:
            attempt["report"] = report
            attempt["judge_result"] = judge_result
            attempt["strategy_proposal"] = judge_result.get("strategy_proposal")
        return attempt

    def _champion_payload(self) -> dict | None:
        if self.strategy_registry is None:
            return None
        active = self.strategy_registry.current_strategy()
        if not active:
            return None
        return self.strategy_registry.latest_judge_verdict(
            active["strategy_version"],
            gate_status="passed",
            proposal_id=active.get("source_proposal_id"),
        )

    def _roles(
        self, *, researcher_id: str, backtester_id: str, evaluator_id: str
    ) -> dict[str, str]:
        roles = {
            "researcher_id": str(researcher_id or "").strip(),
            "backtester_id": str(backtester_id or "").strip(),
            "evaluator_id": str(evaluator_id or "").strip(),
        }
        if any(not value for value in roles.values()):
            raise ValueError("agent team role ids are required")
        if len(set(roles.values())) != len(roles):
            raise ValueError("agent team roles must be distinct")
        return roles

    def _factors(self, factors: Sequence[str] | None) -> list[str]:
        result = [str(factor or "").strip() for factor in (factors or ["momentum_20d"])]
        result = [factor for factor in result if factor]
        if not result:
            raise ValueError("factors must not be empty")
        return result

    def _next_actions(self, attempts: list[dict]) -> list[str]:
        reasons = {reason for attempt in attempts for reason in attempt.get("judge_reasons") or []}
        actions = ["try_alternative_factor_or_longer_horizon"]
        if "insufficient_observations" in reasons or "data_gaps_present" in reasons:
            actions.append("expand_history_or_fix_data_gaps")
        if (
            "rank_ic_mean_below_threshold" in reasons
            or "quantile_spread_below_threshold" in reasons
            or "challenger_rank_ic_not_improved" in reasons
            or "challenger_quantile_spread_not_improved" in reasons
        ):
            actions.append("revise_factor_definition_or_universe")
        if "turnover_above_threshold" in reasons:
            actions.append("add_turnover_or_rebalance_constraints")
        if (
            "backtest_summary_missing" in reasons
            or "insufficient_backtest_periods" in reasons
            or "backtest_total_return_missing" in reasons
            or "backtest_drawdown_missing" in reasons
        ):
            actions.append("run_or_fix_portfolio_backtest")
        if (
            "backtest_total_return_below_threshold" in reasons
            or "backtest_drawdown_above_threshold" in reasons
        ):
            actions.append("revise_strategy_or_risk_constraints")
        if "strategy_proposal_missing" in reasons:
            actions.append("lower_candidate_filters_or_expand_universe")
        return actions

    def _record_to_registry(self, payload: dict) -> dict:
        registry = self.strategy_registry or SqliteStrategyRegistry()
        run_payload = json_safe({**payload, "recorded": None})
        run_record = registry.record_research_loop_run(run_payload)
        verdict_records = []
        for attempt in payload.get("attempts") or []:
            verdict = attempt.get("verdict") if isinstance(attempt, dict) else None
            if not isinstance(verdict, dict):
                continue
            verdict_records.append(registry.record_judge_verdict(verdict))
        return {
            "research_loop_run": run_record,
            "judge_verdicts": verdict_records,
        }

    def _run_id(self, computed_at: str) -> str:
        safe = computed_at.replace("-", "").replace(":", "").replace(".", "").replace("+", "")
        return f"research-loop-{safe}"

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()
