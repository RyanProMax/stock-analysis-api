from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime
from statistics import mean
from typing import Any
from zoneinfo import ZoneInfo

from ..repositories.trading_ledger_repository import SqliteTradingLedger


def _parse_dt(value: str | None, timezone_name: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    tz = ZoneInfo(timezone_name)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=tz)
    return parsed.astimezone(tz)


def _local_date(value: str | None, timezone_name: str) -> date | None:
    parsed = _parse_dt(value, timezone_name)
    return parsed.date() if parsed is not None else None


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _run_has_snapshot_for_date(
    run: dict[str, Any],
    *,
    target_date: date,
    timezone_name: str,
) -> bool:
    for snapshot in (run.get("result") or {}).get("snapshots") or []:
        if _local_date(snapshot.get("as_of"), timezone_name) == target_date:
            return True
    return False


def _run_matches_date(
    run: dict[str, Any],
    *,
    target_date: date,
    timezone_name: str,
) -> bool:
    return _local_date(
        run.get("started_at"), timezone_name
    ) == target_date or _run_has_snapshot_for_date(
        run, target_date=target_date, timezone_name=timezone_name
    )


def _sort_snapshots(snapshots: list[dict[str, Any]], timezone_name: str) -> list[dict[str, Any]]:
    def key(snapshot: dict[str, Any]) -> tuple[str, str]:
        parsed = _parse_dt(snapshot.get("as_of"), timezone_name)
        return (parsed.isoformat() if parsed is not None else "", str(snapshot.get("code") or ""))

    return sorted(snapshots, key=key)


def _summarize_market(
    snapshots: list[dict[str, Any]],
    *,
    timezone_name: str,
) -> list[dict[str, Any]]:
    by_code: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for snapshot in snapshots:
        code = str(snapshot.get("code") or "").strip().upper()
        if code:
            by_code[code].append(snapshot)

    market: list[dict[str, Any]] = []
    for code in sorted(by_code):
        code_snapshots = _sort_snapshots(by_code[code], timezone_name)
        first = code_snapshots[0]
        latest = code_snapshots[-1]
        first_price = _as_float(first.get("price"))
        latest_price = _as_float(latest.get("price"))
        change_ratio = None
        if first_price not in (None, 0.0) and latest_price is not None:
            change_ratio = (latest_price - first_price) / first_price
        market.append(
            {
                "code": code,
                "name": latest.get("name") or first.get("name") or "",
                "first_price": first_price,
                "latest_price": latest_price,
                "change_ratio": change_ratio,
                "first_as_of": first.get("as_of"),
                "latest_as_of": latest.get("as_of"),
                "snapshot_count": len(code_snapshots),
                "source": latest.get("source") or first.get("source") or "unknown",
            }
        )
    return market


def build_daily_summary(
    ledger: SqliteTradingLedger,
    *,
    target_date: date,
    timezone_name: str,
    include_details: bool = False,
) -> dict[str, Any]:
    runs = [
        run
        for run in ledger.list_runs()
        if _run_matches_date(run, target_date=target_date, timezone_name=timezone_name)
    ]
    run_ids = {run["id"] for run in runs}
    orders = [order for order in ledger.list_orders() if order.get("run_id") in run_ids]
    risk_decisions: list[dict[str, Any]] = []
    snapshots: list[dict[str, Any]] = []
    strategy_versions: set[str] = set()

    for run in runs:
        result = run.get("result") or {}
        if result.get("strategy_version"):
            strategy_versions.add(str(result["strategy_version"]))
        snapshots.extend(result.get("snapshots") or [])
        risk_decisions.extend(ledger.list_risk_decisions(run["id"]))

    codes = {
        str(snapshot.get("code") or "").strip().upper()
        for snapshot in snapshots
        if str(snapshot.get("code") or "").strip()
    }
    codes.update(
        str(order.get("code") or "").strip().upper()
        for order in orders
        if str(order.get("code") or "").strip()
    )
    strategy_versions.update(
        str(order.get("strategy_version_id") or "")
        for order in orders
        if str(order.get("strategy_version_id") or "")
    )
    risk_reason_counts = Counter(str(decision.get("reason") or "") for decision in risk_decisions)
    risk_status_counts = Counter(str(decision.get("status") or "") for decision in risk_decisions)

    payload = {
        "status": "ok",
        "source": "trading_daily_summary",
        "date": target_date.isoformat(),
        "timezone": timezone_name,
        "summary": {
            "runs_total": len(runs),
            "orders_total": len(orders),
            "risk_decisions_total": len(risk_decisions),
            "accepted_risk_decisions": risk_status_counts.get("accepted", 0),
            "rejected_risk_decisions": risk_status_counts.get("rejected", 0),
            "codes": sorted(codes),
            "strategy_versions": sorted(strategy_versions),
        },
        "risk_reason_counts": dict(sorted(risk_reason_counts.items())),
        "market": _summarize_market(snapshots, timezone_name=timezone_name),
    }
    if include_details:
        payload.update(
            {
                "orders": orders,
                "risk_decisions": risk_decisions,
                "runs": runs,
            }
        )
    return payload


def build_ledger_backtest(summary: dict[str, Any]) -> dict[str, Any]:
    market_by_code = {item["code"]: item for item in summary.get("market") or []}
    mark_to_market: list[dict[str, Any]] = []
    for order in summary.get("orders") or []:
        code = str(order.get("code") or "").strip().upper()
        latest_price = _as_float((market_by_code.get(code) or {}).get("latest_price"))
        entry_price = _as_float(order.get("price"))
        quantity = int(order.get("quantity") or 0)
        side = str(order.get("side") or "").upper()
        return_ratio = None
        unrealized_pnl = None
        if entry_price not in (None, 0.0) and latest_price is not None:
            direction = -1 if side == "SELL" else 1
            return_ratio = direction * (latest_price - entry_price) / entry_price
            unrealized_pnl = direction * (latest_price - entry_price) * quantity
        mark_to_market.append(
            {
                "code": code,
                "side": side,
                "quantity": quantity,
                "entry_price": entry_price,
                "latest_price": latest_price,
                "unrealized_return_ratio": return_ratio,
                "unrealized_pnl": unrealized_pnl,
            }
        )

    returns = [
        item["unrealized_return_ratio"]
        for item in mark_to_market
        if item.get("unrealized_return_ratio") is not None
    ]
    summary_payload = summary.get("summary") or {}
    risk_total = int(summary_payload.get("risk_decisions_total") or 0)
    rejected = int(summary_payload.get("rejected_risk_decisions") or 0)
    return {
        "method": "ledger_snapshot_replay",
        "runs_total": int(summary_payload.get("runs_total") or 0),
        "orders_total": int(summary_payload.get("orders_total") or 0),
        "risk_decisions_total": risk_total,
        "rejection_rate": rejected / risk_total if risk_total else 0.0,
        "order_mark_to_market": mark_to_market,
        "average_order_return_ratio": mean(returns) if returns else None,
    }
