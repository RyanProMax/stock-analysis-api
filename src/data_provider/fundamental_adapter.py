"""
Fundamental normalization helpers adapted from daily_stock_analysis.

Current scope:
- normalize dividend event series into a stable payload
- derive TTM dividend yield from already-fetched price
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import pandas as pd


def safe_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
    text = str(value).strip().replace(",", "").replace("%", "")
    if not text:
        return None
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def safe_datetime(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    try:
        parsed = pd.to_datetime(value)
    except Exception:
        return None
    if pd.isna(parsed):
        return None
    try:
        return parsed.to_pydatetime()
    except Exception:
        return None


def build_dividend_payload_from_series(
    dividends: pd.Series | None,
    *,
    max_events: int = 5,
    as_of: Optional[datetime] = None,
) -> Dict[str, Any]:
    if dividends is None or dividends.empty:
        return {}

    now_dt = as_of or datetime.now()
    now_date = now_dt.date()
    ttm_start_date = now_date - timedelta(days=365)

    events: List[Dict[str, Any]] = []
    dedupe_keys: set[tuple[str, float]] = set()
    clean_dividends = dividends.dropna().sort_index(ascending=False)
    for index, value in clean_dividends.items():
        event_dt = safe_datetime(index)
        per_share = safe_float(value)
        if event_dt is None or per_share is None or per_share <= 0:
            continue
        event_date = event_dt.date()
        if event_date > now_date:
            continue
        dedupe_key = (event_date.isoformat(), round(per_share, 6))
        if dedupe_key in dedupe_keys:
            continue
        dedupe_keys.add(dedupe_key)
        events.append(
            {
                "event_date": event_date.isoformat(),
                "cash_dividend_per_share": round(per_share, 6),
                "is_pre_tax": True,
            }
        )

    if not events:
        return {}

    ttm_events = []
    for item in events:
        event_dt = safe_datetime(item.get("event_date"))
        if event_dt is None:
            continue
        event_date = event_dt.date()
        if ttm_start_date <= event_date <= now_date:
            ttm_events.append(item)

    return {
        "events": events[: max(1, max_events)],
        "ttm_event_count": len(ttm_events),
        "ttm_cash_dividend_per_share": (
            round(sum(float(item.get("cash_dividend_per_share") or 0.0) for item in ttm_events), 6)
            if ttm_events
            else None
        ),
        "coverage": "cash_dividend_pre_tax",
        "as_of": now_date.isoformat(),
    }


def enrich_dividend_payload_with_yield(
    dividend_payload: Dict[str, Any],
    latest_price: Any,
) -> Dict[str, Any]:
    payload = dict(dividend_payload or {})
    ttm_cash = safe_float(payload.get("ttm_cash_dividend_per_share"))
    price = safe_float(latest_price)
    ttm_yield_pct = None
    if ttm_cash is not None and price is not None and price > 0:
        ttm_yield_pct = round(ttm_cash / price * 100.0, 4)
    payload["ttm_dividend_yield_pct"] = ttm_yield_pct
    if ttm_yield_pct is not None:
        payload["yield_formula"] = "ttm_cash_dividend_per_share / latest_price * 100"
    return payload
