from __future__ import annotations

import json

from src.services.alpha_universe_seed_service import AlphaUniverseSeedService


def test_loads_seed_symbols_from_json_file(tmp_path):
    seed_file = tmp_path / "seeds.json"
    seed_file.write_text(
        json.dumps(
            {
                "version": 1,
                "seeds": [
                    {
                        "id": "hk_core",
                        "market": "hk",
                        "description": "HK core",
                        "symbols": ["HK.00700", "HK.09988", "HK.00700"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    service = AlphaUniverseSeedService(seed_file)

    seed = service.get_seed("hk_core", market="hk")

    assert seed["id"] == "hk_core"
    assert seed["market"] == "hk"
    assert seed["symbols"] == ["HK.00700", "HK.09988"]


def test_missing_seed_raises_clear_error(tmp_path):
    seed_file = tmp_path / "seeds.json"
    seed_file.write_text('{"version": 1, "seeds": []}', encoding="utf-8")
    service = AlphaUniverseSeedService(seed_file)

    try:
        service.get_seed("missing", market="us")
    except ValueError as exc:
        assert "universe seed not found: missing for market=us" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected missing seed to raise")
