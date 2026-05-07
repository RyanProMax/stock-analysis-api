from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import sys
from typing import Any, Optional, Sequence, TextIO
from zoneinfo import ZoneInfo

from ..repositories.trading_ledger_repository import SqliteTradingLedger
from .trading_ledger_analysis import build_daily_summary, build_ledger_backtest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Review simulated trading ledger and emit a strategy proposal"
    )
    parser.add_argument("--ledger-db", help="SQLite trading ledger path")
    parser.add_argument("--date", help="Trading date in YYYY-MM-DD; defaults to today")
    parser.add_argument("--timezone", default="Asia/Shanghai")
    parser.add_argument("--min-runs", type=int, default=3)
    parser.add_argument("--max-rejection-rate", type=float, default=0.5)
    parser.add_argument("--pretty", action="store_true")
    return parser


def _emit(payload: dict[str, Any], pretty: bool, writer: Optional[TextIO]) -> None:
    output = json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        indent=2 if pretty else None,
        separators=(",", ": ") if pretty else (",", ":"),
    )
    target = writer or sys.stdout
    target.write(output)
    target.write("\n")


def _target_date(raw_date: str | None, timezone_name: str):
    if raw_date:
        return datetime.fromisoformat(raw_date).date()
    return datetime.now(ZoneInfo(timezone_name)).date()


def _strategy_version(summary: dict[str, Any]) -> str:
    versions = (summary.get("summary") or {}).get("strategy_versions") or []
    return str(versions[0]) if versions else "unknown"


def _gate_reasons(
    *,
    summary: dict[str, Any],
    backtest: dict[str, Any],
    min_runs: int,
    max_rejection_rate: float,
) -> list[str]:
    reasons: list[str] = []
    if int(backtest.get("runs_total") or 0) < min_runs:
        reasons.append("insufficient_runs")
    if float(backtest.get("rejection_rate") or 0.0) > max_rejection_rate:
        reasons.append("rejection_rate_exceeds_limit")
    if not (summary.get("market") or []):
        reasons.append("missing_market_replay")
    return reasons


def _build_proposal(
    *,
    summary: dict[str, Any],
    backtest: dict[str, Any],
    gate_reasons: list[str],
) -> dict[str, Any]:
    passed = not gate_reasons
    strategy_version = _strategy_version(summary)
    proposed_changes = []
    if passed:
        proposed_changes.append(
            {
                "type": "keep_strategy_under_review",
                "rationale": "ledger replay passed minimum run and rejection-rate gates; keep this as a candidate for the next paper-trading window",
                "parameters": {},
            }
        )
    return {
        "schema_version": "trading_strategy_proposal.v1",
        "status": "candidate" if passed else "blocked",
        "strategy_version": strategy_version,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "approval_required": True,
        "effective_status": "candidate_only" if passed else "not_applied",
        "proposed_changes": proposed_changes,
        "evidence": {
            "daily_summary": summary.get("summary") or {},
            "ledger_backtest": backtest,
            "gate_reasons": gate_reasons,
        },
        "constraints": [
            "proposal_not_applied_to_runtime",
            "requires_human_approval",
            "agent_not_in_intraday_order_path",
        ],
    }


def main(argv: Optional[Sequence[str]] = None, *, writer: Optional[TextIO] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        target_date = _target_date(args.date, args.timezone)
        ledger = SqliteTradingLedger(args.ledger_db)
        summary = build_daily_summary(
            ledger,
            target_date=target_date,
            timezone_name=args.timezone,
            include_details=True,
        )
        backtest = build_ledger_backtest(summary)
        gate_reasons = _gate_reasons(
            summary=summary,
            backtest=backtest,
            min_runs=args.min_runs,
            max_rejection_rate=args.max_rejection_rate,
        )
        gate_status = "passed" if not gate_reasons else "blocked"
        proposal = _build_proposal(
            summary=summary,
            backtest=backtest,
            gate_reasons=gate_reasons,
        )
        payload = {
            "status": "ok" if gate_status == "passed" else "blocked",
            "source": "trading_strategy_review",
            "date": target_date.isoformat(),
            "timezone": args.timezone,
            "review": {
                "gate_status": gate_status,
                "gate_reasons": gate_reasons,
                "min_runs": args.min_runs,
                "max_rejection_rate": args.max_rejection_rate,
                "ledger_backtest": backtest,
            },
            "strategy_proposal": proposal,
        }
        _emit(payload, args.pretty, writer)
        return 0
    except ValueError as exc:
        _emit(
            {"status": "failed", "source": "trading_strategy_review", "error": str(exc)},
            False,
            writer,
        )
        return 2
    except Exception as exc:
        _emit(
            {
                "status": "failed",
                "source": "trading_strategy_review",
                "error": f"策略评审失败: {exc}",
            },
            False,
            writer,
        )
        return 1
