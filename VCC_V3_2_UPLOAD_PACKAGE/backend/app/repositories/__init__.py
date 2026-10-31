"""
Repositories Package Initializer
Exports decoupled repository interfaces and SQLAlchemy implementations.
"""
from app.repositories.base import (
    SignalRepository as BaseSignalRepository,
    AuditRepository as BaseAuditRepository,
    OutcomeRepository as BaseOutcomeRepository,
    PerformanceRepository as BasePerformanceRepository
)
from app.repositories.market_repository import MarketRepository, market_repository
from app.repositories.signal_repository import SignalRepository, signal_repository
from app.repositories.audit_repository import AuditRepository, audit_repository
from app.repositories.lifecycle_repository import LifecycleRepository, lifecycle_repository
from app.repositories.outcome_repository import OutcomeRepository, outcome_repository
from app.repositories.smart_money_repository import SmartMoneyRepository, smart_money_repository
from app.repositories.sqlalchemy_repository import SQLAlchemyPerformanceRepository, performance_repository

__all__ = [
    "MarketRepository",
    "market_repository",
    "SignalRepository",
    "signal_repository",
    "AuditRepository",
    "audit_repository",
    "LifecycleRepository",
    "lifecycle_repository",
    "OutcomeRepository",
    "outcome_repository",
    "SmartMoneyRepository",
    "smart_money_repository",
    "SQLAlchemyPerformanceRepository",
    "performance_repository"
]
