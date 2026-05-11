from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional


class AlphaUniverseSeedService:
    """Read-only loader for tracked Alpha universe seed files."""

    DEFAULT_PATH = Path(__file__).resolve().parents[2] / "config" / "alpha_universe_seeds.json"

    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else self.DEFAULT_PATH

    def list_seeds(self, *, market: Optional[str] = None) -> list[dict[str, Any]]:
        normalized_market = self._normalize_market(market) if market else None
        seeds = self._load_payload().get("seeds") or []
        normalized = [self._normalize_seed(seed) for seed in seeds]
        if normalized_market:
            normalized = [seed for seed in normalized if seed["market"] == normalized_market]
        return normalized

    def get_seed(self, seed_id: str, *, market: Optional[str] = None) -> dict[str, Any]:
        normalized_seed_id = str(seed_id or "").strip()
        if not normalized_seed_id:
            raise ValueError("universe seed id is required")

        for seed in self.list_seeds(market=market):
            if seed["id"] == normalized_seed_id:
                return seed
        market_suffix = f" for market={self._normalize_market(market)}" if market else ""
        raise ValueError(f"universe seed not found: {normalized_seed_id}{market_suffix}")

    def _load_payload(self) -> dict[str, Any]:
        if not self.path.exists():
            raise ValueError(f"universe seed file not found: {self.path}")
        try:
            with self.path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid universe seed json: {self.path}") from exc
        if not isinstance(payload, dict):
            raise ValueError("universe seed file must contain a JSON object")
        return payload

    def _normalize_seed(self, seed: Any) -> dict[str, Any]:
        if not isinstance(seed, dict):
            raise ValueError("universe seed entries must be JSON objects")

        seed_id = str(seed.get("id") or "").strip()
        market = self._normalize_market(seed.get("market"))
        symbols = self._parse_symbols(seed.get("symbols"))
        if not seed_id:
            raise ValueError("universe seed id is required")
        if not symbols:
            raise ValueError(f"universe seed has no symbols: {seed_id}")

        return {
            "id": seed_id,
            "market": market,
            "description": seed.get("description") or "",
            "symbols": symbols,
        }

    @staticmethod
    def _parse_symbols(raw: Any) -> list[str]:
        if raw is None:
            return []
        if isinstance(raw, str):
            parts = raw.split(",")
        elif isinstance(raw, list):
            parts = raw
        else:
            raise ValueError("universe seed symbols must be a list or comma-separated string")
        symbols = [str(part).strip().upper() for part in parts if str(part).strip()]
        return list(dict.fromkeys(symbols))

    @staticmethod
    def _normalize_market(market: Any) -> str:
        text = str(market or "").strip().lower()
        if text in {"hk", "港股", "hkex"}:
            return "hk"
        if text in {"us", "美股", "usa"}:
            return "us"
        if text in {"cn", "a股", "ashare", "a-share"}:
            return "cn"
        raise ValueError(f"unsupported universe seed market: {market}")
