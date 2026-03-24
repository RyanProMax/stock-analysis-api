"""
Pytest configuration and fixtures for Stock Analysis API tests
"""

import pytest
from fastapi.testclient import TestClient

from src.main import app
from src.services.symbol_snapshot_refresh_service import symbol_snapshot_refresh_service


@pytest.fixture
def client(monkeypatch) -> TestClient:
    """FastAPI TestClient using real data sources (yfinance, etc.)"""
    monkeypatch.setattr(symbol_snapshot_refresh_service, "notify_request", lambda path: None)
    return TestClient(app)


# Test constants
# Use NVDA instead of TQQQ for valuation/model tests
# TQQQ is an ETF without financial statements data
TEST_SYMBOL = "NVDA"  # NVIDIA - Has complete financial data
TEST_SYMBOL_ETF = "TQQQ"  # For testing endpoints that don't need financial data
