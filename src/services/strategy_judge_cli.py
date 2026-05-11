from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Optional, Sequence, TextIO

from .strategy_judge_service import StrategyJudgeService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Evaluate a strategy proposal with an independent judge gate"
    )
    parser.add_argument("--proposal-json", required=True)
    parser.add_argument("--evaluation-json", required=True)
    parser.add_argument("--champion-json")
    parser.add_argument("--evaluator-id", required=True)
    parser.add_argument("--researcher-id")
    parser.add_argument("--min-rank-ic-mean", type=float, default=0.03)
    parser.add_argument("--min-quantile-spread", type=float, default=0.0)
    parser.add_argument("--max-turnover", type=float, default=1.0)
    parser.add_argument("--min-observations", type=int, default=20)
    parser.add_argument("--min-challenger-rank-ic-delta", type=float, default=0.0)
    parser.add_argument("--min-challenger-quantile-spread-delta", type=float, default=0.0)
    parser.add_argument("--min-backtest-total-return", type=float, default=0.0)
    parser.add_argument("--max-backtest-drawdown", type=float, default=-1.0)
    parser.add_argument("--min-backtest-periods", type=int, default=1)
    parser.add_argument("--allow-data-gaps", action="store_true")
    parser.add_argument("--pretty", action="store_true")
    return parser


def _load_json(path: str) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError("JSON payload must be an object")
    return payload


def _emit(payload: dict, pretty: bool, writer: Optional[TextIO]) -> None:
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


def main(
    argv: Optional[Sequence[str]] = None,
    *,
    writer: Optional[TextIO] = None,
    service: Optional[StrategyJudgeService] = None,
) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    judge = service or StrategyJudgeService()
    try:
        payload = judge.judge(
            proposal_payload=_load_json(args.proposal_json),
            evaluation_payload=_load_json(args.evaluation_json),
            champion_payload=_load_json(args.champion_json) if args.champion_json else None,
            evaluator_id=args.evaluator_id,
            researcher_id=args.researcher_id,
            min_rank_ic_mean=args.min_rank_ic_mean,
            min_quantile_spread=args.min_quantile_spread,
            max_turnover=args.max_turnover,
            min_observations=args.min_observations,
            min_challenger_rank_ic_delta=args.min_challenger_rank_ic_delta,
            min_challenger_quantile_spread_delta=args.min_challenger_quantile_spread_delta,
            min_backtest_total_return=args.min_backtest_total_return,
            max_backtest_drawdown=args.max_backtest_drawdown,
            min_backtest_periods=args.min_backtest_periods,
            allow_data_gaps=args.allow_data_gaps,
        )
        _emit(payload, args.pretty, writer)
        return 0
    except ValueError as exc:
        _emit({"status": "failed", "source": "strategy_judge", "error": str(exc)}, False, writer)
        return 2
    except Exception as exc:
        _emit(
            {
                "status": "failed",
                "source": "strategy_judge",
                "error": f"strategy_judge 执行失败: {exc}",
            },
            False,
            writer,
        )
        return 1
