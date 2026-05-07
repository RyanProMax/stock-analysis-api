from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
from typing import Any, Iterable, Protocol

from ..model.trading import (
    AccountSnapshot,
    MarketSnapshot,
    OrderRequest,
    OrderSide,
    PositionSnapshot,
    SignalAction,
    StrategySignal,
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class MarketDataProvider(Protocol):
    source: str

    def get_market_snapshots(self, codes: Iterable[str]) -> list[MarketSnapshot]: ...


class Broker(Protocol):
    def get_account(self) -> AccountSnapshot: ...

    def get_positions(self) -> list[PositionSnapshot]: ...

    def submit_order(self, order: OrderRequest) -> dict[str, Any]: ...


class TradingLedger(Protocol):
    def has_order(self, idempotency_key: str) -> bool: ...

    def record_order(
        self,
        order: OrderRequest,
        *,
        run_id: str | None = None,
        broker_result: dict[str, Any] | None = None,
    ) -> None: ...

    def start_run(self, request: dict[str, Any]) -> str: ...

    def record_risk_decision(self, run_id: str, decision: "RiskDecision") -> None: ...

    def finish_run(self, run_id: str, result: dict[str, Any], *, status: str = "ok") -> None: ...


class InMemoryTradingLedger:
    def __init__(self) -> None:
        self._order_keys: set[str] = set()
        self._run_counter = 0

    def has_order(self, idempotency_key: str) -> bool:
        return idempotency_key in self._order_keys

    def record_order(
        self,
        order: OrderRequest,
        *,
        run_id: str | None = None,
        broker_result: dict[str, Any] | None = None,
    ) -> None:
        del run_id, broker_result
        self._order_keys.add(order.idempotency_key)

    def start_run(self, request: dict[str, Any]) -> str:
        del request
        self._run_counter += 1
        return f"memory-run-{self._run_counter}"

    def record_risk_decision(self, run_id: str, decision: "RiskDecision") -> None:
        del run_id, decision

    def finish_run(self, run_id: str, result: dict[str, Any], *, status: str = "ok") -> None:
        del run_id, result, status


class FixedThresholdStrategy:
    def __init__(
        self,
        *,
        strategy_version_id: str,
        buy_above: dict[str, float],
        quantity: int,
    ) -> None:
        self.strategy_version_id = strategy_version_id
        self.buy_above = {self._key(code): float(price) for code, price in buy_above.items()}
        self.quantity = int(quantity)

    def generate(
        self,
        snapshots: list[MarketSnapshot],
        account: AccountSnapshot,
        positions: list[PositionSnapshot],
    ) -> list[StrategySignal]:
        del account
        position_by_code = {self._key(position.code): position for position in positions}
        signals: list[StrategySignal] = []

        for snapshot in snapshots:
            code_key = self._key(snapshot.code)
            threshold = self.buy_above.get(code_key)
            if threshold is None or snapshot.price is None:
                continue
            position = position_by_code.get(code_key)
            if position is not None and position.quantity > 0:
                continue
            if snapshot.price >= threshold:
                signals.append(
                    StrategySignal(
                        strategy_version_id=self.strategy_version_id,
                        code=snapshot.code,
                        action=SignalAction.BUY,
                        quantity=self.quantity,
                        trigger_price=threshold,
                        rationale=f"price {snapshot.price} >= threshold {threshold}",
                        snapshot=snapshot,
                    )
                )
        return signals

    @staticmethod
    def _key(code: str) -> str:
        return str(code or "").strip().upper()


@dataclass(frozen=True)
class RiskDecision:
    status: str
    reason: str
    signal: StrategySignal
    request: OrderRequest | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "status": self.status,
            "reason": self.reason,
            "signal": self.signal.to_dict(),
        }
        if self.request is not None:
            payload["request"] = self.request.to_dict()
        return payload


class MaxNotionalRiskPolicy:
    def __init__(self, *, max_order_notional: float) -> None:
        self.max_order_notional = float(max_order_notional)

    def evaluate(
        self,
        signal: StrategySignal,
        account: AccountSnapshot,
        positions: list[PositionSnapshot],
        ledger: TradingLedger,
    ) -> RiskDecision:
        del positions
        idempotency_key = self._build_idempotency_key(signal)
        if ledger.has_order(idempotency_key):
            return RiskDecision(
                status="rejected",
                reason="duplicate_idempotency_key",
                signal=signal,
            )

        if signal.action == SignalAction.HOLD:
            return RiskDecision(status="skipped", reason="hold_signal", signal=signal)

        if signal.snapshot.price is None:
            return RiskDecision(status="rejected", reason="missing_price", signal=signal)

        notional = float(signal.snapshot.price) * signal.quantity
        if notional > self.max_order_notional:
            return RiskDecision(
                status="rejected",
                reason="order_notional_exceeds_limit",
                signal=signal,
            )

        if signal.action == SignalAction.BUY and account.cash < notional:
            return RiskDecision(status="rejected", reason="insufficient_cash", signal=signal)

        order = OrderRequest(
            code=signal.code,
            side=OrderSide(signal.action.value),
            quantity=signal.quantity,
            price=signal.snapshot.price,
            strategy_version_id=signal.strategy_version_id,
            idempotency_key=idempotency_key,
            reason=signal.rationale,
            trd_env="SIMULATE",
        )
        return RiskDecision(status="accepted", reason="accepted", signal=signal, request=order)

    @staticmethod
    def _build_idempotency_key(signal: StrategySignal) -> str:
        parts = [
            signal.strategy_version_id,
            signal.code,
            signal.action.value,
            str(signal.quantity),
            str(signal.trigger_price),
        ]
        return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


class TradingAutomationService:
    def __init__(
        self,
        *,
        market_data: MarketDataProvider,
        broker: Broker,
        strategy: FixedThresholdStrategy,
        risk_policy: MaxNotionalRiskPolicy,
        ledger: TradingLedger,
    ) -> None:
        self.market_data = market_data
        self.broker = broker
        self.strategy = strategy
        self.risk_policy = risk_policy
        self.ledger = ledger

    def run_once(self, codes: Iterable[str]) -> dict[str, Any]:
        requested_codes = [str(code).strip() for code in codes if str(code).strip()]
        run_request = {"codes": requested_codes, "count": len(requested_codes)}
        started_at = _utc_now()
        run_id = self.ledger.start_run(run_request)
        try:
            snapshots = self.market_data.get_market_snapshots(requested_codes)
            account = self.broker.get_account()
            positions = self.broker.get_positions()
            signals = self.strategy.generate(snapshots, account, positions)

            risk_decisions: list[dict[str, Any]] = []
            orders: list[dict[str, Any]] = []
            for signal in signals:
                decision = self.risk_policy.evaluate(signal, account, positions, self.ledger)
                risk_decisions.append(decision.to_dict())
                self.ledger.record_risk_decision(run_id, decision)
                if decision.status != "accepted" or decision.request is None:
                    continue

                broker_result = self.broker.submit_order(decision.request)
                self.ledger.record_order(
                    decision.request,
                    run_id=run_id,
                    broker_result=broker_result,
                )
                orders.append(
                    {
                        "request": decision.request.to_dict(),
                        "result": broker_result,
                    }
                )

            result = {
                "status": "ok",
                "run_id": run_id,
                "strategy_version": self.strategy.strategy_version_id,
                "started_at": started_at,
                "finished_at": _utc_now(),
                "source": getattr(self.market_data, "source", "unknown"),
                "request": run_request,
                "account": account.to_dict(),
                "positions": [position.to_dict() for position in positions],
                "snapshots": [snapshot.to_dict() for snapshot in snapshots],
                "signals": [signal.to_dict() for signal in signals],
                "risk_decisions": risk_decisions,
                "orders": orders,
            }
            self.ledger.finish_run(run_id, result, status="ok")
            return result
        except Exception as exc:
            self.ledger.finish_run(
                run_id,
                {
                    "status": "failed",
                    "run_id": run_id,
                    "strategy_version": self.strategy.strategy_version_id,
                    "started_at": started_at,
                    "finished_at": _utc_now(),
                    "source": getattr(self.market_data, "source", "unknown"),
                    "request": run_request,
                    "error": str(exc),
                },
                status="failed",
            )
            raise
