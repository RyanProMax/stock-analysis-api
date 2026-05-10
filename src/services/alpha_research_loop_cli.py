from __future__ import annotations

import argparse
import json
import sys
from typing import Optional, Sequence, TextIO

from ..repositories.strategy_registry_repository import SqliteStrategyRegistry
from .alpha_research_loop_service import AlphaResearchLoopService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run an offline alpha research loop with separated agent roles"
    )
    parser.add_argument("--market", default="cn", choices=["cn", "us", "hk"])
    parser.add_argument(
        "--universe",
        default="all",
        choices=["all", "stock", "etf", "watchlist"],
    )
    parser.add_argument("--symbols", help="Comma-separated explicit symbols")
    parser.add_argument("--factors", default="momentum_20d")
    parser.add_argument("--date")
    parser.add_argument("--start")
    parser.add_argument("--end")
    parser.add_argument("--forward-windows", default="1,5,20")
    parser.add_argument("--top", type=int, default=20)
    parser.add_argument("--quantiles", type=int, default=5)
    parser.add_argument("--cost-bps", type=float, default=10.0)
    parser.add_argument("--researcher-id", default="researcher-agent")
    parser.add_argument("--backtester-id", default="backtester-agent")
    parser.add_argument("--evaluator-id", default="judge-agent")
    parser.add_argument("--min-rank-ic-mean", type=float, default=0.03)
    parser.add_argument("--min-quantile-spread", type=float, default=0.0)
    parser.add_argument("--max-turnover", type=float, default=1.0)
    parser.add_argument("--min-observations", type=int, default=20)
    parser.add_argument("--allow-data-gaps", action="store_true")
    parser.add_argument("--include-attempt-details", action="store_true")
    parser.add_argument("--record-to-registry", action="store_true")
    parser.add_argument("--registry-db", help="SQLite strategy registry path")
    parser.add_argument("--run-id")
    parser.add_argument("--pretty", action="store_true")
    return parser


def _parse_csv(raw: str) -> list[str]:
    values = [part.strip() for part in str(raw or "").split(",")]
    return [value for value in values if value]


def _parse_forward_windows(raw: str) -> list[int]:
    windows: list[int] = []
    for value in _parse_csv(raw):
        window = int(value)
        if window <= 0:
            raise ValueError("forward window must be positive")
        windows.append(window)
    if not windows:
        raise ValueError("forward_windows must not be empty")
    return windows


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
    service: Optional[AlphaResearchLoopService] = None,
) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    registry = SqliteStrategyRegistry(args.registry_db) if args.record_to_registry else None
    loop_service = service or AlphaResearchLoopService(strategy_registry=registry)
    try:
        payload = loop_service.run(
            market=args.market,
            universe=args.universe,
            symbols=args.symbols,
            factors=_parse_csv(args.factors),
            date=args.date,
            start=args.start,
            end=args.end,
            forward_windows=_parse_forward_windows(args.forward_windows),
            top=args.top,
            quantiles=args.quantiles,
            cost_bps=args.cost_bps,
            researcher_id=args.researcher_id,
            backtester_id=args.backtester_id,
            evaluator_id=args.evaluator_id,
            min_rank_ic_mean=args.min_rank_ic_mean,
            min_quantile_spread=args.min_quantile_spread,
            max_turnover=args.max_turnover,
            min_observations=args.min_observations,
            allow_data_gaps=args.allow_data_gaps,
            include_attempt_details=args.include_attempt_details,
            record_to_registry=args.record_to_registry,
            run_id=args.run_id,
        )
        _emit(payload, args.pretty, writer)
        return 0
    except ValueError as exc:
        _emit(
            {"status": "failed", "source": "alpha_research_loop", "error": str(exc)}, False, writer
        )
        return 2
    except Exception as exc:
        _emit(
            {
                "status": "failed",
                "source": "alpha_research_loop",
                "error": f"alpha_research_loop 执行失败: {exc}",
            },
            False,
            writer,
        )
        return 1
