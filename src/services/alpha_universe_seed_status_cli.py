from __future__ import annotations

import argparse
import json
import sys
from typing import Optional, Sequence, TextIO

from .alpha_universe_seed_status_service import AlphaUniverseSeedStatusService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Inspect local coverage for an Alpha universe seed"
    )
    parser.add_argument("--universe-seed", required=True)
    parser.add_argument("--market", choices=["cn", "us", "hk"])
    parser.add_argument("--seed-file")
    parser.add_argument("--start-date")
    parser.add_argument("--stale-before")
    parser.add_argument("--pretty", action="store_true")
    return parser


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
    service: Optional[AlphaUniverseSeedStatusService] = None,
) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    status_service = service or AlphaUniverseSeedStatusService()
    try:
        payload = status_service.inspect(
            seed_id=args.universe_seed,
            market=args.market,
            seed_file=args.seed_file,
            start_date=args.start_date,
            stale_before=args.stale_before,
        )
        _emit(payload, args.pretty, writer)
        return 0
    except ValueError as exc:
        _emit(
            {"status": "failed", "source": "alpha_universe_seed_status", "error": str(exc)},
            False,
            writer,
        )
        return 2
    except Exception as exc:
        _emit(
            {
                "status": "failed",
                "source": "alpha_universe_seed_status",
                "error": f"alpha_universe_seed_status 执行失败: {exc}",
            },
            False,
            writer,
        )
        return 1
