"""
Pytest configuration and fixtures for Stock Analysis API tests
"""

import pytest
from fastapi.testclient import TestClient

from src.main import app


@pytest.fixture
def client() -> TestClient:
    """FastAPI TestClient using real data sources (yfinance, etc.)"""
    return TestClient(app)


# Test constants
# Use NVDA instead of TQQQ for valuation/model tests
# TQQQ is an ETF without financial statements data
TEST_SYMBOL = "NVDA"  # NVIDIA - Has complete financial data
TEST_SYMBOL_ETF = "TQQQ"  # For testing endpoints that don't need financial data
