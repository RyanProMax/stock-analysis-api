from __future__ import annotations

import json

from src.model.market import get_market_spec


def test_hk_market_spec_exposes_evaluation_rules():
    spec = get_market_spec("hk")

    assert spec.market == "hk"
    assert spec.currency == "HKD"
    assert spec.timezone == "Asia/Hong_Kong"
    assert spec.exchange == "HKEX"
    assert spec.regular_sessions == ["09:30-12:00", "13:00-16:00"]
    assert spec.lot_size == 100
    assert spec.price_tick == 0.01

    cost_model = spec.to_cost_model()
    assert cost_model["type"] == "market_spec_bps"
    assert cost_model["market"] == "hk"
    assert cost_model["round_trip_bps"] > 0
    assert cost_model["components"]["entry_slippage_bps"] > 0
    json.dumps(cost_model, allow_nan=False)


def test_us_market_spec_uses_one_share_lot_and_usd_rules():
    spec = get_market_spec("US.AAPL")

    assert spec.market == "us"
    assert spec.currency == "USD"
    assert spec.timezone == "America/New_York"
    assert spec.lot_size == 1
    assert spec.price_tick == 0.01
    assert spec.regular_sessions == ["09:30-16:00"]
    assert spec.round_trip_cost_bps > 0


def test_unknown_market_fails_fast():
    try:
        get_market_spec("crypto")
    except ValueError as exc:
        assert "unsupported market" in str(exc)
    else:
        raise AssertionError("expected unsupported market to fail")
