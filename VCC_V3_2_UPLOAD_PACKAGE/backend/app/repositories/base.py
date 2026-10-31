"""
Repository Interfaces for VCC V3.2 Persistence Layer.
Decouples domain and audit business logic from direct ORM / database dependencies.
"""
from abc import ABC, abstractmethod
from typing import List, Optional, Any, Dict
from app.domain.contracts import SignalDecision, SignalOutcome, MarketSnapshot


class SignalRepository(ABC):

    @abstractmethod
    def save_signal(self, decision: SignalDecision) -> None:
        pass

    @abstractmethod
    def get_latest_signal(self, symbol: str) -> Optional[SignalDecision]:
        pass


class AuditRepository(ABC):

    @abstractmethod
    def save_audit_snapshot(self, audit_dict: Dict[str, Any]) -> str:
        pass

    @abstractmethod
    def get_audit_snapshot(self, snapshot_id: str) -> Optional[Dict[str, Any]]:
        pass

    @abstractmethod
    def get_unevaluated_snapshots(self, symbol: str) -> List[Dict[str, Any]]:
        pass


class OutcomeRepository(ABC):

    @abstractmethod
    def save_outcome(self, outcome: SignalOutcome) -> None:
        pass

    @abstractmethod
    def update_audit_outcome(self, snapshot_id: str, outcome_dict: Dict[str, Any]) -> None:
        pass


class PerformanceRepository(ABC):

    @abstractmethod
    def get_performance_stats(self, symbol: str) -> Dict[str, Any]:
        pass
