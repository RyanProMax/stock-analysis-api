from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
from zoneinfo import ZoneInfo
from typing import Any

from ..repositories.task_chain_repository import SqliteTaskChainRepository
from .alpha_research_loop_service import AlphaResearchLoopService

TASK_TYPES = {
    "market_observe",
    "alpha_mine",
    "judge_review",
    "paper_trade",
    "hourly_report",
    "post_market_research",
    "news_scan",
    "kol_scan",
    "sector_review",
    "strategy_analysis",
    "strategy_iteration",
    "daily_report",
}

NEWS_SCAN_INTERVAL_MINUTES = 15
KOL_SCAN_INTERVAL_MINUTES = 30


@dataclass(frozen=True)
class NextTaskSpec:
    task_type: str
    due_at: str
    payload: dict[str, Any]
    priority: int = 100


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

    def __init__(
        self,
        repository: SqliteTaskChainRepository | None = None,
        alpha_research_loop: AlphaResearchLoopService | None = None,
    ) -> None:
        self.repository = repository or SqliteTaskChainRepository()
        self.alpha_research_loop = alpha_research_loop or AlphaResearchLoopService()

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

        run = self.repository.start_run(task=acquired, owner_id=owner_id, started_at=now)
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
                    priority=spec.priority,
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
            return result, [self._next("judge_review", now_dt + timedelta(minutes=5), payload)]

        if task_type == "judge_review":
            result = {
                "task_type": task_type,
                "objective": "independent_strategy_gate",
                "review_status": "queued_for_independent_judge",
                "gate_policy": "paper_trade_only_after_passed_verdict",
            }
            return result, [self._next("paper_trade", now_dt + timedelta(minutes=5), payload)]

        if task_type == "paper_trade":
            result = {
                "task_type": task_type,
                "objective": "simulate_strategy_action",
                "execution_mode": "paper_only",
                "write_policy": "ledger_only_no_live_order",
            }
            return result, [self._next("hourly_report", now_dt + timedelta(minutes=5), payload)]

        if task_type == "hourly_report":
            result = self._build_hourly_report(
                now_dt,
                current_run_id=current_run_id,
                payload=payload,
            )
            if self._is_post_market_research_window(now_dt, payload=payload):
                result["summary"]["next_focus"] = "post_market_research"
                return result, [
                    self._next(
                        "post_market_research",
                        now_dt + timedelta(minutes=1),
                        payload,
                        priority=20,
                    )
                ]
            return result, [self._next("market_observe", now_dt + timedelta(hours=1), payload)]

        if task_type == "post_market_research":
            result = self._build_post_market_research(now_dt, payload=payload)
            return result, [
                self._next(
                    "news_scan",
                    now_dt + timedelta(minutes=1),
                    payload,
                    priority=20,
                ),
                self._next(
                    "kol_scan",
                    now_dt + timedelta(minutes=1),
                    payload,
                    priority=25,
                ),
                self._next(
                    "sector_review",
                    now_dt + timedelta(minutes=3),
                    payload,
                    priority=30,
                )
            ]

        if task_type == "news_scan":
            result = self._build_news_scan(now_dt, payload=payload)
            return result, self._next_recurring_scan(
                "news_scan",
                now_dt,
                payload,
                interval_minutes=NEWS_SCAN_INTERVAL_MINUTES,
            )

        if task_type == "kol_scan":
            result = self._build_kol_scan(now_dt, payload=payload)
            return result, [
                *self._next_recurring_scan(
                "kol_scan",
                now_dt,
                payload,
                interval_minutes=KOL_SCAN_INTERVAL_MINUTES,
                ),
                *self._next_strategy_iteration(now_dt, payload),
            ]

        if task_type == "sector_review":
            result = self._build_sector_review(now_dt, payload=payload)
            return result, [
                self._next(
                    "strategy_analysis",
                    now_dt + timedelta(minutes=2),
                    payload,
                    priority=20,
                )
            ]

        if task_type == "strategy_analysis":
            result = self._build_strategy_analysis(now_dt, payload=payload)
            return result, [
                self._next(
                    "daily_report",
                    now_dt + timedelta(minutes=2),
                    payload,
                    priority=20,
                )
            ]

        if task_type == "strategy_iteration":
            result = self._build_strategy_iteration(now_dt, payload=payload)
            return result, []

        result = self._build_daily_report(now_dt, current_run_id=current_run_id)
        superseded = self.repository.supersede_pending_tasks(
            task_types=["market_observe"],
            due_before=_format_dt(now_dt),
            updated_at=_format_dt(now_dt),
            reason="post_market_daily_report_completed",
        )
        result["superseded_pending_tasks"] = {
            "market_observe": superseded,
            "reason": "post_market_daily_report_completed",
        }
        return result, [self._next("market_observe", now_dt + timedelta(days=1), payload)]

    def _build_hourly_report(
        self,
        now: datetime,
        *,
        current_run_id: str | None,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        period_end = _format_dt(now)
        period_start = _format_dt(now - timedelta(hours=1))
        runs = self.repository.list_runs_between(period_start=period_start, period_end=period_end)
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
                "next_focus": (
                    "post_market_research"
                    if self._is_post_market_research_window(now, payload=payload)
                    else "continue_task_chain"
                ),
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

    def _build_post_market_research(
        self,
        now: datetime,
        *,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "task_type": "post_market_research",
            "report_type": "post_market_research",
            "computed_at": _format_dt(now),
            "market": payload.get("market", "cn"),
            "objective": "collect_after_close_market_news_kol_and_hotspots",
            "research_streams": [
                "market_hotspots",
                "news_search_scan_15m",
                "kol_intel_scan_30m",
                "macro_and_liquidity_context",
                "corporate_events",
            ],
            "status": "collected",
            "write_policy": "append_only_task_run",
            "next_focus": "news_scan_kol_scan_and_sector_review",
        }

    def _build_news_scan(
        self,
        now: datetime,
        *,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        if payload.get("disable_external_collectors") is True:
            return {
                "task_type": "news_scan",
                "report_type": "news_scan",
                "computed_at": _format_dt(now),
                "market": payload.get("market", "cn"),
                "cadence_minutes": NEWS_SCAN_INTERVAL_MINUTES,
                "status": "skipped",
                "reason": "external_collectors_disabled",
            }

        queries = self._news_queries(payload)
        provider = self._news_search_provider()
        if provider is None:
            return {
                "task_type": "news_scan",
                "report_type": "news_scan",
                "computed_at": _format_dt(now),
                "market": payload.get("market", "cn"),
                "cadence_minutes": NEWS_SCAN_INTERVAL_MINUTES,
                "status": "degraded",
                "reason": "news_search_provider_unavailable",
                "setup_hint": "install tvly or set TASK_CHAIN_NEWS_SEARCH_COMMAND",
                "queries": queries,
            }

        results = [
            self._run_news_query(provider=provider, query=query)
            for query in queries
        ]
        ok_count = sum(1 for result in results if result.get("status") == "ok")
        return {
            "task_type": "news_scan",
            "report_type": "news_scan",
            "computed_at": _format_dt(now),
            "market": payload.get("market", "cn"),
            "cadence_minutes": NEWS_SCAN_INTERVAL_MINUTES,
            "status": "collected" if ok_count else "degraded",
            "provider": provider["name"],
            "queries": queries,
            "result_count": ok_count,
            "results": results,
        }

    def _build_kol_scan(
        self,
        now: datetime,
        *,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        days = int(payload.get("kol_days") or payload.get("days") or 1)
        if payload.get("disable_external_collectors") is True:
            return {
                "task_type": "kol_scan",
                "report_type": "kol_scan",
                "computed_at": _format_dt(now),
                "market": payload.get("market", "cn"),
                "cadence_minutes": KOL_SCAN_INTERVAL_MINUTES,
                "days": days,
                "status": "skipped",
                "reason": "external_collectors_disabled",
            }

        skill_root = Path(
            os.environ.get("STOCK_KOL_INTEL_ROOT")
            or "/Users/ryan/projects/stock-kol-intel"
        )
        script_path = skill_root / "commands" / "kol.py"
        if not script_path.exists():
            return {
                "task_type": "kol_scan",
                "report_type": "kol_scan",
                "computed_at": _format_dt(now),
                "market": payload.get("market", "cn"),
                "cadence_minutes": KOL_SCAN_INTERVAL_MINUTES,
                "days": days,
                "status": "degraded",
                "reason": "stock_kol_intel_skill_not_found",
                "skill_root": str(skill_root),
            }

        command = [
            os.environ.get("TASK_CHAIN_PYTHON") or "python3",
            str(script_path),
        ]
        command_result = self._run_external_command(
            command,
            input_text=json.dumps({"argsText": f"--days={days}"}, ensure_ascii=False),
            timeout_seconds=int(os.environ.get("TASK_CHAIN_KOL_TIMEOUT_SECONDS") or 180),
            cwd=skill_root,
        )
        if command_result["status"] != "ok":
            return {
                "task_type": "kol_scan",
                "report_type": "kol_scan",
                "computed_at": _format_dt(now),
                "market": payload.get("market", "cn"),
                "cadence_minutes": KOL_SCAN_INTERVAL_MINUTES,
                "days": days,
                "status": "degraded",
                "reason": "stock_kol_intel_skill_failed",
                "command": command_result,
            }

        parsed = self._parse_json_text(command_result.get("stdout") or "")
        reply = parsed.get("reply") if isinstance(parsed, dict) else {}
        if isinstance(reply, dict) and reply.get("type") == "assistant_prompt":
            prompt = str(reply.get("content") or "").strip()
            return {
                "task_type": "kol_scan",
                "report_type": "kol_scan",
                "computed_at": _format_dt(now),
                "market": payload.get("market", "cn"),
                "cadence_minutes": KOL_SCAN_INTERVAL_MINUTES,
                "days": days,
                "status": "agent_required",
                "source": "stock-kol-intel",
                "ack": reply.get("ack"),
                "prompt_chars": len(prompt),
                "prompt_preview": prompt[:1200],
                "reason": "stock_kol_intel_returns_assistant_prompt",
            }

        final_markdown = (
            reply.get("final_markdown")
            or reply.get("content")
            if isinstance(reply, dict)
            else ""
        )
        final_markdown = str(final_markdown or "").strip()
        return {
            "task_type": "kol_scan",
            "report_type": "kol_scan",
            "computed_at": _format_dt(now),
            "market": payload.get("market", "cn"),
            "cadence_minutes": KOL_SCAN_INTERVAL_MINUTES,
            "days": days,
            "status": "collected" if final_markdown else "degraded",
            "source": "stock-kol-intel",
            "summary_markdown": final_markdown[:4000],
            "content_chars": len(final_markdown),
            "raw_status": parsed.get("status") if isinstance(parsed, dict) else None,
        }

    def _build_sector_review(
        self,
        now: datetime,
        *,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "task_type": "sector_review",
            "report_type": "sector_review",
            "computed_at": _format_dt(now),
            "market": payload.get("market", "cn"),
            "objective": "summarize_sector_direction_and_trackable_targets",
            "sector_view": {
                "status": "summarized",
                "trackable_direction_required": True,
                "requires_symbols_or_etfs": True,
                "source_policy": "only_verified_market_context",
            },
            "next_focus": "strategy_analysis",
        }

    def _build_strategy_analysis(
        self,
        now: datetime,
        *,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        markets = self._research_markets(payload)
        research_results = []
        for market in markets:
            try:
                research_results.append(
                    self.alpha_research_loop.run(
                        market=market,
                        universe=str(payload.get("universe") or "tracked"),
                        symbols=payload.get("symbols"),
                        date=now.date().isoformat(),
                        top=int(payload.get("top") or 10),
                        allow_data_gaps=True,
                        include_attempt_details=False,
                        record_to_registry=False,
                        run_id=f"task-chain-{market}-{now.date().isoformat()}",
                    )
                )
            except Exception as exc:
                research_results.append(
                    {
                        "status": "degraded",
                        "source": "alpha_research_loop",
                        "market": market,
                        "error": str(exc),
                    }
                )
        passed = sum(
            1 for result in research_results if result.get("status") == "human_review_ready"
        )
        return {
            "task_type": "strategy_analysis",
            "report_type": "strategy_analysis",
            "computed_at": _format_dt(now),
            "objective": "run_alpha_research_loop_and_prepare_daily_review",
            "markets": markets,
            "status": "completed" if research_results else "empty",
            "summary": {
                "research_runs": len(research_results),
                "human_review_ready": passed,
                "needs_iteration": sum(
                    1 for result in research_results if result.get("status") == "needs_iteration"
                ),
                "degraded": sum(
                    1 for result in research_results if result.get("status") == "degraded"
                ),
                "proposal_not_applied": True,
                "paper_only": True,
            },
            "research_results": research_results,
            "next_focus": "daily_report",
        }

    def _build_strategy_iteration(
        self,
        now: datetime,
        *,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        runs = self.repository.list_runs_between(
            period_start=_format_dt(day_start),
            period_end=_format_dt(now),
        )
        inputs = self._latest_outputs_by_task_type(
            runs,
            task_types=["news_scan", "kol_scan", "sector_review", "strategy_analysis"],
        )
        analysis = self._build_strategy_analysis(now, payload=payload)
        return {
            **analysis,
            "task_type": "strategy_iteration",
            "report_type": "strategy_iteration",
            "objective": "iterate_alpha_strategy_from_latest_market_intel",
            "iteration_inputs": {
                "news_scan": self._summarize_news_scan(inputs.get("news_scan")),
                "kol_intel": self._summarize_kol_scan(inputs.get("kol_scan")),
                "sector_view": self._summarize_sector_review(inputs.get("sector_review")),
                "previous_strategy_analysis": self._summarize_strategy_analysis(
                    inputs.get("strategy_analysis")
                ),
            },
            "iteration_policy": {
                "cadence": "after_kol_scan_when_no_main_drain_task_is_pending",
                "paper_only": True,
                "proposal_not_applied": True,
                "requires_human_approval_before_activation": True,
            },
            "next_focus": "wait_for_next_intel_or_market_session",
        }

    def _build_daily_report(
        self,
        now: datetime,
        *,
        current_run_id: str | None,
    ) -> dict[str, Any]:
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        period_start = _format_dt(day_start)
        period_end = _format_dt(now)
        runs = self.repository.list_runs_between(period_start=period_start, period_end=period_end)
        runs = [run for run in runs if run.get("id") != current_run_id]
        failed_count = sum(1 for run in runs if run.get("status") == "failed")
        post_market_outputs = self._latest_outputs_by_task_type(
            runs,
            task_types=[
                "post_market_research",
                "news_scan",
                "kol_scan",
                "sector_review",
                "strategy_analysis",
            ],
        )
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
            "market_research": self._summarize_post_market_research(
                post_market_outputs.get("post_market_research")
            ),
            "news_scan": self._summarize_news_scan(post_market_outputs.get("news_scan")),
            "kol_intel": self._summarize_kol_scan(post_market_outputs.get("kol_scan")),
            "sector_view": self._summarize_sector_review(post_market_outputs.get("sector_review")),
            "strategy_analysis": self._summarize_strategy_analysis(
                post_market_outputs.get("strategy_analysis")
            ),
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
    def _is_post_market_research_window(
        now: datetime,
        *,
        payload: dict[str, Any],
    ) -> bool:
        if payload.get("force_post_market_research") is True:
            return True
        local = now.astimezone(ZoneInfo("Asia/Shanghai"))
        return time(15, 30) <= local.time() <= time(23, 59)

    @staticmethod
    def _research_markets(payload: dict[str, Any]) -> list[str]:
        raw = str(payload.get("market") or "cn").strip().lower()
        if raw in {"hk_us", "hk-us", "hk,us"}:
            return ["hk", "us"]
        if raw in {"all", "global"}:
            return ["cn", "hk", "us"]
        if raw in {"cn", "hk", "us"}:
            return [raw]
        return ["cn"]

    @staticmethod
    def _latest_outputs_by_task_type(
        runs: list[dict[str, Any]],
        *,
        task_types: list[str],
    ) -> dict[str, dict[str, Any]]:
        wanted = set(task_types)
        outputs: dict[str, dict[str, Any]] = {}
        for run in runs:
            task_type = str(run.get("task_type") or "")
            if task_type not in wanted:
                continue
            output = run.get("output") if isinstance(run.get("output"), dict) else {}
            outputs[task_type] = output
        return outputs

    @staticmethod
    def _summarize_post_market_research(output: dict[str, Any] | None) -> dict[str, Any]:
        if not output:
            return {"status": "missing", "reason": "post_market_research_not_run"}
        return {
            "status": "summarized",
            "streams": output.get("research_streams") or [],
            "next_focus": output.get("next_focus"),
        }

    @staticmethod
    def _summarize_news_scan(output: dict[str, Any] | None) -> dict[str, Any]:
        if not output:
            return {"status": "missing", "reason": "news_scan_not_run"}
        results = output.get("results") if isinstance(output.get("results"), list) else []
        top_items: list[dict[str, Any]] = []
        for result in results:
            items = result.get("items") if isinstance(result, dict) else []
            if isinstance(items, list):
                top_items.extend(items[:2])
        return {
            "status": output.get("status") or "unknown",
            "provider": output.get("provider"),
            "cadence_minutes": output.get("cadence_minutes"),
            "query_count": len(output.get("queries") or []),
            "item_count": len(top_items),
            "top_items": top_items[:6],
            "reason": output.get("reason"),
        }

    @staticmethod
    def _summarize_kol_scan(output: dict[str, Any] | None) -> dict[str, Any]:
        if not output:
            return {"status": "missing", "reason": "kol_scan_not_run"}
        return {
            "status": output.get("status") or "unknown",
            "source": output.get("source"),
            "cadence_minutes": output.get("cadence_minutes"),
            "days": output.get("days"),
            "content_chars": output.get("content_chars", 0),
            "summary_markdown": str(output.get("summary_markdown") or "")[:1200],
            "reason": output.get("reason"),
        }

    @staticmethod
    def _summarize_sector_review(output: dict[str, Any] | None) -> dict[str, Any]:
        if not output:
            return {"status": "missing", "reason": "sector_review_not_run"}
        sector_view = (
            output.get("sector_view") if isinstance(output.get("sector_view"), dict) else {}
        )
        return {
            "status": "summarized",
            "trackable_direction_required": bool(sector_view.get("trackable_direction_required")),
            "requires_symbols_or_etfs": bool(sector_view.get("requires_symbols_or_etfs")),
        }

    @staticmethod
    def _summarize_strategy_analysis(output: dict[str, Any] | None) -> dict[str, Any]:
        if not output:
            return {"status": "missing", "reason": "strategy_analysis_not_run"}
        summary = output.get("summary") if isinstance(output.get("summary"), dict) else {}
        return {
            "status": "summarized",
            "research_runs": int(summary.get("research_runs") or 0),
            "human_review_ready": int(summary.get("human_review_ready") or 0),
            "needs_iteration": int(summary.get("needs_iteration") or 0),
            "degraded": int(summary.get("degraded") or 0),
            "proposal_not_applied": bool(summary.get("proposal_not_applied", True)),
            "paper_only": bool(summary.get("paper_only", True)),
        }

    @staticmethod
    def _build_correction_reviews(*, failed_count: int) -> list[dict[str, Any]]:
        verdict = "warn" if failed_count else "pass"
        base_issue = [] if failed_count == 0 else ["task_failures_need_review_before_next_trade"]
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
                "correction_actions": ["compare_candidate_against_champion_and_backtest"],
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
        task_type: str,
        due_at: datetime,
        payload: dict[str, Any],
        *,
        priority: int = 100,
    ) -> NextTaskSpec:
        return NextTaskSpec(
            task_type=task_type,
            due_at=_format_dt(due_at),
            payload=payload,
            priority=int(priority),
        )

    def _next_recurring_scan(
        self,
        task_type: str,
        now: datetime,
        payload: dict[str, Any],
        *,
        interval_minutes: int,
    ) -> list[NextTaskSpec]:
        if payload.get("force_post_market_research") is True:
            return []
        next_due = now + timedelta(minutes=interval_minutes)
        if not self._is_post_market_research_window(next_due, payload=payload):
            return []
        return [
            self._next(
                task_type,
                next_due,
                payload,
                priority=40,
            )
        ]

    def _next_strategy_iteration(
        self,
        now: datetime,
        payload: dict[str, Any],
    ) -> list[NextTaskSpec]:
        if payload.get("force_post_market_research") is True:
            return []
        if not self._is_post_market_research_window(now, payload=payload):
            return []
        if self._has_pending_or_running_task(
            ["sector_review", "strategy_analysis", "strategy_iteration", "daily_report"]
        ):
            return []
        return [
            self._next(
                "strategy_iteration",
                now + timedelta(minutes=1),
                payload,
                priority=45,
            )
        ]

    def _has_pending_or_running_task(self, task_types: list[str]) -> bool:
        wanted = set(task_types)
        for status in ["pending", "running"]:
            if any(task["task_type"] in wanted for task in self.repository.list_tasks(status=status)):
                return True
        return False

    @staticmethod
    def _news_queries(payload: dict[str, Any]) -> list[str]:
        raw_queries = payload.get("news_queries")
        if isinstance(raw_queries, list):
            queries = [str(item).strip() for item in raw_queries if str(item).strip()]
            if queries:
                return queries[:5]

        markets = TaskChainService._research_markets(payload)
        base: list[str] = []
        if "hk" in markets:
            base.append("港股 今日 热点 板块 AI 半导体 IPO")
        if "us" in markets:
            base.append("US stocks today AI semiconductor software market news")
        if "cn" in markets:
            base.append("A股 今日 热点 板块 AI 半导体 新能源")
        return base or ["全球 股市 今日 热点 板块"]

    @staticmethod
    def _news_search_provider() -> dict[str, Any] | None:
        configured = os.environ.get("TASK_CHAIN_NEWS_SEARCH_COMMAND")
        if configured:
            return {"name": "configured_search_command", "command": configured}
        tvly_path = shutil.which("tvly")
        if not tvly_path:
            for candidate in [
                Path.home() / ".local" / "bin" / "tvly",
                Path.home() / ".cargo" / "bin" / "tvly",
                Path("/opt/homebrew/bin/tvly"),
                Path("/usr/local/bin/tvly"),
            ]:
                if candidate.exists() and os.access(candidate, os.X_OK):
                    tvly_path = str(candidate)
                    break
        if tvly_path:
            return {"name": "tavily_cli", "command": tvly_path}
        return None

    def _run_news_query(self, *, provider: dict[str, Any], query: str) -> dict[str, Any]:
        command = self._news_command(provider=provider, query=query)
        command_result = self._run_external_command(
            command,
            timeout_seconds=int(os.environ.get("TASK_CHAIN_NEWS_TIMEOUT_SECONDS") or 30),
        )
        if command_result["status"] != "ok":
            return {"status": "failed", "query": query, "command": command_result}

        parsed = self._parse_json_text(command_result.get("stdout") or "")
        items = self._extract_search_items(parsed)
        return {
            "status": "ok",
            "query": query,
            "items": items,
            "raw_chars": len(command_result.get("stdout") or ""),
        }

    @staticmethod
    def _news_command(*, provider: dict[str, Any], query: str) -> list[str]:
        command = str(provider.get("command") or "")
        if provider.get("name") == "tavily_cli":
            return [
                command,
                "search",
                query,
                "--topic",
                "news",
                "--time-range",
                "day",
                "--max-results",
                "5",
                "--json",
            ]
        if "{query}" in command:
            return shlex.split(command.format(query=query))
        return [*shlex.split(command), query]

    @staticmethod
    def _run_external_command(
        command: list[str],
        *,
        input_text: str | None = None,
        timeout_seconds: int,
        cwd: Path | None = None,
    ) -> dict[str, Any]:
        try:
            completed = subprocess.run(
                command,
                input=input_text,
                text=True,
                capture_output=True,
                timeout=timeout_seconds,
                cwd=str(cwd) if cwd else None,
                check=False,
            )
        except FileNotFoundError as exc:
            return {"status": "failed", "reason": "command_not_found", "error": str(exc)}
        except subprocess.TimeoutExpired as exc:
            return {
                "status": "failed",
                "reason": "timeout",
                "timeout_seconds": timeout_seconds,
                "stdout": exc.stdout or "",
                "stderr": exc.stderr or "",
            }

        status = "ok" if completed.returncode == 0 else "failed"
        return {
            "status": status,
            "returncode": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
        }

    @staticmethod
    def _parse_json_text(raw: str) -> Any:
        text = str(raw or "").strip()
        if not text:
            return {}
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {"raw_text": text}

    @staticmethod
    def _extract_search_items(parsed: Any) -> list[dict[str, Any]]:
        candidates: Any
        if isinstance(parsed, list):
            candidates = parsed
        elif isinstance(parsed, dict):
            candidates = (
                parsed.get("results")
                or parsed.get("data")
                or parsed.get("items")
                or parsed.get("raw_text")
                or []
            )
        else:
            candidates = []

        if isinstance(candidates, str):
            return [{"title": candidates[:160], "url": None, "snippet": candidates[:300]}]
        if not isinstance(candidates, list):
            return []

        items: list[dict[str, Any]] = []
        for item in candidates[:5]:
            if isinstance(item, str):
                items.append({"title": item[:160], "url": None, "snippet": item[:300]})
                continue
            if not isinstance(item, dict):
                continue
            title = item.get("title") or item.get("name") or item.get("headline")
            url = item.get("url") or item.get("link")
            snippet = item.get("content") or item.get("snippet") or item.get("description")
            items.append(
                {
                    "title": str(title or "")[:160],
                    "url": str(url or "")[:300] if url else None,
                    "snippet": str(snippet or "")[:300],
                }
            )
        return items

    @staticmethod
    def _validate_task_type(task_type: str) -> None:
        if task_type not in TASK_TYPES:
            raise ValueError(f"unsupported task_type: {task_type}")
