from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from ..repositories.task_chain_repository import SqliteTaskChainRepository

TASK_TYPES = {
    "market_observe",
    "alpha_mine",
    "judge_review",
    "paper_trade",
    "hourly_report",
    "daily_report",
}


@dataclass(frozen=True)
class NextTaskSpec:
    task_type: str
    due_at: str
    payload: dict[str, Any]


def _parse_dt(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    parsed = datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _format_dt(value: datetime) -> str:
    return value.isoformat()


def _status_counts(runs: list[dict[str, Any]]) -> dict[str, int]:
    return dict(Counter(str(run.get("status") or "unknown") for run in runs))


class TaskChainService:
    """Runs one due atomic task and persists the next task decision."""

    def __init__(self, repository: SqliteTaskChainRepository | None = None) -> None:
        self.repository = repository or SqliteTaskChainRepository()

    def bootstrap(
        self,
        *,
        task_type: str,
        due_at: str,
        payload: dict[str, Any] | None = None,
        parent_task_id: str | None = None,
    ) -> dict[str, Any]:
        self._validate_task_type(task_type)
        task = self.repository.create_task(
            task_type=task_type,
            due_at=due_at,
            payload=payload or {},
            parent_task_id=parent_task_id,
            created_at=due_at,
        )
        return {"status": "ok", "source": "task_chain_bootstrap", "task": task}

    def tick(
        self,
        *,
        now: str,
        owner_id: str,
        lease_ttl_seconds: int = 900,
    ) -> dict[str, Any]:
        acquired = self.repository.acquire_due_task(
            now=now,
            owner_id=owner_id,
            lease_ttl_seconds=lease_ttl_seconds,
        )
        if acquired is None:
            return {
                "status": "skipped",
                "source": "task_chain_tick",
                "reason": "no_due_task",
                "schedule": {"now": now},
            }

        run = self.repository.start_run(
            task=acquired, owner_id=owner_id, started_at=now
        )
        try:
            result, next_specs = self._execute_task(
                acquired,
                now=now,
                current_run_id=run["id"],
            )
            next_tasks = [
                self.repository.create_task(
                    task_type=spec.task_type,
                    due_at=spec.due_at,
                    payload=spec.payload,
                    parent_task_id=acquired["id"],
                    created_at=now,
                )
                for spec in next_specs
            ]
            finished_run = self.repository.finish_run(
                run_id=run["id"],
                finished_at=now,
                status="ok",
                output=result,
            )
            completed_task = self.repository.complete_task(
                task_id=acquired["id"],
                status="completed",
                updated_at=now,
                result=result,
            )
            return {
                "status": "ok",
                "source": "task_chain_tick",
                "task": completed_task,
                "run": finished_run,
                "result": result,
                "next_tasks": next_tasks,
            }
        except Exception as exc:
            error = str(exc)
            failed_run = self.repository.finish_run(
                run_id=run["id"],
                finished_at=now,
                status="failed",
                output={},
                error=error,
            )
            failed_task = self.repository.complete_task(
                task_id=acquired["id"],
                status="failed",
                updated_at=now,
                result={},
                error=error,
            )
            return {
                "status": "failed",
                "source": "task_chain_tick",
                "task": failed_task,
                "run": failed_run,
                "error": error,
                "next_tasks": [],
            }

    def _execute_task(
        self,
        task: dict[str, Any],
        *,
        now: str,
        current_run_id: str | None = None,
    ) -> tuple[dict[str, Any], list[NextTaskSpec]]:
        task_type = str(task["task_type"])
        self._validate_task_type(task_type)
        payload = task.get("payload") or {}
        now_dt = _parse_dt(now)

        if task_type == "market_observe":
            result = {
                "task_type": task_type,
                "objective": "observe_market_and_prepare_research",
                "market": payload.get("market", "cn"),
                "symbols": payload.get("symbols"),
                "actions": ["collect_market_context", "prepare_alpha_research"],
                "write_policy": "append_only_task_run",
            }
            return result, [
                self._next(
                    "alpha_mine",
                    now_dt + timedelta(minutes=5),
                    payload,
                )
            ]

        if task_type == "alpha_mine":
            result = {
                "task_type": task_type,
                "objective": "mine_candidate_alpha",
                "research_status": "queued_for_existing_alpha_research_loop",
                "allowed_execution": "readonly_research_and_backtest_only",
            }
            return result, [
                self._next("judge_review", now_dt + timedelta(minutes=5), payload)
            ]

        if task_type == "judge_review":
            result = {
                "task_type": task_type,
                "objective": "independent_strategy_gate",
                "review_status": "queued_for_independent_judge",
                "gate_policy": "paper_trade_only_after_passed_verdict",
            }
            return result, [
                self._next("paper_trade", now_dt + timedelta(minutes=5), payload)
            ]

        if task_type == "paper_trade":
            result = {
                "task_type": task_type,
                "objective": "simulate_strategy_action",
                "execution_mode": "paper_only",
                "write_policy": "ledger_only_no_live_order",
            }
            return result, [
                self._next("hourly_report", now_dt + timedelta(minutes=5), payload)
            ]

        if task_type == "hourly_report":
            result = self._build_hourly_report(
                now_dt,
                current_run_id=current_run_id,
            )
            return result, [
                self._next("market_observe", now_dt + timedelta(hours=1), payload)
            ]

        result = self._build_daily_report(now_dt, current_run_id=current_run_id)
        return result, [
            self._next("market_observe", now_dt + timedelta(days=1), payload)
        ]

    def _build_hourly_report(
        self,
        now: datetime,
        *,
        current_run_id: str | None,
    ) -> dict[str, Any]:
        period_end = _format_dt(now)
        period_start = _format_dt(now - timedelta(hours=1))
        runs = self.repository.list_runs_between(
            period_start=period_start, period_end=period_end
        )
        runs = [run for run in runs if run.get("id") != current_run_id]
        summary = {
            "report_type": "hourly",
            "period_start": period_start,
            "period_end": period_end,
            "summary": {
                "tasks_total": len(runs),
                "tasks_by_status": _status_counts(runs),
                "simulated_orders": 0,
                "risk_events": [],
                "next_focus": "continue_task_chain",
            },
        }
        self.repository.record_summary(
            summary_type="hourly",
            period_start=period_start,
            period_end=period_end,
            summary=summary,
            created_at=period_end,
        )
        return summary

    def _build_daily_report(
        self,
        now: datetime,
        *,
        current_run_id: str | None,
    ) -> dict[str, Any]:
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        period_start = _format_dt(day_start)
        period_end = _format_dt(now)
        runs = self.repository.list_runs_between(
            period_start=period_start, period_end=period_end
        )
        runs = [run for run in runs if run.get("id") != current_run_id]
        failed_count = sum(1 for run in runs if run.get("status") == "failed")
        correction_reviews = self._build_correction_reviews(failed_count=failed_count)
        summary = {
            "report_type": "daily",
            "period_start": period_start,
            "period_end": period_end,
            "operations": {
                "simulated_orders": 0,
                "live_orders": 0,
                "policy": "paper_only",
            },
            "positions": {"status": "paper_ledger_pending"},
            "sector_view": {"status": "pending_market_context"},
            "tasks": {
                "total": len(runs),
                "by_status": _status_counts(runs),
            },
            "correction_reviews": correction_reviews,
            "next_day_plan": {
                "start_with": "market_observe",
                "constraints": self._next_day_constraints(correction_reviews),
            },
        }
        self.repository.record_summary(
            summary_type="daily",
            period_start=period_start,
            period_end=period_end,
            summary=summary,
            created_at=period_end,
        )
        return summary

    @staticmethod
    def _build_correction_reviews(*, failed_count: int) -> list[dict[str, Any]]:
        verdict = "warn" if failed_count else "pass"
        base_issue = (
            [] if failed_count == 0 else ["task_failures_need_review_before_next_trade"]
        )
        return [
            {
                "role": "trade_auditor",
                "verdict": verdict,
                "major_issues": base_issue,
                "correction_actions": ["verify_paper_orders_match_strategy_version"],
            },
            {
                "role": "strategy_reviewer",
                "verdict": verdict,
                "major_issues": base_issue,
                "correction_actions": [
                    "compare_candidate_against_champion_and_backtest"
                ],
            },
            {
                "role": "risk_reviewer",
                "verdict": verdict,
                "major_issues": base_issue,
                "correction_actions": ["check_drawdown_concentration_and_sector_beta"],
            },
            {
                "role": "contrarian_reviewer",
                "verdict": verdict,
                "major_issues": base_issue,
                "correction_actions": ["state_most_likely_failure_mode"],
            },
        ]

    @staticmethod
    def _next_day_constraints(correction_reviews: list[dict[str, Any]]) -> list[str]:
        if any(review.get("verdict") == "fail" for review in correction_reviews):
            return ["pause_paper_trade_until_review"]
        if any(review.get("verdict") == "warn" for review in correction_reviews):
            return ["research_and_review_before_paper_trade"]
        return ["paper_only", "append_only_evidence_required"]

    @staticmethod
    def _next(
        task_type: str, due_at: datetime, payload: dict[str, Any]
    ) -> NextTaskSpec:
        return NextTaskSpec(
            task_type=task_type, due_at=_format_dt(due_at), payload=payload
        )

    @staticmethod
    def _validate_task_type(task_type: str) -> None:
        if task_type not in TASK_TYPES:
            raise ValueError(f"unsupported task_type: {task_type}")
