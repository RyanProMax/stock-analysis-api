from __future__ import annotations

from datetime import datetime, time, timedelta
from typing import Optional, Sequence
from zoneinfo import ZoneInfo

from ..model.serialization import json_safe
from ..repositories.strategy_registry_repository import SqliteStrategyRegistry
from ..repositories.trading_ledger_repository import SqliteTradingLedger
from .alpha_daily_report_service import AlphaDailyReportService

DEFAULT_SOURCE = "watch_worker_tick"
DEFAULT_TIMEZONE = "Asia/Shanghai"
DEFAULT_ACTIVE_WINDOW = "09:30-11:30,13:00-15:00"


class WatchWorkerService:
    def __init__(
        self,
        *,
        strategy_registry: Optional[SqliteStrategyRegistry] = None,
        state_repository: Optional[SqliteTradingLedger] = None,
        report_service: Optional[AlphaDailyReportService] = None,
    ) -> None:
        self.strategy_registry = strategy_registry or SqliteStrategyRegistry()
        self.state_repository = state_repository or SqliteTradingLedger()
        self.report_service = report_service or AlphaDailyReportService()

    def tick(
        self,
        *,
        state_key: str = "alpha-watch-worker",
        interval_seconds: int = 300,
        timezone_name: str = DEFAULT_TIMEZONE,
        active_window: str = DEFAULT_ACTIVE_WINDOW,
        now: str | None = None,
        force: bool = False,
        market: str | None = None,
        universe: str | None = None,
        symbols: str | Sequence[str] | None = None,
        factor: str | None = None,
        date: str | None = None,
        start: str | None = None,
        end: str | None = None,
        forward_windows: Sequence[int] | None = None,
        top: int | None = None,
        include_details: bool = False,
    ) -> dict:
        parsed_now = self._parse_now(now, timezone_name)
        windows = self._parse_windows(active_window)
        schedule = {
            "state_key": state_key,
            "timezone": timezone_name,
            "active_window": active_window,
            "interval_seconds": int(interval_seconds),
            "now": parsed_now.isoformat(),
            "force": bool(force),
        }

        if not force and not self._is_inside_window(parsed_now, windows):
            return json_safe(
                {
                    "status": "skipped",
                    "source": DEFAULT_SOURCE,
                    "reason": "outside_active_window",
                    "schedule": {
                        **schedule,
                        "next_run_at": self._next_window_start(parsed_now, windows).isoformat(),
                    },
                }
            )

        last_tick = self.state_repository.get_scheduler_tick(state_key)
        if last_tick and not force:
            last_started_at = datetime.fromisoformat(last_tick["last_started_at"]).astimezone(
                parsed_now.tzinfo
            )
            next_due_at = last_started_at + timedelta(seconds=int(interval_seconds))
            if parsed_now < next_due_at:
                return json_safe(
                    {
                        "status": "skipped",
                        "source": DEFAULT_SOURCE,
                        "reason": "not_due",
                        "schedule": {
                            **schedule,
                            "last_started_at": last_started_at.isoformat(),
                            "next_run_at": next_due_at.isoformat(),
                        },
                    }
                )

        active_strategy = self.strategy_registry.current_strategy()
        if active_strategy is None:
            return json_safe(
                {
                    "status": "skipped",
                    "source": DEFAULT_SOURCE,
                    "reason": "no_active_strategy",
                    "schedule": schedule,
                    "simulated_execution": self._disabled_execution(),
                }
            )

        started_at = parsed_now.isoformat()
        try:
            report = self.report_service.report(
                market=market or active_strategy["parameters"].get("market") or "cn",
                universe=universe or active_strategy["parameters"].get("universe") or "all",
                symbols=symbols or active_strategy["parameters"].get("symbols"),
                factor=factor or active_strategy["parameters"].get("factor") or "momentum_20d",
                date=date or parsed_now.date().isoformat(),
                start=start or active_strategy["parameters"].get("start"),
                end=end or active_strategy["parameters"].get("end"),
                forward_windows=forward_windows
                or active_strategy["parameters"].get("forward_windows"),
                top=top or active_strategy["parameters"].get("top_n") or 20,
                strategy_version=active_strategy["strategy_version"],
                include_details=include_details,
            )
            status = report.get("status") or "ok"
            payload = {
                "status": status,
                "source": DEFAULT_SOURCE,
                "schedule": schedule,
                "active_strategy": active_strategy,
                "summary": report.get("summary") or {},
                "watch_alerts": self._watch_alerts(report),
                "simulated_execution": self._disabled_execution(),
            }
            if include_details:
                payload["alpha_daily_report"] = report
        except Exception as exc:
            payload = {
                "status": "degraded",
                "source": DEFAULT_SOURCE,
                "reason": "report_failed",
                "error": str(exc),
                "schedule": schedule,
                "active_strategy": active_strategy,
                "watch_alerts": [],
                "simulated_execution": self._disabled_execution(),
            }

        finished_at = self._parse_now(None, timezone_name).isoformat()
        self.state_repository.record_scheduler_tick(
            state_key,
            due_at=parsed_now.isoformat(),
            started_at=started_at,
            finished_at=finished_at,
            status=str(payload["status"]),
            payload=payload,
        )
        return json_safe(payload)

    def _watch_alerts(self, report: dict) -> list[dict]:
        symbols = (report.get("summary") or {}).get("top_candidate_symbols") or []
        return [
            {
                "type": "alpha_candidate",
                "symbol": symbol,
                "severity": "info",
            }
            for symbol in symbols
        ]

    def _disabled_execution(self) -> dict:
        return {
            "status": "disabled",
            "reason": "watch_worker_mvp_read_only",
        }

    def _parse_now(self, raw_now: str | None, timezone_name: str) -> datetime:
        tz = ZoneInfo(timezone_name)
        if not raw_now:
            return datetime.now(tz)
        parsed = datetime.fromisoformat(raw_now)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=tz)
        return parsed.astimezone(tz)

    def _parse_windows(self, raw_windows: str) -> list[tuple[time, time]]:
        windows: list[tuple[time, time]] = []
        for part in str(raw_windows or "").split(","):
            item = part.strip()
            if not item:
                continue
            if "-" not in item:
                raise ValueError("--active-window must use HH:MM-HH:MM entries")
            raw_start, raw_end = item.split("-", 1)
            start = time.fromisoformat(raw_start.strip())
            end = time.fromisoformat(raw_end.strip())
            if start >= end:
                raise ValueError("--active-window start must be earlier than end")
            windows.append((start, end))
        if not windows:
            raise ValueError("--active-window must include at least one window")
        return windows

    def _is_inside_window(self, now: datetime, windows: list[tuple[time, time]]) -> bool:
        current = now.timetz().replace(tzinfo=None)
        return any(start <= current <= end for start, end in windows)

    def _next_window_start(self, now: datetime, windows: list[tuple[time, time]]) -> datetime:
        current = now.timetz().replace(tzinfo=None)
        for start, _end in sorted(windows):
            if current < start:
                return now.replace(hour=start.hour, minute=start.minute, second=0, microsecond=0)
        first_start = sorted(windows)[0][0]
        tomorrow = now + timedelta(days=1)
        return tomorrow.replace(
            hour=first_start.hour,
            minute=first_start.minute,
            second=0,
            microsecond=0,
        )
